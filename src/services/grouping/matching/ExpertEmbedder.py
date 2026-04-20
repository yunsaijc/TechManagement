"""图谱专家画像与向量化示例。"""
import asyncio
import json
import re
from typing import Any, Dict, List

import numpy as np

from src.common.llm import get_default_embedding_client, get_default_llm_client
from src.common.models.grouping import ExpertProfile


DEMO_EXPERT = {
    "elementId": "4:a16385bc-640b-45bd-a228-8a0a8e04df0e:212311",
    "labels": ["Person"],
    "properties": {
        "name": "刘修国",
        "是否专家": "是",
        "id": "1351200",
        "从事专业": "遥感信息获取与地理信息工程",
        "organization": "中国地质大学（武汉）",
        "研究领域": "遥感信息智能获取及其地学应用、地理空间数字孪生技术、三维地质建模及其可视化分析、地理空间知识管理与推理、地理信息工程",
    },
}


class GraphExpertProfiler:
    """面向知识图谱专家节点的画像构建器。"""

    def __init__(self, llm: Any = None, embedder: Any = None):
        self.llm = llm or get_default_llm_client()
        self.embedder = embedder or get_default_embedding_client()
        self._profile_cache: Dict[str, ExpertProfile] = {}
        self._vector_cache: Dict[str, np.ndarray] = {}

    def build_expert_text(self, expert: Dict[str, Any]) -> str:
        """构建专家融合文本，尽量贴近原始 ExpertProfiler 的设计。"""
        props = self._extract_properties(expert)
        parts: List[str] = []

        if props.get("name"):
            parts.append(f"姓名: {props['name']}")
        if props.get("id"):
            parts.append(f"专家ID: {props['id']}")
        if props.get("从事专业"):
            parts.append(f"从事专业: {props['从事专业']}")
        if props.get("研究领域"):
            research_area = props["研究领域"]
            if len(research_area) > 2000:
                research_area = research_area[:2000] + "..."
            parts.append(f"研究领域: {research_area}")
        if props.get("organization"):
            parts.append(f"工作单位: {props['organization']}")

        return "\n\n".join(parts)

    async def profile_expert(self, expert: Dict[str, Any]) -> ExpertProfile:
        """分析单个图谱专家，得到结构化画像。"""
        props = self._extract_properties(expert)
        text = self.build_expert_text(expert)
        prompt = self._build_profile_prompt(props)

        try:
            response = await self.llm.ainvoke(prompt)
            content = response.content if hasattr(response, "content") else str(response)

            # print("LLM content=", content)  # 打印LLM输出

            profile = self._parse_profile_result(props.get("id", ""), content, props)
        except Exception:
            profile = self._fallback_profile_result(props.get("id", ""), props)

        profile.text = text
        return profile

    def _expert_cache_key(self, expert: Dict[str, Any], index: int = 0) -> str:
        props = self._extract_properties(expert)
        expert_id = props.get("id") or expert.get("id")
        if expert_id:
            return str(expert_id)
        name = props.get("name") or expert.get("name")
        if name:
            return f"name:{name}"
        return f"expert_{index}"

    async def profile_experts(
        self,
        experts: List[Dict[str, Any]],
        max_concurrency: int = 4,
    ) -> List[ExpertProfile]:
        """批量分析图谱专家。"""
        if not experts:
            return []

        semaphore = asyncio.Semaphore(max(1, int(max_concurrency)))
        results: List[ExpertProfile | None] = [None] * len(experts)

        async def process_one(index: int, expert: Dict[str, Any]) -> None:
            cache_key = self._expert_cache_key(expert, index)
            cached = self._profile_cache.get(cache_key)
            if cached is not None:
                results[index] = cached
                return

            async with semaphore:
                profile = await self.profile_expert(expert)

            self._profile_cache[cache_key] = profile
            results[index] = profile

        await asyncio.gather(*(process_one(index, expert) for index, expert in enumerate(experts)))
        return [profile for profile in results if profile is not None]

    def build_embedding_text(self, profile: ExpertProfile) -> str:
        """将结构化画像拼成最终 embedding 文本。"""
        text_parts: List[str] = []
        if profile.main_research_area:
            text_parts.append(profile.main_research_area)
        if profile.sub_research_fields:
            text_parts.extend(profile.sub_research_fields)
        if profile.tech_expertise:
            text_parts.extend(profile.tech_expertise)
        if profile.keywords:
            text_parts.extend(profile.keywords)
        return " ".join(text_parts) if text_parts else (profile.text or "")

    def generate_vectors(self, expert_profiles: List[ExpertProfile]) -> np.ndarray:
        """批量生成专家向量，逻辑保持与 matching.agent 接近。"""
        if not expert_profiles:
            return np.empty((0, 0), dtype=float)

        texts: List[str] = []
        pending_indices: List[int] = []
        vectors: List[np.ndarray | None] = [None] * len(expert_profiles)

        for index, profile in enumerate(expert_profiles):
            cache_key = str(profile.expert_id or f"profile_{index}")
            cached = self._vector_cache.get(cache_key)
            if cached is not None:
                vectors[index] = cached
                continue

            text = self.build_embedding_text(profile)
            texts.append(text)
            pending_indices.append(index)

        if texts:
            embeddings = self.embedder.embed_documents(texts)
            for index, embedding in zip(pending_indices, embeddings):
                vector = np.asarray(embedding, dtype=float)
                cache_key = str(expert_profiles[index].expert_id or f"profile_{index}")
                self._vector_cache[cache_key] = vector
                vectors[index] = vector

        return np.vstack([vector for vector in vectors if vector is not None])

    def _build_profile_prompt(self, props: Dict[str, Any]) -> str:
        return f"""请分析以下专家信息，构建专家画像。
            姓名：{props.get('name') or '无'}
            专家ID：{props.get('id') or '无'}
            从事专业：{props.get('从事专业') or '无'}
            研究领域：{(props.get('研究领域') or '无')[:1000]}
            工作单位：{props.get('organization') or '无'}

            请提取以下信息（JSON格式）：
            {{
                "main_research_area": "主要研究方向（如：遥感、地理信息工程）",
                "sub_research_fields": ["细分领域1", "细分领域2"],
                "tech_expertise": ["技术专长1", "技术专长2"],
                "keywords": ["关键词1", "关键词2", "关键词3"]
            }}

            请只输出 JSON，不要其他内容。
            注意只能基于输入原文抽取，不要补充未出现的新术语"""

    def _parse_profile_result(
        self,
        expert_id: str,
        content: str,
        props: Dict[str, Any],
    ) -> ExpertProfile:
        """解析 LLM 输出；失败时回退到规则提取。"""
        try:
            json_match = re.search(r"\{[\s\S]*\}", content)
            if json_match:
                data = json.loads(json_match.group())
                profile = ExpertProfile(
                    expert_id=expert_id,
                    main_research_area=data.get("main_research_area"),
                    sub_research_fields=self._normalize_list(data.get("sub_research_fields")),
                    tech_expertise=self._normalize_list(data.get("tech_expertise")),
                    keywords=self._normalize_list(data.get("keywords")),
                )
                if (
                    profile.main_research_area
                    or profile.sub_research_fields
                    or profile.tech_expertise
                    or profile.keywords
                ):
                    return profile
        except Exception:
            pass

        return self._fallback_profile_result(expert_id, props)

    def _fallback_profile_result(self, expert_id: str, props: Dict[str, Any]) -> ExpertProfile:
        """LLM 不可用时，从图谱字段直接构造可用画像。"""
        profession = (props.get("从事专业") or "").strip()
        research_area = (props.get("研究领域") or "").strip()

        tech_expertise = self._split_phrases(profession)
        sub_research_fields = self._split_phrases(research_area)
        main_research_area = tech_expertise[0] if tech_expertise else (sub_research_fields[0] if sub_research_fields else profession or research_area)
        keywords = self._build_keywords(profession, research_area)

        return ExpertProfile(
            expert_id=expert_id,
            main_research_area=main_research_area or None,
            sub_research_fields=sub_research_fields,
            tech_expertise=tech_expertise,
            keywords=keywords,
        )

    def _extract_properties(self, expert: Dict[str, Any]) -> Dict[str, Any]:
        if isinstance(expert.get("properties"), dict):
            return expert["properties"]
        return expert

    def _split_phrases(self, text: str, limit: int = 8) -> List[str]:
        if not text:
            return []
        parts = [part.strip() for part in re.split(r"[、，,；;。\n]+", text) if part.strip()]
        return list(dict.fromkeys(parts))[:limit]

    def _build_keywords(self, profession: str, research_area: str, limit: int = 12) -> List[str]:
        keywords: List[str] = []
        for text in [profession, research_area]:
            for phrase in self._split_phrases(text, limit=limit):
                keywords.append(phrase)
                for token in re.split(r"[与及其和]", phrase):
                    token = token.strip()
                    if len(token) >= 2:
                        keywords.append(token)
        return list(dict.fromkeys([item for item in keywords if item]))[:limit]

    def _normalize_list(self, value: Any) -> List[str]:
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        if isinstance(value, str) and value.strip():
            return [item.strip() for item in re.split(r"[、，,；;\n]+", value) if item.strip()]
        return []


if __name__ == "__main__":
    profiler = GraphExpertProfiler()
    demo_profile = profiler._fallback_profile_result(
        DEMO_EXPERT["properties"]["id"],
        DEMO_EXPERT["properties"],
    )

    # 1.拼接初始化可读AI文本
    print(profiler.build_expert_text(DEMO_EXPERT))

    # 2.调用LLM生成画像
    profiles = asyncio.run(profiler.profile_experts([DEMO_EXPERT]))
    # print("profiles=", profiles[0])
    
    # 3.生成专家向量
    experts_embeddings = profiler.generate_vectors(profiles)
    print("experts_embeddings=", experts_embeddings[0])
