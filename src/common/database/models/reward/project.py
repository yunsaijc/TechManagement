"""
奖励评审 - 项目数据模型
"""
from pydantic import BaseModel
from datetime import date, datetime
from typing import Optional


class Project(BaseModel):
    """项目/奖励基本信息"""
    id: str
    XMBH: str                      # 项目编号
    XMMC: Optional[str] = None      # 项目名称
    XMTJH: Optional[str] = None    # 项目推荐号
    JZBH: Optional[str] = None      # 奖种编号
    XKDZBH: Optional[str] = None   # 学科大组编号
    XKDZMC: Optional[str] = None   # 学科大组名称
    TJDWBH: Optional[str] = None   # 推荐单位编号
    ND: Optional[str] = None       # 年度
    
    class Config:
        from_attributes = True


class ProjectPerson(BaseModel):
    """主要完成人"""
    id: str
    XMBH: str                      # 项目编号
    XH: float                      # 序号
    PM: float                      # 排名
    XM: Optional[str] = None       # 姓名
    GZDW: Optional[str] = None     # 工作单位
    WCDW: Optional[str] = None    # 完成单位
    SFZH: Optional[str] = None     # 身份证号
    
    class Config:
        from_attributes = True


class ProjectUnit(BaseModel):
    """完成单位"""
    id: str
    XMBH: str                      # 项目编号
    XH: float                      # 序号
    DWMC: Optional[str] = None     # 单位名称
    DWPM: Optional[float] = None   # 排名
    
    class Config:
        from_attributes = True


class ReviewResult(BaseModel):
    """形式审查结果"""
    id: str
    XMBH: str                      # 项目编号
    XMTJBH: Optional[str] = None   # 项目提名号
    SFHG: Optional[str] = None    # 形审是否合格
    BHGXXYY: Optional[str] = None  # 不合格详细原因
    JSSFHG: Optional[str] = None   # 机审是否合格
    
    class Config:
        from_attributes = True
