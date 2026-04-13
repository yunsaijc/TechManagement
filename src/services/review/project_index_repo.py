"""项目索引数据访问层"""
import os
from typing import List, Optional

from src.common.database.connection import project_execute
from src.common.models import ProjectIndexRow


class ProjectIndexRepository:
    """按 zxmc 查询项目索引列表"""

    SUBMIT_STATUS = os.getenv("REVIEW_PROJECT_SUBMIT_STATUS", "1")

    @classmethod
    def get_projects_by_zxmc(
        cls,
        zxmc: str,
        limit: Optional[int] = None,
        project_ids: Optional[List[str]] = None,
    ) -> List[ProjectIndexRow]:
        """根据批次标识获取项目索引记录"""
        params: List[object] = [zxmc, cls.SUBMIT_STATUS]
        sql = """
            SELECT
                b.id,
                b.year,
                b.xmmc,
                zn.name AS guide_name,
                b.cddwMc,
                b.dwmc,
                b.xmFzr,
                b.starttime,
                b.endtime
            FROM Sb_Jbxx b
            LEFT JOIN sys_guide zn ON zn.id = b.zndm
            LEFT JOIN Sb_Sbzt s ON s.onlysign = b.id
            WHERE b.zxmc = ?
              AND s.isSubmit = ?
        """
        if project_ids:
            placeholders = ", ".join("?" for _ in project_ids)
            sql += f" AND b.id IN ({placeholders})"
            params.extend(project_ids)
        sql += " ORDER BY b.id"
        rows = project_execute(sql, tuple(params))
        results: List[ProjectIndexRow] = []
        for row in rows:
            results.append(
                ProjectIndexRow(
                    project_id=row.id,
                    year=str(row.year or ""),
                    project_name=row.xmmc or "",
                    guide_name=row.guide_name or "",
                    applicant_unit=row.cddwMc or "",
                    unit_name=row.dwmc or "",
                    project_leader=row.xmFzr or "",
                    start_date=str(row.starttime or ""),
                    end_date=str(row.endtime or ""),
                )
            )
        if limit is not None:
            return results[:limit]
        return results
