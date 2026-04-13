"""
正文评审项目数据访问层

负责根据 project_id 获取项目基础信息和申报书文件路径。
"""
import os
from pathlib import Path
from typing import Dict, List, Optional

from src.common.database.connection import project_execute


class EvaluationProjectRepository:
    """正文评审项目仓库"""

    def __init__(self):
        self.corpus_root = Path(os.getenv("EVALUATION_CORPUS_ROOT", "/mnt/remote_corpus"))
        self.submit_status = os.getenv("EVALUATION_SUBMIT_STATUS", "1")

    def get_project_info(self, project_id: str) -> Optional[Dict[str, str]]:
        """获取项目基础信息

        Args:
            project_id: 项目ID

        Returns:
            项目信息字典，不存在时返回 None
        """
        sql = """
            SELECT
                b.id,
                b.xmmc,
                b.xmFzr,
                b.cddwMc,
                b.gjc,
                b.year,
                b.zndm,
                zn.name AS guide_name,
                j.xmjj
            FROM Sb_Jbxx b
            LEFT JOIN Sb_Jj j ON j.onlysign = b.id
            LEFT JOIN sys_guide zn ON zn.id = b.zndm
            WHERE b.id = ?
        """
        rows = project_execute(sql, (project_id,))
        if not rows:
            return None

        row = rows[0]
        return {
            "id": row.id,
            "xmmc": row.xmmc or "",
            "xmFzr": row.xmFzr or "",
            "cddw_mc": row.cddwMc or "",
            "gjc": row.gjc or "",
            "year": str(row.year or ""),
            "xmjj": row.xmjj or "",
            "zndm": row.zndm or "",
            "guide_name": row.guide_name or "",
        }

    def get_projects_by_guide_code(self, zndm: str, limit: Optional[int] = None) -> List[Dict[str, str]]:
        """按指南代码获取已提交项目列表"""
        sql = """
            SELECT
                b.id,
                b.xmmc,
                b.year,
                b.zndm,
                zn.name AS guide_name
            FROM Sb_Jbxx b
            LEFT JOIN sys_guide zn ON zn.id = b.zndm
            LEFT JOIN Sb_Sbzt s ON s.onlysign = b.id
            WHERE b.zndm = ?
              AND s.isSubmit = ?
            ORDER BY b.id
        """
        rows = project_execute(sql, (zndm, self.submit_status))
        projects: List[Dict[str, str]] = []
        sliced_rows = rows[:limit] if limit else rows
        for row in sliced_rows:
            projects.append(
                {
                    "id": row.id,
                    "xmmc": row.xmmc or "",
                    "year": str(row.year or ""),
                    "zndm": row.zndm or "",
                    "guide_name": row.guide_name or "",
                }
            )
        return projects

    def get_project_file_paths(self, project_id: str) -> List[str]:
        """获取项目申报文档列表

        Args:
            project_id: 项目ID

        Returns:
            文档绝对路径列表
        """
        project_info = self.get_project_info(project_id)
        if not project_info:
            return []
        year = str(project_info.get("year") or "").strip()
        if not year:
            return []

        doc_path = self.corpus_root / year / "sbs" / project_id / f"{project_id}.docx"
        return [str(doc_path)] if doc_path.exists() else []

    def get_expected_document_path(self, project_id: str) -> Optional[str]:
        """获取按真实规则推断的正文路径"""
        project_info = self.get_project_info(project_id)
        if not project_info:
            return None
        year = str(project_info.get("year") or "").strip()
        if not year:
            return None
        return str(self.corpus_root / year / "sbs" / project_id / f"{project_id}.docx")

    def get_primary_document_path(self, project_id: str) -> Optional[str]:
        """获取主申报文档路径"""
        paths = self.get_project_file_paths(project_id)
        return paths[0] if paths else None
