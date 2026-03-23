"""分组 Agent

当前版本采用学科代码 + 关键词联合分组策略：
1. 按完整学科代码（6位）粗分桶
2. 在桶内基于关键词Jaccard相似度进行层次聚类
3. 组内主题一致性由关键词重叠度保证

分组数据固定来自指定业务批次下、审核通过的项目子集。
"""
from __future__ import annotations

import json
import math
import os
import re
import time
import uuid
from collections import defaultdict, Counter
from datetime import datetime
from functools import lru_cache
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from src.common.llm import get_default_embedding_client, get_default_llm_client
from src.common.models.grouping import (
    FullGroupingRequest,
    FullGroupingResult,
    FullStatistics,
    GroupingRequest,
    GroupingResult,
    GroupingStatistics,
    GroupSummary,
    GroupingStrategy,
    Project,
    ProjectGroup,
    ProjectInGroup,
)
from src.services.grouping.matching.agent import MatchingAgent
from src.services.grouping.storage.project_repo import ProjectRepository
from src.common.database import get_xkfl_repo


DEBUG_DIR = "/home/tdkx/workspace/tech/debug_grouping"
os.makedirs(DEBUG_DIR, exist_ok=True)


def _clean_html_text(text: Optional[str]) -> str:
    if not text:
        return ""
    clean = re.sub(r"<[^>]+>", "", text)
    clean = clean.replace("&nbsp;", " ")
    clean = clean.replace("&amp;", "&")
    clean = clean.replace("&lt;", "<")
    clean = clean.replace("&gt;", ">")
    clean = clean.replace("&quot;", '"')
    clean = re.sub(r"\s+", " ", clean)
    return clean.strip()


def _text_for_project(project: Project, include_abstract: bool = True) -> str:
    parts = [project.xmmc or ""]
    if project.gjc:
        parts.append(project.gjc)
    if include_abstract and project.xmjj:
        parts.append(_clean_html_text(project.xmjj)[:800])
    return "。".join([part for part in parts if part])


def _safe_mean(values: List[float]) -> float:
    return float(np.mean(values)) if values else 0.0


def _cosine_similarity(vec_a: np.ndarray, vec_b: np.ndarray) -> float:
    denom = (np.linalg.norm(vec_a) * np.linalg.norm(vec_b)) + 1e-8
    return float(np.dot(vec_a, vec_b) / denom)


def _save_grouping_result(dataset_tag: str, result: GroupingResult, meta: Optional[dict] = None) -> str:
    try:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"grouping_{dataset_tag}_{timestamp}.json"
        filepath = os.path.join(DEBUG_DIR, filename)
        created_at = result.created_at.strftime("%Y-%m-%d %H:%M:%S") if hasattr(result.created_at, "strftime") else str(result.created_at)

        data = {
            "id": result.id,
            "year": result.year,
            "created_at": created_at,
            "statistics": {
                "total_projects": result.statistics.total_projects,
                "group_count": result.statistics.group_count,
                "balance_score": result.statistics.balance_score,
                "avg_projects_per_group": result.statistics.avg_projects_per_group,
                "avg_quality_per_group": result.statistics.avg_quality_per_group,
                "quality_mean": result.statistics.quality_mean,
                "quality_median": result.statistics.quality_median,
                "quality_std": result.statistics.quality_std,
                "quality_min": result.statistics.quality_min,
                "quality_max": result.statistics.quality_max,
                "quantity_balance": result.statistics.quantity_balance,
                "quality_balance": result.statistics.quality_balance,
                "subject_purity": result.statistics.subject_purity,
                "split_correctness": result.statistics.split_correctness,
                "audit_reminder": result.statistics.audit_reminder,
            },
            "meta": meta or {},
            "groups": [],
        }

        for group in result.groups:
            data["groups"].append({
                "group_id": group.group_id,
                "subject_code": group.subject_code,
                "subject_name": group.subject_name,
                "count": group.count,
                "avg_quality": group.avg_quality,
                "max_quality": group.max_quality,
                "min_quality": group.min_quality,
                "projects": [
                    {
                        "project_id": item.project_id,
                        "xmmc": item.xmmc,
                        "xmjj": _clean_html_text(item.xmjj) if item.xmjj else "",
                        "semantic_score": item.semantic_score,
                        "quality_score": item.quality_score,
                        "reason": item.reason,
                    }
                    for item in group.projects
                ],
            })

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        return filename
    except Exception as exc:
        print(f"[Grouping] 保存分组结果失败: {exc}")
        return ""


class GroupingAgent:
    """语义优先分组 Agent"""

    def __init__(
        self,
        llm: Any = None,
        embedder: Any = None,
        max_per_group: int = 15,
        min_per_group: int = 5,
        concurrency: int = 10,
    ):
        self.llm = llm or get_default_llm_client()
        self.embedder = embedder or get_default_embedding_client()
        self.max_per_group = max_per_group
        self.min_per_group = min_per_group
        self.concurrency = concurrency
        self.project_repo = ProjectRepository()
        self.xkfl_repo = get_xkfl_repo()
        self._subject_cache = self._load_subject_cache()

    def _load_subject_cache(self) -> Dict[str, str]:
        try:
            subject_cache: Dict[str, str] = {}

            zrjj_rows = self.xkfl_repo.list_all_zrjj()
            for row in zrjj_rows:
                code = str(row.get("code") or "").strip()
                name = str(row.get("name") or "").strip()
                if code and name:
                    subject_cache[code] = name

            rows = self.xkfl_repo.list_all()
            for row in rows:
                code = str(row.get("code") or "").strip()
                name = str(row.get("name") or "").strip()
                if code and name and code not in subject_cache:
                    subject_cache[code] = name

            return subject_cache
        except Exception:
            return {}

    def _get_subject_name(self, code: str) -> str:
        if not code or code == "unknown":
            return "未知主题"
        return self._subject_cache.get(code, code)

    @staticmethod
    def _subject_prefixes(code: str) -> List[str]:
        code = (code or "").strip()
        if not code:
            return []

        prefixes = []
        if code[0].isalpha():
            if len(code) >= 1:
                prefixes.append(code[:1])
            if len(code) >= 3:
                prefixes.append(code[:3])
            if len(code) >= 5:
                prefixes.append(code[:5])
            prefixes.append(code)
        else:
            for size in (2, 4, 6, len(code)):
                if len(code) >= size:
                    prefixes.append(code[:size])

        ordered = []
        seen = set()
        for item in prefixes:
            if item and item not in seen:
                seen.add(item)
                ordered.append(item)
        return ordered

    def _subject_similarity(self, code_a: str, code_b: str) -> float:
        a = (code_a or "").strip()
        b = (code_b or "").strip()
        if not a or not b:
            return 0.15
        if a == b:
            return 1.0

        prefixes_a = self._subject_prefixes(a)
        prefixes_b = self._subject_prefixes(b)
        common = [p for p in prefixes_a if p in prefixes_b]
        if not common:
            return 0.0

        longest = max(len(item) for item in common)
        max_len = max(len(a), len(b), 1)
        return min(0.95, 0.35 + 0.6 * (longest / max_len))

    def _subject_group_key(self, project: Project) -> str:
        code = (project.ssxk1 or project.ssxk2 or "unknown").strip()
        prefixes = self._subject_prefixes(code)
        if len(prefixes) >= 3:
            return prefixes[2]
        if prefixes:
            return prefixes[-1]
        return "unknown"

    def _normalize_text(self, text: str) -> str:
        return re.sub(r"\s+", " ", text or "").strip()

    def _build_project_profile(self, project: Project) -> Dict[str, str]:
        abstract = _clean_html_text(project.xmjj) if project.xmjj else ""
        subject_name = self._get_subject_name(project.ssxk1 or "unknown")
        return {
            "id": project.id,
            "xmmc": project.xmmc or "",
            "xmmc_clean": self._normalize_text(project.xmmc or ""),
            "xmjj": abstract[:800],
            "subject_code": project.ssxk1 or "",
            "subject_name": subject_name,
            "text": _text_for_project(project),
        }

    @lru_cache(maxsize=4096)
    def _project_text_key(self, project_id: str, xmmc: str, gjc: str, xmjj: str) -> str:
        parts = [xmmc or "", gjc or "", (xmjj or "")[:800]]
        return "。".join([part for part in parts if part])

    def _project_text(self, project: Project) -> str:
        return self._project_text_key(project.id, project.xmmc or "", project.gjc or "", _clean_html_text(project.xmjj or ""))

    def _embed_projects(self, projects: List[Project]) -> Dict[str, np.ndarray]:
        if not projects:
            return {}
        texts = [self._project_text(project) for project in projects]
        print(f"[Grouping] 开始生成 embedding: {len(projects)} 个项目")
        embed_start = time.time()
        vectors = self._safe_embed(texts)
        print(f"[Grouping] embedding 完成: {len(projects)} 个项目，用时 {time.time() - embed_start:.2f} 秒")
        return {project.id: vectors[idx] for idx, project in enumerate(projects)}

    def _bucket_projects_by_subject(self, projects: List[Project]) -> Dict[str, List[Project]]:
        buckets: Dict[str, List[Project]] = defaultdict(list)
        for project in projects:
            buckets[self._subject_group_key(project)].append(project)
        return buckets

    def _embed_large_buckets_only(self, buckets: Dict[str, List[Project]], max_per_group: int) -> Dict[str, np.ndarray]:
        large_projects: List[Project] = []
        large_bucket_count = 0
        for bucket in buckets.values():
            if len(bucket) > max_per_group:
                large_bucket_count += 1
                large_projects.extend(bucket)
        print(f"[Grouping] 学科粗分完成: {len(buckets)} 个桶，其中 {large_bucket_count} 个大桶需要 embedding，共 {len(large_projects)} 个项目")
        return self._embed_projects(large_projects)

    def _split_bucket_by_text(self, bucket: List[Project], max_per_group: int, vector_map: Dict[str, np.ndarray]) -> List[List[Project]]:
        if len(bucket) <= max_per_group:
            return [bucket]

        n_clusters = max(2, math.ceil(len(bucket) / max_per_group))
        vectors = np.asarray([vector_map[project.id] for project in bucket], dtype=float)
        labels = self._kmeans(vectors, n_clusters)
        grouped: Dict[int, List[Project]] = defaultdict(list)
        for idx, label in enumerate(labels):
            grouped[int(label)].append(bucket[idx])

        result: List[List[Project]] = []
        for _, members in sorted(grouped.items(), key=lambda item: (-len(item[1]), item[0])):
            if len(members) > max_per_group:
                result.extend(self._split_bucket_by_text(members, max_per_group, vector_map))
            else:
                result.append(members)
        return result

    def _merge_small_clusters(self, clusters: List[List[Project]], vector_map: Dict[str, np.ndarray], max_per_group: int) -> List[List[Project]]:
        clusters = [cluster[:] for cluster in clusters if cluster]
        changed = True
        while changed:
            changed = False
            small_index = next((idx for idx, cluster in enumerate(clusters) if 0 < len(cluster) < self.min_per_group), None)
            if small_index is None:
                break

            cluster = clusters[small_index]
            code_a = cluster[0].ssxk1 or cluster[0].ssxk2 or ""
            cluster_vectors = [vector_map[item.id] for item in cluster if item.id in vector_map]
            center_a = np.mean(cluster_vectors, axis=0) if cluster_vectors else None

            best_idx = None
            best_score = -1.0
            for idx, other in enumerate(clusters):
                if idx == small_index:
                    continue
                if len(other) + len(cluster) > max_per_group:
                    continue
                code_b = other[0].ssxk1 or other[0].ssxk2 or ""
                subject_score = self._subject_similarity(code_a, code_b)
                other_vectors = [vector_map[item.id] for item in other if item.id in vector_map]
                if center_a is not None and other_vectors:
                    center_b = np.mean(other_vectors, axis=0)
                    text_score = _cosine_similarity(center_a, center_b)
                else:
                    text_score = 0.0
                total_score = 0.75 * subject_score + 0.25 * text_score
                if total_score > best_score:
                    best_score = total_score
                    best_idx = idx

            if best_idx is None:
                break

            clusters[best_idx].extend(cluster)
            clusters.pop(small_index)
            changed = True

        return clusters

    def _infer_target_group_count(self, project_count: int, max_per_group: int) -> int:
        if project_count <= 0:
            return 0
        base = max(1, math.ceil(project_count / max_per_group))
        if project_count < 20:
            return max(2 if project_count > 6 else 1, base)
        if project_count < 60:
            return max(3, base)
        return max(4, base)

    def _safe_embed(self, texts: List[str]) -> np.ndarray:
        embeddings = self.embedder.embed_documents(texts)
        return np.asarray(embeddings, dtype=float)

    def _kmeans(self, vectors: np.ndarray, n_clusters: int) -> np.ndarray:
        from src.services.grouping.grouping.cluster import ProjectCluster
        return ProjectCluster("kmeans").fit_predict(vectors, n_clusters)

    def _cluster_projects(self, projects: List[Project], max_per_group: int) -> List[List[Project]]:
        """基于代码+关键词的联合分组"""
        if not projects:
            return []
        if len(projects) <= max_per_group:
            return [projects]

        print(f"[Grouping] 开始代码+关键词联合分组，共 {len(projects)} 个项目")
        
        # 1. 按完整学科代码粗分
        buckets = self._group_by_code_prefix(projects)
        print(f"[Grouping] 按完整代码粗分为 {len(buckets)} 个桶")
        
        # 2. 对每个桶进行关键词聚类
        all_clusters: List[List[Project]] = []
        for prefix, bucket in buckets.items():
            print(f"[Grouping] 处理代码桶 {prefix}，共 {len(bucket)} 个项目")
            clusters = self._cluster_by_keywords(bucket, max_per_group, similarity_threshold=0.3)
            all_clusters.extend(clusters)
        
        print(f"[Grouping] 关键词聚类完成，生成 {len(all_clusters)} 个初始组")
        
        # 3. 处理过小/过大组
        clusters = self._rebalance_by_keywords(all_clusters, max_per_group)
        
        print(f"[Grouping] 最终分组完成，共 {len(clusters)} 个组")
        return clusters

    def _rebalance_clusters(self, clusters: List[List[Project]], max_per_group: int, vector_map: Optional[Dict[str, np.ndarray]] = None) -> List[List[Project]]:
        if not clusters:
            return clusters

        vector_map = vector_map or self._embed_projects([project for cluster in clusters for project in cluster])

        changed = True
        while changed:
            changed = False
            clusters = [cluster for cluster in clusters if cluster]

            # 拆分过大簇
            for idx, cluster in list(enumerate(clusters)):
                if len(cluster) <= max_per_group:
                    continue
                replacement = self._split_bucket_by_text(cluster, max_per_group, vector_map)
                clusters[idx:idx + 1] = replacement
                changed = True
                break

            if changed:
                continue

            # 合并过小簇
            small_indices = [idx for idx, cluster in enumerate(clusters) if 0 < len(cluster) < self.min_per_group]
            if not small_indices:
                break

            for idx in small_indices:
                if idx >= len(clusters):
                    continue
                cluster = clusters[idx]
                if not cluster:
                    continue
                target_idx = None
                best_similarity = -1.0
                current_vectors = [vector_map[project.id] for project in cluster if project.id in vector_map]
                current_vec = np.mean(current_vectors, axis=0) if current_vectors else None
                current_code = cluster[0].ssxk1 or cluster[0].ssxk2 or ""
                for other_idx, other_cluster in enumerate(clusters):
                    if other_idx == idx or not other_cluster:
                        continue
                    if len(other_cluster) + len(cluster) > max_per_group:
                        continue
                    other_vectors = [vector_map[project.id] for project in other_cluster if project.id in vector_map]
                    other_code = other_cluster[0].ssxk1 or other_cluster[0].ssxk2 or ""
                    text_similarity = 0.0
                    if current_vec is not None and other_vectors:
                        other_vec = np.mean(other_vectors, axis=0)
                        text_similarity = _cosine_similarity(current_vec, other_vec)
                    similarity = 0.75 * self._subject_similarity(current_code, other_code) + 0.25 * text_similarity
                    if similarity > best_similarity:
                        best_similarity = similarity
                        target_idx = other_idx
                if target_idx is not None:
                    clusters[target_idx].extend(cluster)
                    clusters[idx] = []
                    changed = True
                    break

        return [cluster for cluster in clusters if cluster]

    def _extract_keywords(self, text: str) -> List[str]:
        tokens = re.findall(r"[\u4e00-\u9fffA-Za-z0-9]{2,}", text or "")
        stopwords = {
            "项目", "研究", "技术", "系统", "方法", "应用", "开发", "平台", "关键", "实现",
            "相关", "面向", "基于", "一种", "及其", "关键技术", "理论", "模型", "机制",
        }
        return [token for token in tokens if token not in stopwords]

    def _select_group_title(self, cluster: List[Project]) -> Tuple[str, str, str]:
        subject_codes = [project.ssxk1 for project in cluster if project.ssxk1]
        subject_name = ""
        if subject_codes:
            common = Counter(subject_codes).most_common(1)[0][0]
            subject_name = self._get_subject_name(common)

        keyword_counter: Counter[str] = Counter()
        for project in cluster[:10]:
            keyword_counter.update(self._extract_keywords(project.xmmc or ""))

        top_keywords = [word for word, _ in keyword_counter.most_common(2)]
        if subject_name and top_keywords:
            title = f"{subject_name}-{''.join(top_keywords)}"
        elif subject_name:
            title = subject_name
        elif top_keywords:
            title = "-".join(top_keywords)
        else:
            title = "综合主题"

        sample_names = "、".join((project.xmmc or "")[:20] for project in cluster[:3] if project.xmmc)
        summary = f"按学科与项目主题聚合形成的分组"
        if sample_names:
            summary += f"，代表项目包括：{sample_names}"

        return title[:40] or "综合主题", summary[:120], subject_name

    def _build_group_summary(self, cluster: List[Project], title: str) -> GroupSummary:
        themes = []
        for project in cluster[:3]:
            themes.append(project.xmmc[:12])
        return GroupSummary(
            count=len(cluster),
            avg_score=0.0,
            main_themes=themes or [title],
        )

    async def _build_groups(self, clusters: List[List[Project]]) -> List[ProjectGroup]:
        total_clusters = len(clusters)
        build_start = time.time()

        async def build_one(index: int, cluster: List[Project]) -> ProjectGroup:
            cluster_start = time.time()
            print(f"[Grouping] 生成分组标题进度 {index}/{total_clusters}，簇内项目 {len(cluster)} 个")

            title, summary, subject_name = self._select_group_title(cluster)

            project_items = []
            scores = []
            for project in cluster:
                score = 1.0
                scores.append(score)
                project_items.append(
                    ProjectInGroup(
                        project_id=project.id,
                        xmmc=project.xmmc,
                        xmjj=project.xmjj or "",
                        subject_code=project.ssxk1,
                        subject_name=subject_name or self._get_subject_name(project.ssxk1 or "unknown"),
                        semantic_score=score,
                        quality_score=score,
                        reason=summary or f"语义归入：{title}",
                    )
                )

            group = ProjectGroup(
                group_id=index,
                subject_code=cluster[0].ssxk1 if cluster and cluster[0].ssxk1 else None,
                subject_name=subject_name or title,
                projects=project_items,
                count=len(cluster),
                avg_quality=round(_safe_mean(scores), 2),
                max_quality=round(max(scores), 2) if scores else 0.0,
                min_quality=round(min(scores), 2) if scores else 0.0,
                summary=self._build_group_summary(cluster, title),
            )

            print(
                f"[Grouping] 分组标题完成 {index}/{total_clusters}：{title}，"
                f"用时 {time.time() - cluster_start:.2f} 秒"
            )
            return group

        groups = []
        for index, cluster in enumerate(clusters, start=1):
            groups.append(await build_one(index, cluster))

        print(f"[Grouping] 所有分组标题生成完成，用时 {time.time() - build_start:.2f} 秒")
        return list(groups)

    def _balance_metrics(self, groups: List[ProjectGroup]) -> Dict[str, float]:
        if not groups:
            return {
                "quantity_balance": 1.0,
                "quality_balance": 1.0,
                "subject_purity": 1.0,
                "split_correctness": 1.0,
            }

        counts = [group.count for group in groups]
        avg_count = _safe_mean(counts)
        quantity_balance = 1.0 if not counts or avg_count == 0 else max(0.0, 1 - (np.std(counts) / (avg_count + 1e-8)))

        group_sizes = [group.avg_quality for group in groups if group.count > 0]
        quality_balance = 1.0 if not group_sizes else max(0.0, 1 - np.std(group_sizes))

        subject_purity_scores = []
        for group in groups:
            codes = [item.subject_code for item in group.projects if item.subject_code]
            if not codes:
                continue
            dominant = Counter(codes).most_common(1)[0][1]
            subject_purity_scores.append(dominant / len(codes))
        subject_purity = _safe_mean(subject_purity_scores) if subject_purity_scores else 1.0

        split_correctness = 1.0
        return {
            "quantity_balance": round(float(quantity_balance), 3),
            "quality_balance": round(float(quality_balance), 3),
            "subject_purity": round(float(subject_purity), 3),
            "split_correctness": round(float(split_correctness), 3),
        }

    async def group_projects(self, request: GroupingRequest) -> GroupingResult:
        start_time = time.time()
        self.max_per_group = request.max_per_group

        projects = self.project_repo.get_grouping_test_projects(category=request.category)
        if not projects:
            raise ValueError("固定分组测试数据集中没有可用项目")

        projects = [project for project in projects if project.xmmc and project.xmmc.strip()]
        if not projects:
            raise ValueError("没有可用于分组的项目名称")

        dataset_filter = self.project_repo.get_grouping_dataset_filter()
        print(
            f"[Grouping] 获取到 {len(projects)} 个项目，"
            f"使用固定测试数据集 guide={dataset_filter['guide_code']} audit={dataset_filter['audit_status']}，开始分组"
        )

        cluster_start = time.time()
        clusters = self._cluster_projects(projects, self.max_per_group)
        print(f"[Grouping] 初步生成 {len(clusters)} 个语义簇，用时 {time.time() - cluster_start:.2f} 秒")

        build_group_start = time.time()
        groups = await self._build_groups(clusters)
        print(f"[Grouping] ProjectGroup 构建完成，用时 {time.time() - build_group_start:.2f} 秒")

        counts = [group.count for group in groups]
        avg_scores = [group.avg_quality for group in groups]
        metrics = self._balance_metrics(groups)
        balance_score = (
            metrics["quantity_balance"] * 0.4
            + metrics["quality_balance"] * 0.2
            + metrics["subject_purity"] * 0.4
        )

        stats = GroupingStatistics(
            total_projects=len(projects),
            group_count=len(groups),
            balance_score=round(balance_score, 3),
            avg_projects_per_group=round(_safe_mean(counts), 2),
            avg_quality_per_group=round(_safe_mean(avg_scores), 2),
            quality_mean=round(_safe_mean(avg_scores), 2) if avg_scores else 0.0,
            quality_median=round(float(np.median(avg_scores)), 2) if avg_scores else 0.0,
            quality_std=round(float(np.std(avg_scores)), 2) if avg_scores else 0.0,
            quality_min=round(float(min(avg_scores)), 2) if avg_scores else 0.0,
            quality_max=round(float(max(avg_scores)), 2) if avg_scores else 0.0,
            quantity_balance=metrics["quantity_balance"],
            quality_balance=metrics["quality_balance"],
            subject_purity=metrics["subject_purity"],
            split_correctness=metrics["split_correctness"],
            audit_reminder=None,
        )

        result = GroupingResult(
            id=str(uuid.uuid4()),
            year="fixed",
            groups=groups,
            statistics=stats,
            created_at=datetime.now(),
        )

        save_start = time.time()
        filename = _save_grouping_result("fixed", result, meta={
            "strategy": request.strategy.value if request.strategy else GroupingStrategy.SEMANTIC.value,
            "dataset_filter": dataset_filter,
            "input": {
                "category": request.category,
                "max_per_group": request.max_per_group,
            },
        })
        if filename:
            print(f"[Grouping] 结果已保存: {filename}，用时 {time.time() - save_start:.2f} 秒")

        elapsed = time.time() - start_time
        print(f"[Grouping] 完成，用时 {elapsed:.2f} 秒，分组 {len(groups)} 个")
        return result

    async def match_experts(self, group: ProjectGroup, group_id: int, request: Any):
        matching_agent = MatchingAgent(self.llm, self.embedder)
        return await matching_agent.match_experts(group, group_id, request)

    async def full_grouping(self, request: FullGroupingRequest) -> FullGroupingResult:
        grouping_request = GroupingRequest(
            category=request.category,
            max_per_group=request.max_per_group,
            strategy=GroupingStrategy.SEMANTIC,
        )
        grouping_result = await self.group_projects(grouping_request)

        matches = {}
        warnings: List[str] = []
        for group in grouping_result.groups:
            matching_request = request.model_copy(update={"group_id": group.group_id}) if hasattr(request, "model_copy") else None
            from src.common.models.grouping import MatchingRequest
            mr = MatchingRequest(
                group_id=group.group_id,
                experts_per_project=request.experts_per_project,
                min_experts_per_group=request.min_experts_per_group,
                avoid_relations=request.avoid_relations,
                max_reviews_per_expert=request.max_reviews_per_expert,
            )
            match_result = await self.match_experts(group, group.group_id, mr)
            matches[group.group_id] = match_result
            warnings.extend(match_result.warnings)

        total_projects = grouping_result.statistics.total_projects
        total_groups = grouping_result.statistics.group_count
        total_experts = set()
        avg_match_score = 0.0
        match_count = 0

        for match_result in matches.values():
            for assignment in match_result.matches:
                for expert in assignment.experts:
                    total_experts.add(expert.expert_id)
                    avg_match_score += expert.match_score
                    match_count += 1

        if match_count > 0:
            avg_match_score /= match_count

        statistics = FullStatistics(
            total_projects=total_projects,
            total_groups=total_groups,
            total_experts=len(total_experts),
            avg_match_score=avg_match_score,
            balance_score=grouping_result.statistics.balance_score,
        )

        report = (
            f"分组与匹配完成。共{total_projects}个项目分成{total_groups}组，"
            f"平均每组{total_projects // max(1, total_groups)}个项目。"
        )
        if total_experts:
            report += f" 共涉及{len(total_experts)}位专家。"
        if avg_match_score > 0:
            report += f" 平均匹配度{avg_match_score:.1f}分。"
        if warnings:
            report += f" 检测到{len(warnings)}条提示。"

        return FullGroupingResult(
            id=f"full_{grouping_result.id}",
            year="fixed",
            category=request.category,
            groups=grouping_result.groups,
            matches=matches,
            statistics=statistics,
            report=report,
        )


# ========== 关键词分组相关方法 ==========

    def _get_code_prefix(self, code: str) -> str:
        """提取完整学科代码作为分组桶键（使用全部6位代码进行粗分）"""
        code = (code or "").strip()
        if not code:
            return "unknown"
        # 使用完整代码进行粗分，如 F020202、B010303
        return code

    def _parse_keywords(self, gjc: Optional[str]) -> set:
        """解析关键词字段为集合"""
        if not gjc:
            return set()
        # 支持分号、逗号分隔
        separators = r'[;；,，]'
        keywords = re.split(separators, gjc)
        # 清洗：去空格、统一小写
        return {kw.strip().lower() for kw in keywords if kw.strip()}

    def _jaccard_similarity(self, set_a: set, set_b: set) -> float:
        """计算两个集合的Jaccard相似度"""
        if not set_a or not set_b:
            return 0.0
        intersection = len(set_a & set_b)
        union = len(set_a | set_b)
        return intersection / union if union > 0 else 0.0

    def _compute_keyword_similarity_matrix(self, projects: List[Project]) -> np.ndarray:
        """计算项目间的关键词相似度矩阵"""
        n = len(projects)
        matrix = np.zeros((n, n))
        
        # 提取所有项目的关键词，gjc为空时从项目名提取
        keywords_list = []
        for p in projects:
            kw = self._parse_keywords(p.gjc)
            if not kw and p.xmmc:
                # 从项目名提取关键词作为fallback
                kw = self._extract_keywords_from_title(p.xmmc)
            keywords_list.append(kw)
        
        # 计算相似度矩阵（对称矩阵，只计算上三角）
        for i in range(n):
            for j in range(i + 1, n):
                sim = self._jaccard_similarity(keywords_list[i], keywords_list[j])
                matrix[i, j] = matrix[j, i] = sim
        
        return matrix

    def _extract_keywords_from_title(self, title: str) -> set:
        """从项目标题提取关键词"""
        if not title:
            return set()
        # 提取2-8字的中文词组
        tokens = re.findall(r'[\u4e00-\u9fff]{2,8}', title)
        # 过滤停用词
        stopwords = {'项目', '研究', '技术', '系统', '方法', '应用', '开发', '平台', '基于', '及其'}
        return {t for t in tokens if t not in stopwords}

    def _hierarchical_cluster_by_keywords(
        self, 
        projects: List[Project], 
        similarity_matrix: np.ndarray,
        similarity_threshold: float = 0.3
    ) -> List[List[Project]]:
        """基于关键词相似度进行层次聚类"""
        n = len(projects)
        if n == 0:
            return []
        if n == 1:
            return [projects]
        
        # 初始化：每个项目为一个簇
        clusters = [[i] for i in range(n)]
        
        # 层次聚类：不断合并相似度最高的簇
        while len(clusters) > 1:
            best_sim = -1.0
            best_pair = None
            
            # 找出相似度最高的一对簇
            for i in range(len(clusters)):
                for j in range(i + 1, len(clusters)):
                    # 计算两个簇之间的平均相似度
                    sim_sum = 0.0
                    count = 0
                    for idx_a in clusters[i]:
                        for idx_b in clusters[j]:
                            sim_sum += similarity_matrix[idx_a, idx_b]
                            count += 1
                    avg_sim = sim_sum / count if count > 0 else 0.0
                    
                    if avg_sim > best_sim:
                        best_sim = avg_sim
                        best_pair = (i, j)
            
            # 如果最高相似度低于阈值，停止合并
            if best_sim < similarity_threshold:
                break
            
            # 合并最相似的两个簇
            if best_pair:
                i, j = best_pair
                clusters[i].extend(clusters[j])
                clusters.pop(j)
        
        # 将索引转换为项目对象
        return [[projects[idx] for idx in cluster] for cluster in clusters]

    def _group_by_code_prefix(self, projects: List[Project]) -> Dict[str, List[Project]]:
        """按完整学科代码分组"""
        buckets: Dict[str, List[Project]] = defaultdict(list)
        for project in projects:
            prefix = self._get_code_prefix(project.ssxk1)
            buckets[prefix].append(project)
        return dict(buckets)

    def _cluster_by_keywords(
        self, 
        projects: List[Project], 
        max_per_group: int = 15,
        similarity_threshold: float = 0.3
    ) -> List[List[Project]]:
        """基于关键词的完整聚类流程"""
        if not projects:
            return []
        if len(projects) <= max_per_group:
            return [projects]
        
        # 计算相似度矩阵
        similarity_matrix = self._compute_keyword_similarity_matrix(projects)
        
        # 层次聚类
        clusters = self._hierarchical_cluster_by_keywords(
            projects, similarity_matrix, similarity_threshold
        )
        
        # 处理过大的组：按相似度继续拆分
        result = []
        for cluster in clusters:
            if len(cluster) > max_per_group:
                # 递归拆分
                sub_clusters = self._cluster_by_keywords(
                    cluster, max_per_group, similarity_threshold
                )
                result.extend(sub_clusters)
            else:
                result.append(cluster)
        
        return result

    def _rebalance_by_keywords(
        self, 
        clusters: List[List[Project]], 
        max_per_group: int
    ) -> List[List[Project]]:
        """基于关键词相似度再平衡分组"""
        if not clusters:
            return clusters
        
        changed = True
        while changed:
            changed = False
            clusters = [c for c in clusters if c]
            
            # 拆分过大组
            for idx, cluster in list(enumerate(clusters)):
                if len(cluster) <= max_per_group:
                    continue
                # 重新聚类
                sub_clusters = self._cluster_by_keywords(cluster, max_per_group, 0.3)
                clusters[idx:idx + 1] = sub_clusters
                changed = True
                break
            
            if changed:
                continue
            
            # 合并过小组
            small_indices = [i for i, c in enumerate(clusters) if 0 < len(c) < self.min_per_group]
            if not small_indices:
                break
            
            for idx in small_indices:
                if idx >= len(clusters):
                    continue
                cluster = clusters[idx]
                if not cluster:
                    continue
                
                # 计算与哪个组最相似
                cluster_keywords = set()
                for p in cluster:
                    cluster_keywords.update(self._parse_keywords(p.gjc))
                
                best_idx = None
                best_sim = -1.0
                current_code = self._get_code_prefix(cluster[0].ssxk1)
                
                for other_idx, other in enumerate(clusters):
                    if other_idx == idx or not other:
                        continue
                    if len(other) + len(cluster) > max_per_group:
                        continue
                    
                    # 代码前缀必须相同
                    other_code = self._get_code_prefix(other[0].ssxk1)
                    if current_code != other_code:
                        continue
                    
                    # 计算关键词相似度
                    other_keywords = set()
                    for p in other:
                        other_keywords.update(self._parse_keywords(p.gjc))
                    
                    sim = self._jaccard_similarity(cluster_keywords, other_keywords)
                    if sim > best_sim:
                        best_sim = sim
                        best_idx = other_idx
                
                if best_idx is not None:
                    clusters[best_idx].extend(cluster)
                    clusters[idx] = []
                    changed = True
                    break
        
        return [c for c in clusters if c]
