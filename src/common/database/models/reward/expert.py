"""
奖励评审 - 专家数据模型
"""
from pydantic import BaseModel
from datetime import datetime
from typing import Optional


class Expert(BaseModel):
    """专家基本信息"""
    id: str
    ZJNO: str                      # 专家号
    XM: str                        # 姓名
    XB: Optional[str] = None       # 性别
    CSRQ: Optional[datetime] = None  # 出生日期
    YDDH: str                     # 移动电话
    DZYX: Optional[str] = None    # 电子邮箱
    GZDWID: Optional[str] = None   # 工作单位ID
    SXXK1: Optional[str] = None    # 熟悉学科1
    SXXK2: Optional[str] = None    # 熟悉学科2
    SXXK3: Optional[str] = None    # 熟悉学科3
    ZC: Optional[str] = None       # 职称
    RKZT: Optional[str] = None      # 入库状态
    RKSJ: Optional[datetime] = None  # 入库时间
    
    class Config:
        from_attributes = True


class WorkUnit(BaseModel):
    """工作单位"""
    id: str
    GZDWID: str                    # 工作单位ID
    GZDWMC: Optional[str] = None   # 工作单位名称
    ZZJGDM: Optional[str] = None   # 统一社会信用代码
    
    class Config:
        from_attributes = True


class RecommendUnit(BaseModel):
    """推荐单位"""
    id: str
    TJDWID: str                    # 推荐单位ID
    TJDWMC: str                   # 推荐单位名称
    LXR: Optional[str] = None      # 联系人
    LXDH: Optional[str] = None     # 联系电话
    
    class Config:
        from_attributes = True


class Subject(BaseModel):
    """学科代码"""
    id: str
    parent_id: Optional[str] = None
    code: Optional[str] = None
    name: Optional[str] = None
    sort: Optional[float] = None
    
    class Config:
        from_attributes = True
