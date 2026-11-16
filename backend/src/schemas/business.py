from datetime import datetime,timezone
from typing import Literal
from pydantic import BaseModel,Field,model_validator


class Login(BaseModel):
    email:str
    password:str


class ExperimentInput(BaseModel):
    code:str=Field(min_length=1,max_length=60)
    name:str=Field(min_length=2,max_length=120)
    starts_at:datetime
    ends_at:datetime
    a_ratio:float=Field(default=.5,ge=.1,le=.9,allow_inf_nan=False)
    hypothesis:str=Field(min_length=5,max_length=2000)
    denominator:Literal['exposure','roster']='exposure'

    @model_validator(mode='after')
    def dates(self):
        if self.starts_at.tzinfo is None or self.ends_at.tzinfo is None:
            raise ValueError('时间必须带时区')
        if self.ends_at<=self.starts_at:
            raise ValueError('结束时间必须晚于开始时间')
        return self


class EventInput(BaseModel):
    experiment_id:int=Field(gt=0)
    user_key:str=Field(min_length=1,max_length=80)
    group:Literal['A','B']
    kind:Literal['exposure','activation']
    occurred_at:datetime

    @model_validator(mode='after')
    def dates(self):
        if self.occurred_at.tzinfo is None:
            raise ValueError('事件时间必须带时区')
        return self


class RosterMemberInput(BaseModel):
    user_key:str=Field(min_length=1,max_length=80)
    group:Literal['A','B']


class RosterImportInput(BaseModel):
    # 整版导入：本次提交即一份完整名册，不做增量合并
    members:list[RosterMemberInput]=Field(min_length=1,max_length=200000)
    note:str=Field(default='',max_length=1000)
    # 幂等键：相同 import_key 重试返回同一个版本，不新增成员
    import_key:str|None=Field(default=None,max_length=80)

    @model_validator(mode='after')
    def unique_keys(self):
        keys=[m.user_key for m in self.members]
        if len(keys)!=len(set(keys)):
            raise ValueError('名册内存在重复用户，请先合并同一用户的重复行')
        return self


class RunInput(BaseModel):
    experiment_id:int=Field(gt=0)


class RationaleInput(BaseModel):
    rationale:str=Field(min_length=10,max_length=3000)


class PublishInput(BaseModel):
    action:Literal['publish_b','keep_a']
