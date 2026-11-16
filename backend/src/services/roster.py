"""分组名册、暂存事件与曝光对账。

名册是新实验的激活分母：无论用户是否上报曝光，名册全体都进入分母。
事件一律先暂存；名册锁定（生效）后在同一事务内原子归属，唯一约束保证只归属一次。
"""
import hashlib
from datetime import datetime,timezone
from fastapi import HTTPException
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from scipy.stats import chi2
from src.models.entities import Event,Experiment,RosterVersion,RosterMember,StagedEvent
from src.services.business import dump

MEMBER_PAGE=200


def _lock_experiment(s,exp_id):
    """对实验行做无操作 UPDATE，取得写锁。

    MySQL 下等价于 SELECT ... FOR UPDATE；SQLite 下取得库写锁。名册导入、锁定与
    事件采集都用它串行化，避免"检查未锁定→插入→锁定扫描已过"导致暂存事件滞留。
    """
    s.execute(update(Experiment).where(Experiment.id==exp_id).values(code=Experiment.code))


def now():
    return datetime.now(timezone.utc).isoformat()


def latest(s,exp_id):
    return s.query(RosterVersion).filter_by(experiment_id=exp_id).order_by(RosterVersion.version_no.desc()).first()


def active(s,exp_id):
    """生效版本：最新已锁定版本。待核对版本不参与分析，也不影响已生效版本。"""
    return s.query(RosterVersion).filter(RosterVersion.experiment_id==exp_id,RosterVersion.state=='locked').order_by(RosterVersion.version_no.desc()).first()


def version(s,i):
    r=s.get(RosterVersion,i)
    if not r:raise HTTPException(404,'名册版本不存在')
    return r


def member_group(s,version_id,user_key):
    m=s.query(RosterMember).filter_by(roster_version_id=version_id,user_key=user_key).first()
    return m.group if m else None


def members(s,version_id):
    return s.query(RosterMember).filter_by(roster_version_id=version_id).order_by(RosterMember.user_key).all()


def checksum_pairs(pairs):
    body='\n'.join(f'{key}\t{group}' for key,group in sorted(pairs))
    return hashlib.sha256(body.encode()).hexdigest()


def checksum(rows):
    return checksum_pairs([(m.user_key,m.group) for m in rows])


def dump_version(v):
    d=dump(v)
    d['can_analyse']=v.state=='locked'
    return d


def import_version(s,exp,data,user):
    """整版导入。相同 import_key 或相同内容的重试返回已有版本，不新增成员。"""
    if exp.denominator!='roster':
        raise HTTPException(409,'该实验按曝光统计，不能导入分组名册；请为新实验选择名册分母')
    checksum_value=checksum(data.members)
    if data.import_key:
        # 同一导入键的重试返回同一版本；键与内容不一致说明误用了旧键。
        existing=s.query(RosterVersion).filter_by(experiment_id=exp.id,import_key=data.import_key).first()
        if existing:
            if existing.checksum!=checksum_value:
                raise HTTPException(409,'导入键已被另一份名册占用，请使用新的导入键')
            return existing
    else:
        existing=s.query(RosterVersion).filter_by(experiment_id=exp.id,checksum=checksum_value).first()
        if existing:return existing
    # 写锁串行分配版本号，并发重试不会得到两个同号版本。
    _lock_experiment(s,exp.id)
    latest_row=latest(s,exp.id)
    number=(latest_row.version_no+1) if latest_row else 1
    a=sum(1 for m in data.members if m.group=='A')
    v=RosterVersion(experiment_id=exp.id,version_no=number,state='pending',checksum=checksum_value,
                    member_count=len(data.members),group_a_count=a,group_b_count=len(data.members)-a,
                    import_key=data.import_key,note=data.note,created_by=user.email,created_at=now())
    s.add(v)
    try:s.flush()
    except IntegrityError:
        # 并发重试：唯一约束保证同一内容/同一导入键只会落一个版本。
        s.rollback()
        again=s.query(RosterVersion).filter_by(experiment_id=exp.id,checksum=checksum_value).first()
        if again:return again
        raise HTTPException(409,'名册版本并发冲突，请重试')
    for m in data.members:s.add(RosterMember(roster_version_id=v.id,user_key=m.user_key,group=m.group))
    s.commit()
    return v


def _combined(s,exp_id):
    """已归属事件与暂存事件合并视图，用于重复/跨组校验与对账。"""
    rows=[{'user_key':e.user_key,'group':e.group,'kind':e.kind,'occurred_at':e.occurred_at,'source':'attributed','event_id':e.id} for e in s.query(Event).filter_by(experiment_id=exp_id).all()]
    rows+=[{'user_key':e.user_key,'group':e.group,'kind':e.kind,'occurred_at':e.occurred_at,'source':'staged','event_id':e.applied_event_id} for e in s.query(StagedEvent).filter_by(experiment_id=exp_id).all()]
    return rows


def conflicts(s,exp,v):
    """判定一个名册版本能否投入使用。冲突版本不允许分析。"""
    found=[]
    if not v.member_count:found.append('名册为空')
    if not v.group_a_count or not v.group_b_count:found.append('名册必须同时包含 A、B 两组用户')
    roster_group={m.user_key:m.group for m in members(s,v.id)}
    by_user={}
    for e in _combined(s,exp.id):by_user.setdefault(e['user_key'],set()).add(e['group'])
    for key,groups in sorted(by_user.items()):
        if len(groups)>1:
            found.append(f'用户 {key} 同时出现在 A、B 两组')
        elif key in roster_group and roster_group[key] not in groups:
            found.append(f'用户 {key} 事件组别 {next(iter(groups))} 与名册组别 {roster_group[key]} 不一致')
    return list(dict.fromkeys(found))


def _apply_one(s,exp_id,v,staged):
    """把一条暂存事件归入正式事件表；重复调用不会新增事件。"""
    existing=s.query(Event).filter_by(experiment_id=exp_id,user_key=staged.user_key,kind=staged.kind).first()
    if existing:
        if existing.group!=staged.group or member_group(s,v.id,staged.user_key)!=staged.group:
            return 'conflict'
        if staged.applied_event_id!=existing.id:
            staged.applied_event_id=existing.id
            staged.applied_roster_version_id=v.id
        return 'existing'
    group=member_group(s,v.id,staged.user_key)
    if group is None:return 'unrostered'
    if group!=staged.group:return 'conflict'
    e=Event(experiment_id=exp_id,user_key=staged.user_key,group=group,kind=staged.kind,occurred_at=staged.occurred_at)
    try:
        with s.begin_nested():s.add(e);s.flush()
    except IntegrityError:
        # 另一路径已归属同一实验/用户/类型；回读既有事件，保证只归属一次。
        existing=s.query(Event).filter_by(experiment_id=exp_id,user_key=staged.user_key,kind=staged.kind).first()
        if not existing:raise
        if existing.group!=group:return 'conflict'
        staged.applied_event_id=existing.id
        staged.applied_roster_version_id=v.id
        return 'existing'
    staged.applied_event_id=e.id
    staged.applied_roster_version_id=v.id
    return 'applied'


def apply_staged(s,exp_id,v,commit=False):
    """归属所有未归属的暂存事件；调用方负责事务边界。

    与采集路径共用实验写锁，多 worker 同时恢复时也只会归属一次。
    """
    _lock_experiment(s,exp_id)
    pending=s.query(StagedEvent).filter(StagedEvent.experiment_id==exp_id,StagedEvent.applied_event_id.is_(None)).order_by(StagedEvent.id).all()
    result={'applied':0,'existing':0,'unrostered':0,'conflict':0}
    for item in pending:result[_apply_one(s,exp_id,v,item)]+=1
    if commit:s.commit()
    return result


def recover(s):
    """启动恢复：名册已锁定但存在未归属暂存事件时补做归属（幂等）。"""
    for v in s.query(RosterVersion).filter_by(state='locked').all():
        if s.query(StagedEvent).filter_by(experiment_id=v.experiment_id,applied_event_id=None).count():
            apply_staged(s,v.experiment_id,v,commit=True)


def verify(s,exp,v,user):
    if v.state in ('locked','superseded'):
        raise HTTPException(409,'名册已锁定或已被新版本取代，不能再核对')
    if v.state=='conflict':
        raise HTTPException(409,'该名册版本存在冲突，已拒绝分析；请导入新的完整版本')
    issues=conflicts(s,exp,v)
    if issues:
        v.state='conflict';v.conflict_reason='；'.join(issues[:20])
    else:
        v.state='ready';v.conflict_reason=''
    v.verified_by=user.email;v.verified_at=now()
    s.commit()
    return v


def lock(s,exp,v,user):
    """从可用到锁定（生效）。锁定与暂存归属在同一事务内完成，中断可重入。

    以实验行锁与采集路径串行化：锁定扫描前不会再有新事件插入，锁定提交后
    采集方会看到生效版本并直接归属，因此暂存事件不遗漏且只归属一次。
    """
    if v.state=='locked':return v,apply_staged(s,exp.id,v,commit=True)
    if v.state in ('conflict','superseded'):
        raise HTTPException(409,'冲突或已取代的名册版本不能锁定')
    if v.state!='ready':raise HTTPException(409,'名册需先核对通过（可用）才能锁定')
    current=latest(s,exp.id)
    if current and current.id!=v.id:
        raise HTTPException(409,'已有更新版本的名册，请核对并锁定最新版本')
    _lock_experiment(s,exp.id)
    s.refresh(v)
    if v.state=='locked':return v,apply_staged(s,exp.id,v,commit=True)
    if v.state!='ready':raise HTTPException(409,'名册状态已变化，请刷新后重试')
    issues=conflicts(s,exp,v)
    if issues:
        v.state='conflict';v.conflict_reason='；'.join(issues[:20]);s.commit()
        raise HTTPException(409,'名册存在跨组冲突，已拒绝锁定与分析')
    v.state='locked';v.locked_by=user.email;v.locked_at=now()
    for other in s.query(RosterVersion).filter(RosterVersion.experiment_id==exp.id,RosterVersion.id!=v.id,RosterVersion.state=='locked').all():
        other.state='superseded'
    s.flush()
    summary=apply_staged(s,exp.id,v)
    s.commit()
    return v,summary


def record_event(s,exp,data,stamp,user):
    """名册实验的事件先暂存；生效名册存在时在同一事务内直接归属一次。"""
    # 与锁定路径共用实验行锁：要么看到未生效并留待归属，要么看到已生效并直接归属，
    # 不会出现"检查为未生效、插入后才发现已生效又永远无人归属"的遗漏。
    _lock_experiment(s,exp.id)
    roster=active(s,exp.id)
    prior=[e for e in _combined(s,exp.id) if e['user_key']==data.user_key]
    if any(e['group']!=data.group for e in prior):raise HTTPException(409,'同一用户不能跨组，需排查分流污染')
    if any(e['kind']==data.kind for e in prior):raise HTTPException(409,'重复事件：同一实验/用户/事件类型只记一次')
    if data.kind=='activation':
        # 名册分母允许激活缺失曝光（这正是漏报要暴露的情形），
        # 但曝光已上报时仍要求激活不早于曝光。
        exposure=next((e for e in prior if e['kind']=='exposure'),None)
        if exposure and stamp<exposure['occurred_at']:raise HTTPException(422,'激活时间不能早于曝光')
    else:
        activation=next((e for e in prior if e['kind']=='activation'),None)
        if activation and stamp>activation['occurred_at']:raise HTTPException(422,'曝光时间不能晚于已上报的激活')
    locked=roster is not None and roster.state=='locked'
    group=member_group(s,roster.id,data.user_key) if locked else None
    if locked and group and group!=data.group:
        raise HTTPException(409,f'该用户在名册中属于 {group} 组，不能按 {data.group} 组录入')
    staged=StagedEvent(experiment_id=exp.id,user_key=data.user_key,group=data.group,kind=data.kind,
                       occurred_at=stamp,received_at=now())
    s.add(staged);s.flush()
    event=None;attribution='staged'
    if locked:
        attribution=_apply_one(s,exp.id,roster,staged)
        event=s.get(Event,staged.applied_event_id) if staged.applied_event_id else None
    s.commit()
    return staged,event,attribution


def reconcile(s,exp,v):
    """对账名册与曝光日志：缺报、未入册、跨组冲突。"""
    member_rows=members(s,v.id)
    roster_group={m.user_key:m.group for m in member_rows}
    combined=_combined(s,exp.id)
    exposure_keys={e['user_key'] for e in combined if e['kind']=='exposure'}
    exposures=exposure_keys&set(roster_group)
    missing=[{'user_key':m.user_key,'group':m.group} for m in member_rows if m.user_key not in exposure_keys]
    unrostered=[];seen=set()
    for e in combined:
        if e['user_key'] not in roster_group and e['user_key'] not in seen:
            seen.add(e['user_key']);unrostered.append({'user_key':e['user_key'],'group':e['group'],'kind':e['kind'],'source':'暂存事件' if e['source']=='staged' else '已归属事件'})
    cross=[];users={}
    for e in combined:users.setdefault(e['user_key'],set()).add(e['group'])
    for key,groups in sorted(users.items()):
        if len(groups)>1:
            cross.append({'user_key':key,'detail':'同时出现在 A、B 两组','groups':sorted(groups)})
        elif key in roster_group and roster_group[key] not in groups:
            cross.append({'user_key':key,'detail':f'事件组别 {next(iter(groups))} 与名册 {roster_group[key]} 不一致','groups':sorted(groups)})
    activated={g:len({e['user_key'] for e in combined if e['kind']=='activation' and roster_group.get(e['user_key'])==g}) for g in ('A','B')}
    return {
        'version_id':v.id,'version_no':v.version_no,'version_state':v.state,
        'roster_total':len(member_rows),'roster_a':sum(1 for m in member_rows if m.group=='A'),'roster_b':sum(1 for m in member_rows if m.group=='B'),
        'exposure_total':len(exposures),'exposure_a':sum(1 for k in exposures if roster_group[k]=='A'),'exposure_b':sum(1 for k in exposures if roster_group[k]=='B'),
        'activated_a':activated['A'],'activated_b':activated['B'],
        'missing_report_total':len(missing),'missing_report_a':sum(1 for m in missing if m['group']=='A'),'missing_report_b':sum(1 for m in missing if m['group']=='B'),
        'missing_report':missing[:MEMBER_PAGE],'missing_truncated':len(missing)>MEMBER_PAGE,
        'unrostered_total':len(unrostered),'unrostered':unrostered[:MEMBER_PAGE],'unrostered_truncated':len(unrostered)>MEMBER_PAGE,
        'cross_group_total':len(cross),'cross_group':cross[:MEMBER_PAGE],'cross_group_truncated':len(cross)>MEMBER_PAGE,
        'staged_pending':s.query(StagedEvent).filter_by(experiment_id=exp.id,applied_event_id=None).count(),
        'staged_events':[{'id':e.id,'user_key':e.user_key,'group':e.group,'kind':e.kind,'occurred_at':e.occurred_at,
                          'applied':e.applied_event_id is not None,'attributed':e.user_key in roster_group} for e in
                         s.query(StagedEvent).filter_by(experiment_id=exp.id).order_by(StagedEvent.id.desc()).limit(MEMBER_PAGE).all()],
        'latest_version':(latest(s,exp.id) and {'id':latest(s,exp.id).id,'version_no':latest(s,exp.id).version_no,'state':latest(s,exp.id).state}) or None,
        'active_version_id':(active(s,exp.id) and active(s,exp.id).id),
        'attributed_events':s.query(Event).filter_by(experiment_id=exp.id).count(),
    }


def analysis_version(s,exp_id):
    """裁决使用的版本。最新版冲突时直接返回冲突版，确保冲突版本拒绝分析。"""
    latest_v=latest(s,exp_id)
    if latest_v is not None and latest_v.state=='conflict':return latest_v
    return active(s,exp_id) or latest_v


def analysis_blockers(s,exp,v):
    if v is None:return ['尚未导入分组名册，无法以名册为分母分析']
    blockers=[]
    if v.state=='conflict':
        blockers.append('名册冲突版本禁止分析：'+(v.conflict_reason or '存在跨组冲突'))
    elif v.state!='locked':
        blockers.append(f'名册版本 v{v.version_no} 尚未锁定（当前 {v.state}），不能进入裁决')
    rec=reconcile(s,exp,v)
    if rec['roster_a']<2 or rec['roster_b']<2:blockers.append('名册每组至少需2名成员')
    if rec['roster_total']:
        expected=[rec['roster_total']*exp.a_ratio,rec['roster_total']*(1-exp.a_ratio)]
        srm=sum((o-e)**2/e for o,e in zip([rec['roster_a'],rec['roster_b']],expected) if e)
        if float(chi2.sf(srm,1))<.01:blockers.append('名册分流 SRM p<0.01，先排查随机分流')
    n0,n1=rec['roster_a'],rec['roster_b'];c0,c1=rec['activated_a'],rec['activated_b']
    if min(n0,n1)<20 or min(c0,n0-c0,c1,n1-c1)<5:
        blockers.append('每组至少20名名册成员且成功/失败各至少5人，当前不满足正态近似')
    if rec['cross_group_total']:blockers.append('对账发现跨组冲突，需先处理名册与事件归属')
    return blockers


def snapshot_roster(s,exp,v):
    return {'version':dump_version(v),'members':[{'user_key':m.user_key,'group':m.group} for m in members(s,v.id)],
            'reconciliation':reconcile(s,exp,v)}
