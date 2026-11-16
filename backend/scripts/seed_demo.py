from datetime import datetime,timezone,timedelta
from types import SimpleNamespace
from src.config.database import Base,engine,Session
from src.models.entities import User,Experiment,Event,RosterVersion,StagedEvent
from src.utils.security import hash_password
from src.schemas.business import RosterImportInput
from src.services import roster


def seed():
 Base.metadata.create_all(engine)
 with Session() as s:
  for role in ('admin','analyst','viewer'):
   email=role+'@demo.local'
   if not s.query(User).filter_by(email=email).first():s.add(User(email=email,role=role,password=hash_password('Demo123!')))
  s.commit()
  today=datetime.now(timezone.utc).replace(hour=0,minute=0,second=0,microsecond=0)
  for code,name,ends in [('LJ-1115-A','首次引导文案 / 成熟对照',today-timedelta(days=1)),('LJ-1115-B','快捷模板入口 / 观察中',today+timedelta(days=3))]:
   exp=s.query(Experiment).filter_by(code=code).first()
   if not exp:
    exp=Experiment(code=code,name=name,starts_at=(today-timedelta(days=7)).isoformat(),ends_at=ends.isoformat(),a_ratio=.5,hypothesis='更清晰的首次引导能提升首次激活率，预先固定观察期与分流比例');s.add(exp);s.flush()
   if code.endswith('-A'):
    stamp=(datetime.fromisoformat(exp.starts_at)+timedelta(hours=12)).isoformat()
    for i in range(1200):
     group='A' if i<600 else 'B';key=f'LJ-U{i+1:04}';activated=(i<120 if group=='A' else i-600<180)
     for kind in ['exposure']+(['activation'] if activated else []):
      if not s.query(Event).filter_by(experiment_id=exp.id,user_key=key,kind=kind).first():s.add(Event(experiment_id=exp.id,user_key=key,group=group,kind=kind,occurred_at=stamp))
  s.commit()
  seed_roster(s,today)
  print({'users':s.query(User).count(),'experiments':s.query(Experiment).count(),'events':s.query(Event).count(),
         'rosters':s.query(RosterVersion).count(),'staged':s.query(StagedEvent).count()})


def seed_roster(s,today):
 """名册分母演示实验：整版导入→核对→锁定，曝光日志故意缺报 40 人、混入 5 名未入册者。"""
 code='LJ-1116-R'
 exp=s.query(Experiment).filter_by(code=code).first()
 if not exp:
  exp=Experiment(code=code,name='新版入门引导 / 名册分母',starts_at=(today-timedelta(days=10)).isoformat(),
                 ends_at=(today-timedelta(days=1)).isoformat(),a_ratio=.5,denominator='roster',
                 hypothesis='新版入门引导以名册为分母统计激活，避免曝光漏报抬高试用效果')
  s.add(exp);s.flush()
 if s.query(RosterVersion).filter_by(experiment_id=exp.id).first():return
 stamp=(datetime.fromisoformat(exp.starts_at)+timedelta(hours=12)).isoformat()
 analyst=SimpleNamespace(email='analyst@demo.local');admin=SimpleNamespace(email='admin@demo.local')
 # 名册 400 人：RN-0001..RN-0200 为 A 组，RN-0201..RN-0400 为 B 组。
 roster_pairs=[(f'RN-{i:04}',('A' if i<=200 else 'B')) for i in range(1,401)]
 data=RosterImportInput(members=[{'user_key':k,'group':g} for k,g in roster_pairs],note='整版导入 400 人',import_key='seed-1116-v1')
 v=roster.import_version(s,exp,data,analyst)
 # 锁定前采集事件：先暂存，锁定生效时归属。
 activated_a={f'RN-{i:04}' for i in range(1,201) if i<=30}
 activated_b={f'RN-{i:04}' for i in range(201,401) if i<=201+59}
 # 曝光日志只覆盖 360 人（A 组少 25 人、B 组少 15 人），其余 40 人只有名册没有曝光。
 missing_a={f'RN-{i:04}' for i in range(176,201)}
 missing_b={f'RN-{i:04}' for i in range(386,401)}
 for i in range(1,401):
  key=f'RN-{i:04}';group='A' if i<=200 else 'B'
  if key in missing_a or key in missing_b:continue
  s.add(StagedEvent(experiment_id=exp.id,user_key=key,group=group,kind='exposure',occurred_at=stamp,received_at=stamp))
  if key in activated_a or key in activated_b:
   s.add(StagedEvent(experiment_id=exp.id,user_key=key,group=group,kind='activation',occurred_at=stamp,received_at=stamp))
 # 5 条曝光来自未入册用户，锁定后保持未归属，等待补名册或人工处理。
 for i in range(1,6):
  s.add(StagedEvent(experiment_id=exp.id,user_key=f'GHOST-{i:02}',group='A' if i%2 else 'B',kind='exposure',occurred_at=stamp,received_at=stamp))
 s.commit()
 roster.verify(s,exp,v,analyst)
 roster.lock(s,exp,v,admin)


if __name__=='__main__':seed()
