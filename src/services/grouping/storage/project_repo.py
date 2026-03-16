"""
项目数据访问层

负责从项目评审数据库 (SQL Server) 读取项目数据
"""
from typing import List, Optional

from src.common.database.connection import project_execute
from src.common.models.grouping import Project


class ProjectRepository:
    """项目数据仓库
    
    对应数据库: kjjhxm_wlps (SQL Server)
    表: Sb_Jbxx, Sb_Jj
    """
    
    @staticmethod
    def get_projects_by_year(
        year: str,
        category: Optional[str] = None,
        limit: Optional[int] = None
    ) -> List[Project]:
        """根据年度获取项目列表
        
        Args:
            year: 年度
            category: 奖种类别 (可选)
            limit: 限制返回数量
        
        Returns:
            项目列表
        """
        params = [year]
        
        # 构建查询SQL
        if limit:
            # SQL Server: TOP 在最外层
            sql = f"""
                SELECT TOP {limit}
                    b.id, b.xmmc, b.gjc, b.ssxk1, b.ssxk2, 
                    j.xmjj, j.lxbj, b.cddwMc, b.year
                FROM Sb_Jbxx b
                LEFT JOIN Sb_Jj j ON b.id = j.onlysign
                WHERE b.year = ?
            """
            if category:
                sql += " AND b.jhlb = ?"
                params.append(category)
            sql += " ORDER BY b.id"
        else:
            sql = """
                SELECT 
                    b.id, b.xmmc, b.gjc, b.ssxk1, b.ssxk2, 
                    j.xmjj, j.lxbj, b.cddwMc, b.year
                FROM Sb_Jbxx b
                LEFT JOIN Sb_Jj j ON b.id = j.onlysign
                WHERE b.year = ?
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
    def count_projects_by_year(year: str, category: Optional[str] = None) -> int:
        """统计年度项目数量
        
        Args:
            year: 年度
            category: 奖种类别
        
        Returns:
            项目数量
        """
        sql = "SELECT COUNT(*) as cnt FROM Sb_Jbxx WHERE year = ?"
        params = [year]
        
        if category:
            sql += " AND jhlb = ?"
            params.append(category)
        
        rows = project_execute(sql, tuple(params))
        return rows[0].cnt if rows else 0
