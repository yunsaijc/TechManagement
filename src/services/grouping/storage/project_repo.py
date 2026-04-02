"""
项目数据访问层

负责从项目评审数据库 (SQL Server) 读取项目数据。
分组功能默认只使用固定业务批次下、审核通过的项目子集。
"""
import os
from typing import List, Optional

from src.common.database.connection import project_execute
from src.common.models.grouping import Project


class ProjectRepository:
    """项目数据仓库
    
    对应数据库: kjjhxm_wlps (SQL Server)
    表: Sb_Jbxx, Sb_Jj, Sb_Sbzt
    """

    FIXED_TEST_GUIDE_CODE = os.getenv("GROUPING_TEST_GUIDE_CODE", "c2f3b7b1f9534463ad726e6936c91859")
    APPROVED_AUDIT_STATUS = os.getenv("GROUPING_TEST_AUDIT_STATUS", "1")
    SUBMIT_STATUS = os.getenv("GROUPING_SUBMIT_STATUS", "1")

    @classmethod
    def _base_from_clause(cls) -> str:
        return """
            FROM Sb_Jbxx b
            LEFT JOIN Sb_Jj j ON b.id = j.onlysign
            LEFT JOIN Sb_Sbzt s ON s.onlysign = b.id
            WHERE b.zndm = ?
              AND s.gkAudit = ?
        """

    @classmethod
    def _base_params(cls) -> List[str]:
        return [cls.FIXED_TEST_GUIDE_CODE, cls.APPROVED_AUDIT_STATUS]

    @classmethod
    def get_grouping_dataset_filter(cls) -> dict:
        return {
            "guide_code": cls.FIXED_TEST_GUIDE_CODE,
            "audit_status": cls.APPROVED_AUDIT_STATUS,
        }

    @classmethod
    def get_grouping_dataset_filter_by_guide_codes(cls, guide_codes: List[str]) -> dict:
        return {
            "guide_codes": guide_codes,
            "is_submit": cls.SUBMIT_STATUS,
        }
    
    @staticmethod
    def get_grouping_test_projects(
        category: Optional[str] = None,
    ) -> List[Project]:
        """获取固定分组测试数据集
        
        Args:
            category: 奖种类别 (可选)
        
        Returns:
            项目列表
        """
        params = ProjectRepository._base_params()
        sql = f"""
            SELECT
                b.id, b.xmmc, b.gjc, b.ssxk1, b.ssxk2,
                j.xmjj, j.lxbj, b.cddwMc, b.year
            {ProjectRepository._base_from_clause()}
        """
        if category:
            sql += " AND b.jhlb = ?"
            params.append(category)
        sql += " ORDER BY b.id"
        
        # 执行查询
        rows = project_execute(sql, tuple(params))
        
        # 转换为模型
        projects = []
        for row in rows:
            project = Project(
                id=row.id,
                xmmc=row.xmmc or "",
                gjc=row.gjc,
                ssxk1=row.ssxk1,
                ssxk2=row.ssxk2,
                xmjj=row.xmjj,
                lxbj=row.lxbj,
                cddw_mc=row.cddwMc,
                year=row.year,
            )
            projects.append(project)
        
        return projects

    @staticmethod
    def get_grouping_projects_by_guide_codes(
        guide_codes: List[str],
        category: Optional[str] = None,
    ) -> List[Project]:
        """按 zndm 代码列表获取已提交项目。"""
        cleaned_codes = [code.strip() for code in guide_codes if code and code.strip()]
        if not cleaned_codes:
            return []

        placeholders = ",".join(["?"] * len(cleaned_codes))
        params: List[str] = cleaned_codes + [ProjectRepository.SUBMIT_STATUS]
        sql = f"""
            SELECT
                b.id, b.xmmc, b.gjc, b.ssxk1, b.ssxk2,
                j.xmjj, j.lxbj, b.cddwMc, b.year
            FROM Sb_Jbxx b
            LEFT JOIN Sb_Jj j ON b.id = j.onlysign
            LEFT JOIN Sb_Sbzt s ON s.onlysign = b.id
            WHERE b.zndm IN ({placeholders})
              AND s.isSubmit = ?
        """
        if category:
            sql += " AND b.jhlb = ?"
            params.append(category)
        sql += " ORDER BY b.id"

        rows = project_execute(sql, tuple(params))
        projects: List[Project] = []
        for row in rows:
            projects.append(
                Project(
                    id=row.id,
                    xmmc=row.xmmc or "",
                    gjc=row.gjc,
                    ssxk1=row.ssxk1,
                    ssxk2=row.ssxk2,
                    xmjj=row.xmjj,
                    lxbj=row.lxbj,
                    cddw_mc=row.cddwMc,
                    year=row.year,
                )
            )
        return projects
    
    @staticmethod
    def get_project_by_id(project_id: str) -> Optional[Project]:
        """根据ID获取项目
        
        Args:
            project_id: 项目ID
        
        Returns:
            项目信息
        """
        sql = """
            SELECT 
                b.id, b.xmmc, b.gjc, b.ssxk1, b.ssxk2, 
                j.xmjj, j.lxbj, b.cddwMc, b.year
            FROM Sb_Jbxx b
            LEFT JOIN Sb_Jj j ON b.id = j.onlysign
            WHERE b.id = ?
        """
        
        rows = project_execute(sql, (project_id,))
        
        if not rows:
            return None
        
        row = rows[0]
        return Project(
            id=row.id,
            xmmc=row.xmmc or "",
            gjc=row.gjc,
            ssxk1=row.ssxk1,
            ssxk2=row.ssxk2,
            xmjj=row.xmjj,
            lxbj=row.lxbj,
            cddw_mc=row.cddwMc,
            year=row.year,
        )
    
    @staticmethod
    def count_grouping_test_projects(category: Optional[str] = None) -> int:
        """统计固定分组测试数据集数量
        
        Args:
            category: 奖种类别
        
        Returns:
            项目数量
        """
        sql = f"""
            SELECT COUNT(*) as cnt
            {ProjectRepository._base_from_clause()}
        """
        params = ProjectRepository._base_params()
        
        if category:
            sql += " AND b.jhlb = ?"
            params.append(category)
        
        rows = project_execute(sql, tuple(params))
        return rows[0].cnt if rows else 0
