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
        # 本地文件根目录：默认使用仓库内可配置目录，避免硬编码到测试样例数据
        self.doc_root = Path(os.getenv("EVALUATION_PROJECT_DOC_ROOT", "data/evaluation_projects"))

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
                j.xmjj
            FROM Sb_Jbxx b
            LEFT JOIN Sb_Jj j ON j.onlysign = b.id
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
        }

    def get_project_file_paths(self, project_id: str) -> List[str]:
        """获取项目申报文档列表

        目录约定：
        `EVALUATION_PROJECT_DOC_ROOT/{project_id}/`

        Args:
            project_id: 项目ID

        Returns:
            文档绝对路径列表
        """
        project_dir = self.doc_root / project_id
        if not project_dir.is_dir():
            return []

        paths: List[Path] = []
        for pattern in ("*.docx", "*.pdf", "*.doc"):
            paths.extend(project_dir.glob(pattern))
            paths.extend(project_dir.glob(pattern.upper()))

        # 去重 + 排序（保证稳定）
        unique_paths = sorted({p.resolve() for p in paths})
        return [str(p) for p in unique_paths]

    def get_primary_document_path(self, project_id: str) -> Optional[str]:
        """获取主申报文档路径（优先 docx，再 pdf，再 doc）"""
        paths = self.get_project_file_paths(project_id)
        if not paths:
            return None

        def _priority(path: str) -> tuple[int, str]:
            lower = path.lower()
            if lower.endswith(".docx"):
                return (0, lower)
            if lower.endswith(".pdf"):
                return (1, lower)
            if lower.endswith(".doc"):
                return (2, lower)
            return (9, lower)

        return sorted(paths, key=_priority)[0]
