import os,time,json,logging
from pathlib import Path
import redis
from src.config.database import Session
from src.models.entities import Decision
from src.services.analysis import calculate

_r=redis.Redis.from_url(os.environ['REDIS_URL'])


def recover(s):
    """启动恢复：回收中断的裁决任务，并补做名册暂存归属（幂等）。"""
    for pending in s.query(Decision).filter(Decision.state.in_(['queued','running'])).all():
        pending.state='queued';_r.rpush('trial:decisions',pending.id)
    s.commit()
    from src.services.roster import recover as roster_recover
    roster_recover(s)


if __name__=='__main__':
    r=_r
    with Session() as recovery:recover(recovery)
    while True:
        Path('/tmp/heartbeat').touch()
        try:
            item=r.blpop('trial:decisions',timeout=3)
            if not item:continue
            with Session() as s:
                row=s.get(Decision,int(item[1]))
                if not row or row.state!='queued':continue
                row.state='running';s.commit()
                try:
                    row.result=calculate(row.snapshot);row.state='done'
                    Path('/artifacts/trial-verdict-'+str(row.id)+'.json').write_text(json.dumps(row.result,ensure_ascii=False))
                except Exception as e:row.state='failed';row.error=str(e)
                s.commit()
        except Exception:logging.exception('worker');time.sleep(2)
