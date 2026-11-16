import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
_URL=os.environ['DATABASE_URL']
_OPTS={'pool_pre_ping':True}
# MySQL 默认 REPEATABLE READ 会让取得行锁后的普通读取仍停留在旧快照，
# 因此显式使用 READ COMMITTED，保证名册锁定与事件采集并发时看到最新提交。
if _URL.startswith('mysql'):
    _OPTS['isolation_level']='READ COMMITTED'
engine=create_engine(_URL,**_OPTS)
Session=sessionmaker(bind=engine,expire_on_commit=False)
Base=declarative_base()
def db():
 with Session() as s: yield s
