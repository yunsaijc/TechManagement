"""
专家数据访问层

负责从项目评审数据库 (SQL Server) 读取专家数据
"""
from typing import List, Optional

from src.common.database.connection import project_execute
from src.common.models.grouping import Expert


class ExpertRepository:
    """专家数据仓库
    
    对应数据库: kjjhxm_wlps (SQL Server)
    表: ZJK_ZJXX
    """
    
    @staticmethod
    def get_experts(
        subject_codes: Optional[List[str]] = None,
        limit: Optional[int] = None
    ) -> List[Expert]:
        """获取专家列表
        
        Args:
            subject_codes: 学科代码列表 (用于筛选熟悉学科)
            limit: 限制返回数量
        
        Returns:
            专家列表
        """
        sql = """
            SELECT 
                ZJNO,
                XM,
                SXXK1,
                SXXK2,
                SXXK3,
                SXXK4,
                SXXK5,
                SXZY,
                YJLY,
                LWLZ,
                GZDWID
            FROM ZJK_ZJXX
            WHERE 1=1
        """
        params = []
        
        # 如果指定了学科代码，筛选熟悉这些学科的专家
        if subject_codes:
            placeholders = ",".join(["?"] * len(subject_codes))
            sql += f""" AND (
                SXXK1 IN ({placeholders})
                OR SXXK2 IN ({placeholders})
                OR SXXK3 IN ({placeholders})
                OR SXXK4 IN ({placeholders})
                OR SXXK5 IN ({placeholders})
            )"""
            params.extend(subject_codes)
        
        # SQL Server: TOP 需要在 ORDER BY 之前
        if limit:
            sql = f"SELECT TOP {limit} * FROM ({sql}) AS t"
            rows = project_execute(sql, tuple(params))
        else:
            sql += " ORDER BY ZJNO"
            rows = project_execute(sql, tuple(params))
        
        # 转换为模型
        experts = []
        for row in rows:
            expert = Expert(
                id=row.ZJNO,
                xm=row.XM or "",
                sxxk1=row.SXXK1,
                sxxk2=row.SXXK2,
                sxxk3=row.SXXK3,
                sxxk4=row.SXXK4,
                sxxk5=row.SXXK5,
                sxzy=row.SXZY,
                yjly=row.YJLY,
                lwlz=row.LWLZ,
                gzdw=row.GZDWID,  # 工作单位ID
            )
            experts.append(expert)
        
        return experts
    
    @staticmethod
    def get_expert_by_id(expert_id: str) -> Optional[Expert]:
        """根据ID获取专家
        
        Args:
            expert_id: 专家ID (ZJNO)
        
        Returns:
            专家信息
        """
        sql = """
            SELECT 
                ZJNO,
                XM,
                SXXK1,
                SXXK2,
                SXXK3,
                SXXK4,
                SXXK5,
                SXZY,
                YJLY,
                LWLZ,
                GZDW
            FROM ZJK_ZJXX
            WHERE ZJNO = ?
        """
        
        rows = project_execute(sql, (expert_id,))
        
        if not rows:
            return None
        
        row = rows[0]
        return Expert(
            id=row.ZJNO,
            xm=row.XM or "",
            sxxk1=row.SXXK1,
            sxxk2=row.SXXK2,
            sxxk3=row.SXXK3,
            sxxk4=row.SXXK4,
            sxxk5=row.SXXK5,
            sxzy=row.SXZY,
            yjly=row.YJLY,
            lwlz=row.LWLZ,
            gzdw=row.GZDW,
        )
    
    @staticmethod
    def count_experts(subject_codes: Optional[List[str]] = None) -> int:
        """统计专家数量
        
        Args:
            subject_codes: 学科代码列表
        
        Returns:
            专家数量
        """
        sql = "SELECT COUNT(*) as cnt FROM ZJK_ZJXX WHERE 1=1"
        params = []
        
        if subject_codes:
            placeholders = ",".join(["?"] * len(subject_codes))
            sql += f""" AND (
                SXXK1 IN ({placeholders})
                OR SXXK2 IN ({placeholders})
                OR SXXK3 IN ({placeholders})
                OR SXXK4 IN ({placeholders})
                OR SXXK5 IN ({placeholders})
            )"""
            params.extend(subject_codes)
        
        rows = project_execute(sql, tuple(params))
        return rows[0].cnt if rows else 0
    
    @staticmethod
    def get_experts_by_subject(subject_code: str, limit: int = 100) -> List[Expert]:
        """根据学科代码获取专家
        
        Args:
            subject_code: 学科代码
            limit: 限制返回数量
        
        Returns:
            熟悉该学科的专家列表
        """
        return ExpertRepository.get_experts(
            subject_codes=[subject_code],
            limit=limit
        )
