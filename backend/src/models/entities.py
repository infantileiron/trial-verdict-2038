from sqlalchemy import Column,Integer,String,Float,JSON,Text,UniqueConstraint,ForeignKey
from src.config.database import Base


class User(Base):
    __tablename__='users'
    id=Column(Integer,primary_key=True)
    email=Column(String(100),unique=True)
    password=Column(String(200))
    role=Column(String(20))


class Experiment(Base):
    __tablename__='experiments'
    id=Column(Integer,primary_key=True)
    code=Column(String(60),unique=True)
    name=Column(String(120))
    starts_at=Column(String(40))
    ends_at=Column(String(40))
    a_ratio=Column(Float)
    hypothesis=Column(Text)
    # exposure: 分母取曝光日志中的去重用户（既有口径）
    # roster:   分母取独立分组名册中的全体成员（新实验口径）
    denominator=Column(String(20),nullable=False,default='exposure',server_default='exposure')


class Event(Base):
    __tablename__='events'
    __table_args__=(UniqueConstraint('experiment_id','user_key','kind',name='uq_exp_user_kind'),)
    id=Column(Integer,primary_key=True)
    experiment_id=Column(Integer,ForeignKey('experiments.id'))
    user_key=Column(String(80))
    group=Column(String(1))
    kind=Column(String(20))
    occurred_at=Column(String(40))


class RosterVersion(Base):
    """一次整版导入的分组名册。版本不可原地改写，只能导入新版本。"""
    __tablename__='roster_versions'
    __table_args__=(
        UniqueConstraint('experiment_id','version_no',name='uq_roster_exp_version'),
        UniqueConstraint('experiment_id','import_key',name='uq_roster_exp_import_key'),
        UniqueConstraint('experiment_id','checksum',name='uq_roster_exp_checksum'),
    )
    id=Column(Integer,primary_key=True)
    experiment_id=Column(Integer,ForeignKey('experiments.id'),nullable=False)
    version_no=Column(Integer,nullable=False)
    # pending=待核对 ready=可用 locked=已锁定 conflict=冲突 superseded=已被新版本取代
    state=Column(String(20),nullable=False,default='pending')
    checksum=Column(String(64),nullable=False)
    member_count=Column(Integer,nullable=False,default=0)
    group_a_count=Column(Integer,nullable=False,default=0)
    group_b_count=Column(Integer,nullable=False,default=0)
    import_key=Column(String(80),nullable=True)
    note=Column(Text,default='')
    conflict_reason=Column(Text,default='')
    created_by=Column(String(100),default='')
    created_at=Column(String(40),default='')
    verified_by=Column(String(100),default='')
    verified_at=Column(String(40),default='')
    locked_by=Column(String(100),default='')
    locked_at=Column(String(40),default='')


class RosterMember(Base):
    __tablename__='roster_members'
    __table_args__=(UniqueConstraint('roster_version_id','user_key',name='uq_roster_member'),)
    id=Column(Integer,primary_key=True)
    roster_version_id=Column(Integer,ForeignKey('roster_versions.id'),nullable=False)
    user_key=Column(String(80),nullable=False)
    group=Column(String(1),nullable=False)


class StagedEvent(Base):
    """名册尚未生效或用户不在名册时，事件先暂存；名册生效后原子地归属一次。"""
    __tablename__='staged_events'
    __table_args__=(UniqueConstraint('experiment_id','user_key','kind',name='uq_staged_exp_user_kind'),)
    id=Column(Integer,primary_key=True)
    experiment_id=Column(Integer,ForeignKey('experiments.id'),nullable=False)
    user_key=Column(String(80),nullable=False)
    group=Column(String(1),nullable=False)
    kind=Column(String(20),nullable=False)
    occurred_at=Column(String(40),nullable=False)
    received_at=Column(String(40),default='')
    applied_event_id=Column(Integer,ForeignKey('events.id'),nullable=True)
    applied_roster_version_id=Column(Integer,ForeignKey('roster_versions.id'),nullable=True)


class Decision(Base):
    __tablename__='decisions'
    id=Column(Integer,primary_key=True)
    experiment_id=Column(Integer,ForeignKey('experiments.id'))
    state=Column(String(20),default='queued')
    snapshot=Column(JSON)
    result=Column(JSON,nullable=True)
    error=Column(Text,default='')
    rationale=Column(Text,default='')
    action=Column(String(30),default='')
    published_by=Column(String(100),default='')
    published_at=Column(String(40),default='')


class Audit(Base):
    __tablename__='audits'
    id=Column(Integer,primary_key=True)
    actor=Column(String(100))
    action=Column(String(200))
    created=Column(String(40))
