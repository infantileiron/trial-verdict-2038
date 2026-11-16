from datetime import datetime,timezone
from src.models.entities import Audit
def utc(t):return t.astimezone(timezone.utc).isoformat()
def audit(s,u,action):
 s.add(Audit(actor=u.email,action=action,created=datetime.now(timezone.utc).isoformat()))
 try:s.commit()
 except Exception:s.rollback()
def dump(obj):return {c.name:getattr(obj,c.name) for c in obj.__table__.columns if c.name!='password'}
