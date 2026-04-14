"""项目向量化示例。"""
import html
import json
import re
from typing import Any, Dict, List

import numpy as np

from src.common.llm import get_default_embedding_client


DEMO_PROJECT = {
    "project_id": "b6cbd95d18d44eab90588d1c363513a6",
    "xmmc": "基于机器学习与深度学习的遥感BOA反射率模拟研究",
    "xmjj": "<p style=\"font-size: 16px;\"><span>大气底部（BOA）光谱反射率是遥感领域中一个十分重要的基础参量，其直接决定了诸如卫星载荷辐射定标、定量遥感产品反演等结果的准确性。</span><span>针对目前 BOA 反射率模拟研究中存在模型过于简化、精度低、方法适用性差等科学问题，拟开展顾及几何、大气和BRDF的模型构建研究。</span></p>",
    "ssxk1": None,
    "ssxk2": None,
    "subject_code": "D0106",
    "subject_name": "遥感机理与方法",
    "semantic_score": 1.0,
    "reason": "按学科与项目主题聚合形成的分组，代表项目包括：融合光学遥感与声学探测的海草床分带识别及、机器学习理论下的空间碎片光学观测任务计划",
    "original_subject_code": "D0106",
    "original_subject_name": "遥感机理与方法",
    "original_subject_code_2": "",
    "original_subject_name_2": "未知主题",
    "keywords": ["深度学习", "遥感科学", "BOA地表反射率"],
    "risk_flags": [],
}


class ProjectEmbedder:
    """面向项目字典数据的向量化器。"""

    def __init__(self, embedder: Any = None):
        self.embedder = embedder or get_default_embedding_client()

    def _get(self, project: Dict[str, Any], key: str, default: Any = "") -> Any:
        value = project.get(key, default)
        return default if value is None else value

    def _clean_html_text(self, text: str) -> str:
        if not text:
            return ""
        clean = re.sub(r"<[^>]+>", " ", text)
        clean = html.unescape(clean)
        clean = re.sub(r"\s+", " ", clean)
        return clean.strip()

    def _normalize_keywords(self, value: Any) -> List[str]:
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        if isinstance(value, str) and value.strip():
            return [item.strip() for item in re.split(r"[、，,；;\n]+", value) if item.strip()]
        return []

    def _project_text(self, project: Dict[str, Any]) -> str:
        parts: List[str] = []

        # 1) 学科信息
        subject_name = self._get(project, "subject_name", "") or self._get(project, "original_subject_name", "")
        subject_code = self._get(project, "subject_code", "") or self._get(project, "original_subject_code", "")
        if subject_name:
            parts.extend([str(subject_name)] * 2)
        if subject_code:
            parts.append(str(subject_code))

        # 2) 关键词（支持 list 或字符串）
        keywords = self._normalize_keywords(project.get("keywords"))
        if not keywords:
            keywords = self._normalize_keywords(project.get("gjc"))
        for kw in keywords:
            if len(kw) >= 2:
                parts.extend([kw] * 3)

        # 3) 项目名称
        title = str(self._get(project, "xmmc", "")).strip()
        if title:
            parts.append(title)

        # 4) 项目简介（支持 HTML）
        summary = self._clean_html_text(str(self._get(project, "xmjj", "")).strip())
        if summary:
            parts.append(summary[:500])

        # 5) 分组原因（可选）
        reason = self._clean_html_text(str(self._get(project, "reason", "")).strip())
        if reason:
            parts.append(reason[:200])

        return "。".join([p for p in parts if p])

    def _generate_project_vectors(self, projects: List[Dict[str, Any]]) -> np.ndarray:
        """生成项目向量。

        Args:
            projects: 项目列表（支持你给的 grouping_result 项目结构）

        Returns:
            np.ndarray: 形状 (n_projects, embedding_dim)
        """
        if not projects:
            return np.empty((0, 0), dtype=float)

        texts = [self._project_text(project) for project in projects]
        embeddings = self.embedder.embed_documents(texts)
        return np.asarray(embeddings, dtype=float)


if __name__ == "__main__":
    embedder = ProjectEmbedder()
    vectors = embedder._generate_project_vectors([DEMO_PROJECT])

    print("=== project_text ===")
    print(embedder._project_text(DEMO_PROJECT))
    print("\n=== vector shape ===")
    print(vectors.shape)
    # print("\n=== first 10 dims ===")
    # print(json.dumps(vectors[0][:10].tolist(), ensure_ascii=False))
