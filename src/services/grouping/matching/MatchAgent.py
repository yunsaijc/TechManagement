"""使用 ProjectEmbedder + ExpertEmbedder 进行项目-专家 Top-K 匹配。"""
import asyncio
from datetime import datetime
import json
from pathlib import Path
import random
import sys
from typing import Any, Dict, List

import numpy as np
import time

# 兼容 `python src/.../MatchAgent.py` 直接运行的场景
PROJECT_ROOT = Path(__file__).resolve().parents[4]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.services.grouping.matching.ExpertEmbedder import GraphExpertProfiler
from src.services.grouping.matching.ProjectEmbedder import ProjectEmbedder
from src.services.grouping.matching.SearchExpert import search_experts


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

    def _boost_score(self, score: float) -> float:
        return round(min(100.0, float(score) + 30.0), 2)

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
        expert_profile_concurrency: int = 4,
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
        expert_profiles = await self.expert_profiler.profile_experts(
            experts,
            max_concurrency=expert_profile_concurrency,
        )
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
                        "match_score": self._boost_score(cosine * 100),
                    }
                )

            results.append(
                {
                    "project_id": self._project_id(project, i),
                    "top_experts": top_experts,
                }
            )

        return results

    async def match_group_top_k(
        self,
        projects: List[Dict[str, Any]],
        experts: List[Dict[str, Any]],
        top_k: int = 5,
        expert_profile_concurrency: int = 4,
    ) -> Dict[str, Any]:
        """为整个项目组返回最相似的 Top-K 专家。"""
        if (not projects) or (not experts):
            return {"group_experts": []}

        proj_embed_t1 = time.time()
        project_vectors = self.project_embedder._generate_project_vectors(projects)
        proj_embed_t2 = time.time()
        proj_embed_time = proj_embed_t2 - proj_embed_t1
        print(f"proj_embed_time = {proj_embed_time:.2f} seconds")

        llm_t1 = time.time()
        expert_profiles = await self.expert_profiler.profile_experts(
            experts,
            max_concurrency=expert_profile_concurrency,
        )
        llm_t2 = time.time()
        llm_time = llm_t2 - llm_t1
        print(f"llm_time = {llm_time:.2f} seconds")

        exp_embed_t1 = time.time()
        expert_vectors = self.expert_profiler.generate_vectors(expert_profiles)
        exp_embed_t2 = time.time()
        exp_embed_time = exp_embed_t2 - exp_embed_t1
        print(f"exp_embed_time = {exp_embed_time:.2f} seconds")

        sim = self._cosine_similarity_matrix(project_vectors, expert_vectors)
        
        # 计算每个专家与所有项目的平均匹配度
        avg_similarity = np.mean(sim, axis=0)
        
        # 获取top_k个专家的索引
        top_indices = np.argsort(avg_similarity)[::-1][:top_k]

        top_experts = []
        for j in top_indices:
            cosine = float(avg_similarity[j])
            top_experts.append(
                {
                    "expert_id": self._expert_id(experts[j], j),
                    "expert_name": self._expert_name(experts[j], j),
                    "avg_cosine_similarity": round(cosine, 4),
                    "avg_match_score": self._boost_score(cosine * 100),
                }
            )

        return {
            "project_count": len(projects),
            "group_experts": top_experts,
        }

    async def match_projects_individual_search(
        self,
        projects: List[Dict[str, Any]],
        top_k: int = 5,
        expert_limit: int = 25,
        search_timeout: int = 30,
        max_concurrency: int = 3,
        max_llm_concurrency: int = 2,
        max_profile_concurrency: int = 4,
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
                matched = await self.match_top_k(
                    projects=[project],
                    experts=experts,
                    top_k=top_k,
                    expert_profile_concurrency=max_profile_concurrency,
                )
                match_time = time.time() - match_t1
                print(f"project_id={self._project_id(project, i)} match_time={match_time:.2f}s")

            row = matched[0] if matched else {"project_id": self._project_id(project, i), "top_experts": []}
            row["query_text"] = query_text
            row["expert_count"] = len(experts)
            return row

        tasks = [asyncio.create_task(process_one(i, project)) for i, project in enumerate(projects)]
        results = await asyncio.gather(*tasks)
        return results

    async def match_group_search(
        self,
        projects: List[Dict[str, Any]],
        group_subject_name: str | None = None,
        top_k: int = 5,
        expert_limit: int = 25,
        search_timeout: int = 30,
        max_profile_concurrency: int = 4,
    ) -> Dict[str, Any]:
        """为整个项目组检索并分配专家。"""
        if not projects:
            return {"group_experts": []}

        query_text = build_query_text_from_group(group_subject_name)
        representative_project = projects[0]
        fallback_query = (
            (group_subject_name or "").strip()
            or (representative_project.get("subject_name") or "").strip()
            or "遥感"
        )

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
        print(f"group search_experts_time={search_time:.2f}s")

        if not experts:
            return {
                "project_count": len(projects),
                "group_experts": [],
            }

        match_t1 = time.time()
        result = await self.match_group_top_k(
            projects=projects,
            experts=experts,
            top_k=top_k,
            expert_profile_concurrency=max_profile_concurrency,
        )
        match_time = time.time() - match_t1
        print(f"group match_time={match_time:.2f}s")

        result["query_text"] = query_text
        result["expert_count"] = len(experts)
        return result


def load_group_entries(file_path: Path) -> List[Dict[str, Any]]:
    """从 grouping_result.json 读取所有有效 group。"""
    with file_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    groups = data.get("groups", [])
    valid_groups = [g for g in groups if g.get("projects")]
    if not valid_groups:
        raise ValueError(f"文件中没有可用的 group/projects: {file_path}")

    return valid_groups


def backfill_project_titles_from_grouping(
    match_result_path: str | Path,
    grouping_result_path: str | Path,
    output_path: str | Path | None = None,
) -> Dict[str, Any]:
    """按 project_id 从 grouping_result.json 回填 match_result 中缺失的 project_title。"""
    match_result_path = Path(match_result_path)
    grouping_result_path = Path(grouping_result_path)
    output_path = Path(output_path) if output_path else match_result_path

    with grouping_result_path.open("r", encoding="utf-8") as f:
        grouping_payload = json.load(f)

    project_title_map: Dict[str, str] = {}
    for group in grouping_payload.get("groups", []):
        for project in group.get("projects", []):
            project_id = project.get("project_id") or project.get("id")
            title = project.get("xmmc") or project.get("project_title") or project.get("title")
            if project_id and title:
                project_title_map[str(project_id)] = str(title)

    with match_result_path.open("r", encoding="utf-8") as f:
        match_payload = json.load(f)

    if isinstance(match_payload, dict):
        results = match_payload.get("results")
        if not isinstance(results, list):
            raise ValueError(f"结果文件缺少 results 列表: {match_result_path}")
    elif isinstance(match_payload, list):
        results = match_payload
    else:
        raise ValueError(f"不支持的结果文件结构: {match_result_path}")

    updated_count = 0
    missing_count = 0
    for item in results:
        project_id = item.get("project_id")
        if not project_id:
            missing_count += 1
            continue

        title = project_title_map.get(str(project_id))
        if not title:
            missing_count += 1
            continue

        if not str(item.get("project_title") or "").strip():
            item["project_title"] = title
            updated_count += 1

    with output_path.open("w", encoding="utf-8") as f:
        json.dump(match_payload, f, ensure_ascii=False, indent=2)

    return {
        "output_path": str(output_path),
        "updated_count": updated_count,
        "missing_count": missing_count,
        "result_count": len(results),
    }


def rebuild_match_report_from_json(
    match_result_path: str | Path,
    report_html_path: str | Path,
) -> str:
    """根据最新 JSON 结果重建 HTML 报告。"""
    from src.services.grouping.matching.matching_report_builder import MatchingReportBuilder

    match_result_path = Path(match_result_path)
    report_html_path = Path(report_html_path)

    builder = MatchingReportBuilder()
    builder.build_from_json_file(match_result_path, report_html_path)
    return str(report_html_path)


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


def build_query_text_from_group(subject_name: str | None) -> str:
    """从 group 级 subject_name 构造专家检索词。"""
    query_text = str(subject_name or "").strip()
    return query_text[:40] if query_text else "遥感"


async def run_group_shared_matching(
    grouping_file: Path,
    top_k: int = 5,
    expert_limit: int = 10,
    search_timeout: int = 30,
    max_profile_concurrency: int = 4,
    sample_group_count: int | None = 10,
) -> Dict[str, Any]:
    """为 grouping_result.json 中的每个项目组分配一组共享专家。"""
    matcher = MatchAgent()
    groups = load_group_entries(grouping_file)
    if sample_group_count is not None:
        sample_size = max(1, min(int(sample_group_count), len(groups)))
        groups = random.sample(groups, sample_size)

    results: List[Dict[str, Any]] = []
    matched_group_count = 0
    unmatched_group_count = 0
    top1_scores: List[float] = []
    total_project_count = 0
    sampled_group_ids: List[int] = []

    for index, group in enumerate(groups, start=1):
        group_id = int(group.get("group_id", -1))
        subject_name = str(group.get("subject_name") or "").strip()
        projects = group.get("projects", []) or []
        total_project_count += len(projects)
        sampled_group_ids.append(group_id)

        print(
            f"[{index}/{len(groups)}] group_id={group_id} "
            f"subject_name={subject_name or '-'} project_count={len(projects)}"
        )

        result = await matcher.match_group_search(
            projects=projects,
            group_subject_name=subject_name,
            top_k=top_k,
            expert_limit=expert_limit,
            search_timeout=search_timeout,
            max_profile_concurrency=max_profile_concurrency,
        )

        group_result = {
            "group_id": group_id,
            "subject_name": subject_name,
            "project_count": len(projects),
            "projects": [
                str(project.get("xmmc") or project.get("project_title") or "").strip()
                for project in projects
                if str(project.get("xmmc") or project.get("project_title") or "").strip()
            ],
            **result,
        }
        results.append(group_result)

        group_experts = group_result.get("group_experts", []) or []
        if group_experts:
            matched_group_count += 1
            top1_scores.append(float(group_experts[0].get("avg_match_score", 0.0) or 0.0))
        else:
            unmatched_group_count += 1

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source_grouping_file": str(grouping_file),
        "summary": {
            "group_count": len(results),
            "matched_group_count": matched_group_count,
            "unmatched_group_count": unmatched_group_count,
            "project_count": total_project_count,
            "avg_top1_score": round(sum(top1_scores) / len(top1_scores), 2) if top1_scores else 0.0,
        },
        "run_config": {
            "top_k": top_k,
            "expert_limit": expert_limit,
            "search_timeout": search_timeout,
            "max_profile_concurrency": max_profile_concurrency,
            "sample_group_count": len(groups),
            "query_source": "group.subject_name",
            "score_adjustment": "+30 capped at 100",
        },
        "sampled_group_ids": sampled_group_ids,
        "results": results,
    }


if __name__ == "__main__":
    grouping_file = Path(__file__).resolve().parent / "grouping_result.json"
    output = asyncio.run(
        run_group_shared_matching(
            grouping_file=grouping_file,
            top_k=5,
            expert_limit=10,
            search_timeout=30,
            max_profile_concurrency=4,
            sample_group_count=10,
        )
    )

    print("=== Group Shared Match Summary ===")
    print(f"group_count = {output.get('summary', {}).get('group_count', 0)}")
    print(f"matched_group_count = {output.get('summary', {}).get('matched_group_count', 0)}")
    print(f"unmatched_group_count = {output.get('summary', {}).get('unmatched_group_count', 0)}")
    print(f"project_count = {output.get('summary', {}).get('project_count', 0)}")

    output_dir = Path(__file__).resolve().parent / "output"
    output_dir.mkdir(exist_ok=True)

    json_output_path = output_dir / "group_shared_match_results.json"
    with json_output_path.open("w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\n[OUTPUT] JSON 结果已保存到: {json_output_path}")

    try:
        html_output_path = output_dir / "group_shared_match_report.html"
        rebuild_match_report_from_json(json_output_path, html_output_path)
        print(f"[OUTPUT] HTML 报告已保存到: {html_output_path}")
    except Exception as e:
        print(f"[WARN] 生成 HTML 报告失败: {e}")
