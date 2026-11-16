import math,hashlib,json
from datetime import datetime,timezone
from scipy.stats import norm,chi2

VERSION='two-proportion-srm-1.0'
VERSION_ROSTER='two-proportion-roster-1.1'


def _checksum(snapshot):
    return hashlib.sha256(json.dumps(snapshot,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def calculate(snapshot):
    exp=snapshot['experiment'];events=snapshot['events']
    roster=snapshot.get('roster')
    if exp.get('denominator')=='roster' or roster:
        return _roster(exp,events,roster,snapshot)
    return _exposure(exp,events,snapshot)


def _common(exp,n0,n1,c0,c1,snapshot,extra):
    if min(n0,n1)<2:raise ValueError('每组至少需2名分母用户，无法计算当前比例差异')
    p0,p1=c0/n0,c1/n1;delta=p1-p0;pooled=(c0+c1)/(n0+n1)
    se0=math.sqrt(pooled*(1-pooled)*(1/n0+1/n1))
    z=delta/se0 if se0 else 0.0;pv=float(2*norm.sf(abs(z))) if se0 else 1.0
    se=math.sqrt(p0*(1-p0)/n0+p1*(1-p1)/n1);margin=float(norm.ppf(.975))*se
    expected=[(n0+n1)*exp['a_ratio'],(n0+n1)*(1-exp['a_ratio'])]
    srm=sum((a-b)**2/b for a,b in zip([n0,n1],expected));srm_p=float(chi2.sf(srm,1))
    approximate=min(n0,n1)>=20 and min(c0,n0-c0,c1,n1-c1)>=5
    matured=datetime.now(timezone.utc)>=datetime.fromisoformat(exp['ends_at'])
    return dict(n_a=n0,n_b=n1,activated_a=c0,activated_b=c1,rate_a=p0,rate_b=p1,difference=delta,
                relative_lift=delta/p0 if p0 else None,z=z,p_value=pv,
                ci_low=max(-1,delta-margin),ci_high=min(1,delta+margin),
                srm_chi2=srm,srm_p=srm_p,expected_a=expected[0],expected_b=expected[1],
                matured=matured,approximation_valid=approximate,
                significant_positive=delta>0 and pv<.05,
                checksum=_checksum(snapshot),**extra)


def _exposure(exp,events,snapshot):
    exposed={g:{e['user_key'] for e in events if e['group']==g and e['kind']=='exposure'} for g in ('A','B')}
    activated={g:{e['user_key'] for e in events if e['group']==g and e['kind']=='activation'}&exposed[g] for g in ('A','B')}
    n0,n1=[len(exposed[g]) for g in ('A','B')];c0,c1=[len(activated[g]) for g in ('A','B')]
    reasons=[]
    if not (datetime.now(timezone.utc)>=datetime.fromisoformat(exp['ends_at'])):reasons.append('实验未到预定结束时间，禁止提前发布')
    result=_common(exp,n0,n1,c0,c1,snapshot,{})
    if result['srm_p']<.01:reasons.append('SRM p<0.01，先排查随机分流与事件采集')
    if not result['approximation_valid']:reasons.append('每组至少20人且成功/失败各至少5人，当前不满足正态近似')
    result.update(denominator='exposure',roster=None,reconciliation=None,exposure_n_a=n0,exposure_n_b=n1,
                  release_eligible=not reasons,block_reasons=reasons,version=VERSION,
                  method='双侧双比例z检验；95%绝对提升Wald区间；SRM卡方df=1；曝光用户去重，激活为曝光子集；差异方向B−A')
    return result


def _roster(exp,events,roster,snapshot):
    if not roster:raise ValueError('名册实验缺少冻结的分组名册快照，无法分析')
    version=roster['version']
    if version['state']=='conflict':raise ValueError('名册冲突版本禁止分析：'+(version.get('conflict_reason') or '存在跨组冲突'))
    if version['state']!='locked':raise ValueError(f"名册版本 v{version['version_no']} 尚未锁定，不能进入裁决")
    group={m['user_key']:m['group'] for m in roster['members']}
    n0=sum(1 for g in group.values() if g=='A');n1=len(group)-n0
    activated={g:{e['user_key'] for e in events if e['kind']=='activation' and group.get(e['user_key'])==g} for g in ('A','B')}
    c0,c1=len(activated['A']),len(activated['B'])
    exposures={g:{e['user_key'] for e in events if e['kind']=='exposure' and group.get(e['user_key'])==g} for g in ('A','B')}
    rec=roster.get('reconciliation') or {}
    extra=dict(denominator='roster',roster=version,reconciliation=rec,
               exposure_n_a=len(exposures['A']),exposure_n_b=len(exposures['B']),
               missing_report_total=rec.get('missing_report_total',0),
               unrostered_total=rec.get('unrostered_total',0),
               cross_group_total=rec.get('cross_group_total',0))
    reasons=[]
    if not (datetime.now(timezone.utc)>=datetime.fromisoformat(exp['ends_at'])):reasons.append('实验未到预定结束时间，禁止提前发布')
    result=_common(exp,n0,n1,c0,c1,snapshot,extra)
    if result['srm_p']<.01:reasons.append('名册分流 SRM p<0.01，先排查随机分流')
    if extra['cross_group_total']:reasons.append('对账发现跨组冲突，需先处理名册与事件归属')
    if not result['approximation_valid']:reasons.append('每组至少20名名册成员且成功/失败各至少5人，当前不满足正态近似')
    result.update(release_eligible=not reasons,block_reasons=reasons,version=VERSION_ROSTER,
                  method='分母为冻结名册全体成员（非曝光人群）；激活按名册组别汇总且在名册内的去重用户；'
                         '双侧双比例z检验；95%绝对提升Wald区间；SRM卡方df=1；差异方向B−A')
    return result
