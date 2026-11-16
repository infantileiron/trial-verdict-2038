"""幂等 schema 升级：为已存在的旧库补列，新库由 metadata.create_all 直接建全。"""
import logging
from sqlalchemy import inspect,text


def ensure_schema(engine):
    inspector=inspect(engine)
    if 'experiments' in inspector.get_table_names():
        columns={c['name'] for c in inspector.get_columns('experiments')}
        if 'denominator' not in columns:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE experiments ADD COLUMN denominator VARCHAR(20) NOT NULL DEFAULT 'exposure'"))
            logging.info('added experiments.denominator')
