"""使用 ProjectEmbedder + ExpertEmbedder 进行项目-专家 Top-K 匹配。"""
import asyncio
import json
import random
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np
import time

from src.services.grouping.ExpertEmbedder import GraphExpertProfiler
from src.services.grouping.ProjectEmbedder import ProjectEmbedder
from src.services.grouping.SearchExpert import search_experts


class MatchAgent:
    """基于同一 embedding 模型的项目-专家匹配器。"""

    def __init__(
        self,
        project_embedder: ProjectEmbedder | None = None,
        expert_profiler: GraphExpertProfiler | None = None,
    ):
        self.project_embedder = project_embedder or ProjectEmbedder()
        self.expert_profiler = expert_profiler or GraphExpertProfiler()

    def _extract_expert_props(self, expert: Dict[str, Any]) -> Dict[str, Any]:
        if isinstance(expert.get("properties"), dict):
            return expert["properties"]
        return expert

    def _project_id(self, project: Dict[str, Any], index: int) -> str:
        pid = project.get("project_id") or project.get("id")
        return str(pid) if pid else f"project_{index}"

    def _expert_id(self, expert: Dict[str, Any], index: int) -> str:
        props = self._extract_expert_props(expert)
        eid = props.get("id") or expert.get("id")
        return str(eid) if eid else f"expert_{index}"

    def _expert_name(self, expert: Dict[str, Any], index: int) -> str:
        props = self._extract_expert_props(expert)
        name = props.get("name") or expert.get("name")
        return str(name) if name else f"专家{index + 1}"

    def _cosine_similarity_matrix(
        self,
        project_vectors: np.ndarray,
        expert_vectors: np.ndarray,
    ) -> np.ndarray:
        if project_vectors.ndim != 2 or expert_vectors.ndim != 2:
            raise ValueError("project_vectors 和 expert_vectors 必须是二维矩阵")
        if project_vectors.shape[1] != expert_vectors.shape[1]:
            raise ValueError(
                f"向量维度不一致: project_dim={project_vectors.shape[1]}, expert_dim={expert_vectors.shape[1]}"
            )

        project_norm = project_vectors / (np.linalg.norm(project_vectors, axis=1, keepdims=True) + 1e-8)
        expert_norm = expert_vectors / (np.linalg.norm(expert_vectors, axis=1, keepdims=True) + 1e-8)
        return project_norm @ expert_norm.T

    async def match_top_k(
        self,
        projects: List[Dict[str, Any]],
        experts: List[Dict[str, Any]],
        top_k: int = 5,
    ) -> List[Dict[str, Any]]:
        """为每个项目返回最相似的 Top-K 专家。"""
        if (not projects) or (not experts):
            return []

        proj_embed_t1 = time.time()
        project_vectors = self.project_embedder._generate_project_vectors(projects)
        proj_embed_t2 = time.time()
        proj_embed_time = proj_embed_t2 - proj_embed_t1
        print(f"proj_embed_time = {proj_embed_time:.2f} seconds")

        llm_t1 = time.time()
        expert_profiles = await self.expert_profiler.profile_experts(experts)
        llm_t2 = time.time()
        llm_time = llm_t2 - llm_t1
        print(f"llm_time = {llm_time:.2f} seconds")

        exp_embed_t1 = time.time()
        expert_vectors = self.expert_profiler.generate_vectors(expert_profiles)
        exp_embed_t2 = time.time()
        exp_embed_time = exp_embed_t2 - exp_embed_t1
        print(f"exp_embed_time = {exp_embed_time:.2f} seconds")

        sim = self._cosine_similarity_matrix(project_vectors, expert_vectors)

        k = max(1, min(int(top_k), sim.shape[1]))
        results: List[Dict[str, Any]] = []

        for i, project in enumerate(projects):
            row = sim[i]
            top_indices = np.argsort(row)[::-1][:k]

            top_experts = []
            for j in top_indices:
                cosine = float(row[j])
                top_experts.append(
                    {
                        "expert_id": self._expert_id(experts[j], j),
                        "expert_name": self._expert_name(experts[j], j),
                        "cosine_similarity": round(cosine, 4),
                        "match_score": round(cosine * 100, 2),
                    }
                )

            results.append(
                {
                    "project_id": self._project_id(project, i),
                    "top_experts": top_experts,
                }
            )

        return results

    async def match_projects_individual_search(
        self,
        projects: List[Dict[str, Any]],
        top_k: int = 5,
        expert_limit: int = 25,
        search_timeout: int = 30,
        max_concurrency: int = 3,
        max_llm_concurrency: int = 2,
    ) -> List[Dict[str, Any]]:
        """每个项目独立检索专家，并发执行匹配。"""
        if not projects:
            return []

        search_semaphore = asyncio.Semaphore(max(1, int(max_concurrency)))
        llm_semaphore = asyncio.Semaphore(max(1, int(max_llm_concurrency)))

        async def process_one(i: int, project: Dict[str, Any]) -> Dict[str, Any]:
            query_text = build_query_text_from_project(project)
            fallback_query = (project.get("subject_name") or "遥感").strip() or "遥感"

            async with search_semaphore:
                search_t1 = time.time()
                try:
                    experts = await asyncio.to_thread(
                        search_experts,
                        query_text=query_text,
                        limit=expert_limit,
                        timeout=search_timeout,
                    )
                except Exception:
                    experts = await asyncio.to_thread(
                        search_experts,
                        query_text=fallback_query,
                        limit=expert_limit,
                        timeout=search_timeout,
                    )

                search_time = time.time() - search_t1
                print(f"project_id={self._project_id(project, i)} search_experts_time={search_time:.2f}s")

            if not experts:
                return {
                    "project_id": self._project_id(project, i),
                    "query_text": query_text,
                    "expert_count": 0,
                    "top_experts": [],
                }

            async with llm_semaphore:
                match_t1 = time.time()
                matched = await self.match_top_k(projects=[project], experts=experts, top_k=top_k)
                match_time = time.time() - match_t1
                print(f"project_id={self._project_id(project, i)} match_time={match_time:.2f}s")

            row = matched[0] if matched else {"project_id": self._project_id(project, i), "top_experts": []}
            row["query_text"] = query_text
            row["expert_count"] = len(experts)
            return row

        tasks = [asyncio.create_task(process_one(i, project)) for i, project in enumerate(projects)]
        results = await asyncio.gather(*tasks)
        return results


def load_random_group_projects(file_path: Path) -> Tuple[int, List[Dict[str, Any]]]:
    """从 grouping_result.json 随机选择一个有项目的 group。"""
    with file_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    groups = data.get("groups", [])
    valid_groups = [g for g in groups if g.get("projects")]
    if not valid_groups:
        raise ValueError(f"文件中没有可用的 group/projects: {file_path}")

    selected = random.choice(valid_groups)
    group_id = int(selected.get("group_id", -1))
    projects = selected.get("projects", [])
    return group_id, projects


def build_query_text_from_project(project: Dict[str, Any]) -> str:
    """从单个项目抽取检索词，用于 SearchExpert 查专家。"""
    if not project:
        return "遥感"

    subject_name = (project.get("subject_name") or "").strip()

    keywords = project.get("keywords") or []
    if isinstance(keywords, list):
        keyword_list = [str(k).strip() for k in keywords if str(k).strip()]
        kw_text = " ".join(keyword_list[:2])
    else:
        kw_text = str(keywords).strip()

    title = (project.get("xmmc") or "").strip()
    short_title = title[:20] if title else ""

    parts = [part for part in [subject_name, kw_text, short_title] if part]
    query_text = " ".join(parts).strip()

    return query_text[:40] if query_text else "遥感"


if __name__ == "__main__":
    matcher = MatchAgent()

    grouping_file = Path(__file__).resolve().parent / "grouping_result.json"
    group_id, projects = load_random_group_projects(grouping_file)

    print(f"selected_group_id = {group_id}, project_count = {len(projects)}")

    output = asyncio.run(
        matcher.match_projects_individual_search(
            projects=projects[:1],
            top_k=1, # 5
            expert_limit=3, # 15
            search_timeout=30,
            max_concurrency=8,
            max_llm_concurrency=3,
        )
    )

    print("=== Match Result ===")
    for row in output:
        project_id = row["project_id"]
        query_text = row.get("query_text", "")
        expert_count = row.get("expert_count", 0)
        print(f"project_id = {project_id}, query_text = {query_text}, expert_count = {expert_count}")
        for item in row["top_experts"]:
            expert_id = item["expert_id"]
            expert_name = item["expert_name"]
            cosine_similarity = item["cosine_similarity"]
            match_score = item["match_score"]
            print(f"expert_id = {expert_id}, expert_name = {expert_name}")
            print(
                f"cosine_similarity = {cosine_similarity:.4f}, "
                f"match_score = {match_score:.2f}"
            )
