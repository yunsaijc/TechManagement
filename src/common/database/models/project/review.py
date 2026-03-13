"""
项目评审 - 评审数据模型 (SQL Server)
"""
from pydantic import BaseModel
from datetime import date, datetime
from typing import Optional


class ProjectReview(BaseModel):
    """项目评审信息"""
    XMBH: str                      # 项目编号
    ND: Optional[str] = None        # 年度
    CSJG: Optional[str] = None      # 初审结果
    CSYJ: Optional[str] = None      # 形审意见
    SFJRWP: Optional[str] = None   # 是否进入网评
    WPZBH: Optional[str] = None    # 网评组编号
    WPFS: Optional[float] = None   # 网评分数
    Wpfspm: Optional[str] = None   # 网评组排名
    wpsftg: Optional[str] = None   # 网评是否通过
    SFJRFS: Optional[str] = None   # 是否进入复审
    FSFS: Optional[float] = None   # 复审分数
    SFJRZP: Optional[int] = None   # 是否进入总评
    L1_ZPPS1: Optional[int] = None  # 总评一轮同意票数
    L2_ZPPS1: Optional[int] = None  # 总评二轮同意票数
    ZPZZJG: Optional[int] = None   # 总评最终结果
    SFLX: Optional[int] = None     # 是否立项
    LXBH: Optional[str] = None     # 立项项目编号
    LXJF: Optional[float] = None    # 立项经费
    
    class Config:
        from_attributes = True


class ExpertLogin(BaseModel):
    """网评专家登录"""
    PSZBH: Optional[str] = None    # 评审组编号
    ZJBH: Optional[str] = None     # 专家编号
    ZJXM: Optional[str] = None     # 专家姓名
    PWSX: Optional[int] = None     # 评委顺序
    PSZXMS: Optional[int] = None   # 评审组项目数
    WCXMS: Optional[int] = None   # 完成项目数
    PSKSSJ: Optional[datetime] = None  # 评审开始时间
    PSJZSJ: Optional[datetime] = None   # 评审截止时间
    
    class Config:
        from_attributes = True


class ExpertScore(BaseModel):
    """综合评审打分"""
    ZPZBH: Optional[str] = None    # 总评组编号
    ZJBH: Optional[str] = None     # 专家编号
    XMBH: Optional[str] = None    # 项目编号
    ZJTP: Optional[str] = None    # 专家投票
    TJSJ: Optional[datetime] = None  # 提交时间
    
    class Config:
        from_attributes = True
