"""分组 Agent

当前版本采用关键词Embedding主导 + 学科代码辅助分组策略：
1. 构造文本（关键词重复3次 + 项目名）确保关键词权重最高
2. 计算全局Embedding，建立语义空间
3. 基于Embedding相似度进行全局层次聚类
4. 对过大组/过小组合并基于Embedding再平衡

分组数据固定来自指定业务批次下、审核通过的项目子集。
"""
from __future__ import annotations

import json
import hashlib
import logging
import math
import os
import pickle
import re
import time
import uuid
from collections import defaultdict, Counter
from datetime import datetime
from functools import lru_cache
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

# 配置 logger
logger = logging.getLogger(__name__)

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
EMBEDDING_CACHE_FILE = os.path.join(DEBUG_DIR, "embedding_cache.pkl")


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "y", "on"}


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
    """构造用于Embedding的文本，关键词重复3次确保权重最高"""
    # 解析关键词
    keywords = _parse_keywords_to_list(project.gjc)
    
    # 无关键词时从项目名提取
    if not keywords and project.xmmc:
        keywords = _extract_keywords_from_title_to_list(project.xmmc)
    
    # 构造文本：关键词重复3次 + 项目名
    if keywords:
        keyword_str = "；".join(keywords)
        return f"{keyword_str}。研究主题：{keyword_str}。核心内容：{keyword_str}。项目名称：{project.xmmc or ''}"
    else:
        # 最后fallback：使用项目名
        return project.xmmc or ""


def _parse_keywords_to_list(gjc: Optional[str]) -> List[str]:
    """解析关键词字段为列表"""
    if not gjc:
        return []
    # 清洗HTML实体
    gjc = gjc.replace("&ldquo;", "").replace("&rdquo;", "")
    gjc = gjc.replace("&quot;", "").replace("&amp;", "&")
    separators = r'[;；,，]'
    keywords = re.split(separators, gjc)
    return [kw.strip() for kw in keywords if kw.strip()]


def _extract_keywords_from_title_to_list(title: str) -> List[str]:
    """从项目标题提取关键词列表"""
    if not title:
        return []
    tokens = re.findall(r'[\u4e00-\u9fff]{2,8}', title)
    stopwords = {'项目', '研究', '技术', '系统', '方法', '应用', '开发', '平台', '基于', '及其'}
    return [t for t in tokens if t not in stopwords][:5]  # 最多取5个


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
                "quantity_balance": result.statistics.quantity_balance,
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
                "projects": [
                    {
                        "project_id": item.project_id,
                        "xmmc": item.xmmc,
                        "xmjj": _clean_html_text(item.xmjj)[:200] if item.xmjj else "",  # 截取前200字
                        "original_subject_code": item.original_subject_code or "",
                        "original_subject_name": item.original_subject_name or "",
                        "keywords": item.keywords or [],
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
        use_llm_validation: bool = False,  # 默认禁用LLM验证以提高速度
        merge_min_total_score: Optional[float] = None,
        merge_min_text_score: Optional[float] = None,
    ):
        self.llm = llm or get_default_llm_client()
        self.embedder = embedder or get_default_embedding_client()
        self.max_per_group = max_per_group
        self.min_per_group = min_per_group
        self.concurrency = concurrency
        self.use_llm_validation = use_llm_validation
        self.merge_min_total_score = (
            merge_min_total_score
            if merge_min_total_score is not None
            else _env_float("GROUPING_MERGE_MIN_TOTAL_SCORE", 0.62)
        )
        self.merge_min_text_score = (
            merge_min_text_score
            if merge_min_text_score is not None
            else _env_float("GROUPING_MERGE_MIN_TEXT_SCORE", 0.45)
        )
        self.stop_after_first_merge_round_for_debug = _env_bool(
            "GROUPING_STOP_AFTER_FIRST_MERGE_ROUND", False
        )
        self.project_repo = ProjectRepository()
        self.xkfl_repo = get_xkfl_repo()
        self._subject_cache = self._load_subject_cache()
        self._llm_validation_cache: Dict[str, bool] = self._load_llm_validation_cache()  # 持久化缓存
        self._embedding_cache: Dict[str, List[float]] = self._load_embedding_cache()

    def _load_llm_validation_cache(self) -> Dict[str, bool]:
        """加载LLM验证缓存（持久化到文件）"""
        import json
        from pathlib import Path
        
        # 路径: tech/debug_grouping/llm_validation_cache.json
        cache_file = Path(__file__).parent.parent.parent.parent.parent / "debug_grouping" / "llm_validation_cache.json"
        if cache_file.exists():
            try:
                with open(cache_file, 'r', encoding='utf-8') as f:
                    cache = json.load(f)
                print(f"[缓存] 加载LLM验证缓存: {len(cache)} 条记录")
                return cache
            except Exception as e:
                print(f"[缓存] 加载LLM验证缓存失败: {e}")
        else:
            print(f"[缓存] 缓存文件不存在，创建新缓存")
        return {}
    
    def _save_llm_validation_cache(self):
        """保存LLM验证缓存到文件"""
        import json
        from pathlib import Path
        
        # 路径: tech/debug_grouping/llm_validation_cache.json
        cache_dir = Path(__file__).parent.parent.parent.parent.parent / "debug_grouping"
        cache_dir.mkdir(exist_ok=True)
        cache_file = cache_dir / "llm_validation_cache.json"
        
        try:
            with open(cache_file, 'w', encoding='utf-8') as f:
                json.dump(self._llm_validation_cache, f, ensure_ascii=False, indent=2)
            print(f"[缓存] 已保存 {len(self._llm_validation_cache)} 条LLM验证记录")
        except Exception as e:
            print(f"[缓存] 保存LLM验证缓存失败: {e}")

    def _load_embedding_cache(self) -> Dict[str, List[float]]:
        if not os.path.exists(EMBEDDING_CACHE_FILE):
            print("[缓存] Embedding缓存文件不存在，创建新缓存")
            return {}
        try:
            with open(EMBEDDING_CACHE_FILE, "rb") as f:
                cache = pickle.load(f)
            if isinstance(cache, dict):
                print(f"[缓存] 加载Embedding缓存: {len(cache)} 条记录")
                return cache
        except Exception as e:
            print(f"[缓存] 加载Embedding缓存失败: {e}")
        return {}

    def _save_embedding_cache(self):
        try:
            with open(EMBEDDING_CACHE_FILE, "wb") as f:
                pickle.dump(self._embedding_cache, f, protocol=pickle.HIGHEST_PROTOCOL)
            print(f"[缓存] 已保存Embedding缓存: {len(self._embedding_cache)} 条记录")
        except Exception as e:
            print(f"[缓存] 保存Embedding缓存失败: {e}")

    @staticmethod
    def _embedding_text_cache_key(text: str) -> str:
        return hashlib.sha1(text.encode("utf-8")).hexdigest()

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

    def _get_first_level_category(self, code: str) -> str:
        """获取学科大类（一级学科代码）
        
        A - 数理科学
        B - 化学科学  
        C - 生命科学
        D - 地球科学
        E - 工程与材料科学
        F - 信息科学
        G - 管理科学
        H - 医学科学
        J - 交叉学科
        """
        code = (code or "").strip()
        if not code:
            return ""
        # 返回第一个字母（大类）
        if code[0].isalpha():
            return code[0].upper()
        return ""

    def _is_same_discipline_category(self, code_a: str, code_b: str) -> bool:
        """检查两个学科代码是否属于同一大类"""
        cat_a = self._get_first_level_category(code_a)
        cat_b = self._get_first_level_category(code_b)
        # 如果任一个为空，允许合并（保守策略）
        if not cat_a or not cat_b:
            return True
        return cat_a == cat_b

    def _subject_similarity(self, code_a: str, code_b: str) -> float:
        a = (code_a or "").strip()
        b = (code_b or "").strip()
        if not a or not b:
            return 0.15
        if a == b:
            return 1.0

        # 【学科大类约束】不同大类直接返回0，禁止合并
        if not self._is_same_discipline_category(a, b):
            return 0.0

        # 同三级学科优先给高分；仅同一级大类则低分，避免细分方向误并
        third_a = self._get_third_level_code(a)
        third_b = self._get_third_level_code(b)
        if third_a and third_a == third_b:
            return 0.9

        prefixes_a = self._subject_prefixes(a)
        prefixes_b = self._subject_prefixes(b)
        common = [p for p in prefixes_a if p in prefixes_b]
        if not common:
            return 0.2

        longest = max(len(item) for item in common)
        if longest >= 3:
            return 0.55
        return 0.2

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
        """构建增强文本用于Embedding生成"""
        return self._build_enhanced_text(project)
    
    def _build_enhanced_text(self, project: Project) -> str:
        """构建增强文本，提升关键词和学科信息的权重"""
        parts = []
        
        # 1. 学科信息（高权重：重复3次）
        subject_code = project.ssxk1 or project.ssxk2 or ""
        subject_name = self._get_subject_name(subject_code)
        if subject_name and subject_name != "unknown":
            parts.extend([subject_name] * 3)
        
        # 2. 关键词（最高权重：重复5次）
        keywords = _parse_keywords_to_list(project.gjc)
        for kw in keywords:
            if kw and len(kw) >= 2:
                parts.extend([kw] * 5)
        
        # 3. 项目标题（清洗后）
        if project.xmmc:
            title = self._clean_text_for_embedding(project.xmmc)
            if title:
                parts.append(title)
        
        # 4. 项目简介（低权重：截断并清洗）
        if project.xmjj:
            summary = _clean_html_text(project.xmjj)
            summary = self._clean_text_for_embedding(summary)
            if summary:
                parts.append(summary[:200])
        
        return "。".join(parts)
    
    def _clean_text_for_embedding(self, text: str) -> str:
        """清洗文本，去除通用停用词"""
        if not text:
            return ""
        
        # 通用停用词表
        stopwords = {
            "优化", "调度", "系统", "方法", "研究", "技术", "应用",
            "开发", "平台", "关键", "实现", "相关", "面向", "基于",
            "一种", "及其", "理论", "模型", "机制", "设计", "分析",
            "进行", "开展", "提出", "解决", "探索", "建立", "构建",
        }
        
        # 清洗HTML实体
        text = text.replace("&ldquo;", "").replace("&rdquo;", "")
        text = text.replace("&quot;", "").replace("&amp;", "&")
        
        # 分词并去除停用词（提取2-8字的中文词）
        words = re.findall(r"[\u4e00-\u9fff]{2,8}", text)
        filtered = [w for w in words if w not in stopwords]
        return "。".join(filtered)

    def _embed_projects(self, projects: List[Project]) -> Dict[str, np.ndarray]:
        if not projects:
            return {}
        total = len(projects)
        logger.info(f"[Grouping] 开始生成 embedding: {total} 个项目")

        texts = [self._project_text(project) for project in projects]
        keys = [self._embedding_text_cache_key(text) for text in texts]

        vectors_map: Dict[str, np.ndarray] = {}
        missing_projects: List[Project] = []
        missing_texts: List[str] = []
        missing_keys: List[str] = []

        for project, text, key in zip(projects, texts, keys):
            cached = self._embedding_cache.get(key)
            if cached is not None:
                vectors_map[project.id] = np.asarray(cached, dtype=float)
            else:
                missing_projects.append(project)
                missing_texts.append(text)
                missing_keys.append(key)

        logger.info(
            f"[Grouping] embedding缓存命中 {len(vectors_map)}/{total}，未命中 {len(missing_projects)}"
        )

        if missing_projects:
            embed_start = time.time()
            embeddings = self.embedder.embed_documents(
                missing_texts,
                progress_callback=lambda done, total_batch: logger.info(
                    f"[Grouping] embedding 进度: {done}/{total_batch} 批次完成"
                ),
            )
            elapsed = time.time() - embed_start
            logger.info(f"[Grouping] embedding新计算完成: {len(missing_projects)} 个项目，用时 {elapsed:.2f} 秒")

            for project, key, vec in zip(missing_projects, missing_keys, embeddings):
                vec_list = [float(x) for x in vec]
                self._embedding_cache[key] = vec_list
                vectors_map[project.id] = np.asarray(vec_list, dtype=float)
            self._save_embedding_cache()

        return vectors_map

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

    def _split_large_clusters_by_embedding(
        self,
        clusters: List[List[Project]],
        max_per_group: int,
        vector_map: Dict[str, np.ndarray]
    ) -> List[List[Project]]:
        """拆分过大组（基于Embedding KMeans聚类）
        
        Args:
            clusters: 当前聚类列表
            max_per_group: 每组最大项目数
            vector_map: 项目ID到向量的映射
            
        Returns:
            拆分后的聚类列表
        """
        result = []
        for idx, cluster in enumerate(clusters):
            if len(cluster) <= max_per_group:
                result.append(cluster)
                continue
            
            # 过大组需要拆分
            print(f"  [拆分] 组{idx+1}有{len(cluster)}个项目，需要拆分...")
            sub_clusters = self._split_bucket_by_text(cluster, max_per_group, vector_map)
            result.extend(sub_clusters)
            print(f"  [拆分] 完成，拆成{len(sub_clusters)}个组")
        
        return result

    async def _merge_small_clusters_by_embedding(
        self,
        clusters: List[List[Project]],
        min_per_group: int,
        max_per_group: int,
        vector_map: Dict[str, np.ndarray]
    ) -> List[List[Project]]:
        """合并过小组（基于Embedding相似度，带LLM验证）
        
        Args:
            clusters: 当前聚类列表
            min_per_group: 每组最小项目数
            max_per_group: 每组最大项目数
            vector_map: 项目ID到向量的映射
            
        Returns:
            合并后的聚类列表
        """
        if not clusters:
            return clusters

        clusters = [cluster[:] for cluster in clusters if cluster]
        max_rounds = 20
        top_k = 3

        for round_idx in range(1, max_rounds + 1):
            clusters = [c for c in clusters if c]
            small_indices = [idx for idx, c in enumerate(clusters) if 0 < len(c) < min_per_group]
            if not small_indices:
                break

            print(f"[合并][第{round_idx}轮] 发现{len(small_indices)}个过小组需要处理...")

            # 预计算每个簇的中心向量与学科代码
            centers: List[Optional[np.ndarray]] = []
            codes: List[str] = []
            sizes: List[int] = []
            for cluster in clusters:
                sizes.append(len(cluster))
                codes.append(cluster[0].ssxk1 or cluster[0].ssxk2 or "")
                cluster_vectors = [vector_map[p.id] for p in cluster if p.id in vector_map]
                centers.append(np.mean(cluster_vectors, axis=0) if cluster_vectors else None)

            # 每个小组生成 top_k 候选
            candidate_edges: List[Dict[str, Any]] = []
            for src_idx in small_indices:
                src_size = sizes[src_idx]
                src_center = centers[src_idx]
                code_a = codes[src_idx]
                local_candidates: List[Dict[str, Any]] = []

                for dst_idx, _ in enumerate(clusters):
                    if dst_idx == src_idx:
                        continue
                    if sizes[dst_idx] + src_size > max_per_group:
                        continue

                    code_b = codes[dst_idx]
                    subject_score = self._subject_similarity(code_a, code_b)
                    text_score = 0.0
                    if src_center is not None and centers[dst_idx] is not None:
                        text_score = _cosine_similarity(src_center, centers[dst_idx])  # type: ignore[arg-type]
                    total_score = 0.75 * subject_score + 0.25 * text_score

                    if (
                        total_score < self.merge_min_total_score
                        or text_score < self.merge_min_text_score
                    ):
                        continue

                    local_candidates.append(
                        {
                            "src": src_idx,
                            "dst": dst_idx,
                            "score": total_score,
                            "text": text_score,
                            "subject": subject_score,
                            "code_a": code_a,
                            "code_b": code_b,
                        }
                    )

                if local_candidates:
                    local_candidates.sort(key=lambda item: item["score"], reverse=True)
                    candidate_edges.extend(local_candidates[:top_k])

            if not candidate_edges:
                print(f"[合并][第{round_idx}轮] 无满足门槛的候选，停止")
                break

            # 并发执行所有跨代码候选的LLM校验（去重）
            need_validate_keys: List[Tuple[int, int]] = []
            need_validate_payloads: List[Tuple[List[Project], List[Project], str, str]] = []
            seen_pairs: set[Tuple[int, int]] = set()
            for edge in candidate_edges:
                key = (edge["src"], edge["dst"])
                if edge["code_a"] == edge["code_b"] or key in seen_pairs:
                    continue
                seen_pairs.add(key)
                need_validate_keys.append(key)
                need_validate_payloads.append(
                    (
                        clusters[edge["src"]],
                        clusters[edge["dst"]],
                        edge["code_a"],
                        edge["code_b"],
                    )
                )

            validation_map: Dict[Tuple[int, int], bool] = {}
            if need_validate_payloads:
                results = await self._batch_llm_validate_merges(need_validate_payloads, persist_cache=False)
                for key, ok in zip(need_validate_keys, results):
                    validation_map[key] = ok
                # 按轮次统一写缓存，避免每次校验落盘
                self._save_llm_validation_cache()

            # 冲突消解：按分数从高到低选择无冲突合并边
            candidate_edges.sort(key=lambda item: item["score"], reverse=True)
            planned_merges: List[Dict[str, Any]] = []
            used_as_source: set[int] = set()
            used_as_target: set[int] = set()
            target_loads = sizes[:]

            for edge in candidate_edges:
                src = edge["src"]
                dst = edge["dst"]

                # src不能重复，也不能既当target又当source
                if src in used_as_source or src in used_as_target:
                    continue
                # dst若已作为source使用，跳过，避免链式冲突
                if dst in used_as_source:
                    continue

                if edge["code_a"] != edge["code_b"]:
                    if not validation_map.get((src, dst), False):
                        print(f"  [合并拒绝] 组{src+1} -> 组{dst+1}，代码{edge['code_a']}!={edge['code_b']}，LLM拒绝")
                        continue

                src_size = sizes[src]
                if target_loads[dst] + src_size > max_per_group:
                    continue

                used_as_source.add(src)
                used_as_target.add(dst)
                target_loads[dst] += src_size
                planned_merges.append(edge)

            if not planned_merges:
                print(f"[合并][第{round_idx}轮] 无可提交合并计划，停止")
                break

            # 统一提交本轮合并
            for edge in planned_merges:
                src = edge["src"]
                dst = edge["dst"]
                if src >= len(clusters) or dst >= len(clusters) or not clusters[src] or not clusters[dst]:
                    continue
                clusters[dst].extend(clusters[src])
                clusters[src] = []
                print(
                    f"  [合并] 将组{src+1}({sizes[src]}个项目)合并到组{dst+1} "
                    f"(score={edge['score']:.3f}, text={edge['text']:.3f}, subject={edge['subject']:.3f})"
                )

            clusters = [c for c in clusters if c]
            print(f"[合并][第{round_idx}轮] 完成 {len(planned_merges)} 次合并，剩余 {len(clusters)} 组")

            if self.stop_after_first_merge_round_for_debug and round_idx == 1:
                debug_file = self._save_unmerged_groups_for_debug(clusters, min_per_group, round_idx)
                if debug_file:
                    print(f"[合并][调试] 已按要求在第1轮后停止，未合并结果已保存: {debug_file}")
                break

        return [c for c in clusters if c]

    def _save_unmerged_groups_for_debug(
        self,
        clusters: List[List[Project]],
        min_per_group: int,
        round_idx: int,
    ) -> str:
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"merge_unmerged_round{round_idx}_{timestamp}.json"
            filepath = os.path.join(DEBUG_DIR, filename)

            groups = []
            small_group_ids = []
            counts = []
            for idx, cluster in enumerate(clusters, start=1):
                code_counter = Counter((p.ssxk1 or p.ssxk2 or "") for p in cluster if (p.ssxk1 or p.ssxk2))
                dominant_code = code_counter.most_common(1)[0][0] if code_counter else ""
                dominant_name = self._get_subject_name(dominant_code) if dominant_code else "未知主题"
                count = len(cluster)
                counts.append(count)
                group_entry = {
                    "group_id": idx,
                    "subject_code": dominant_code or None,
                    "subject_name": dominant_name,
                    "count": count,
                    "projects": [
                        {
                            "project_id": p.id,
                            "xmmc": p.xmmc,
                            "xmjj": _clean_html_text(p.xmjj) if p.xmjj else "",
                            "original_subject_code": p.ssxk1 or p.ssxk2 or "",
                            "original_subject_name": self._get_subject_name(p.ssxk1 or p.ssxk2 or ""),
                            "keywords": _parse_keywords_to_list(p.gjc)[:20],
                        }
                        for p in cluster
                    ],
                }
                groups.append(group_entry)
                if 0 < count < min_per_group:
                    small_group_ids.append(idx)

            payload = {
                "id": f"merge_debug_round{round_idx}_{timestamp}",
                "year": "fixed",
                "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "statistics": {
                    "round": round_idx,
                    "total_groups_after_round": len(clusters),
                    "small_group_count_after_round": len(small_group_ids),
                    "small_group_ids": small_group_ids,
                    "min_per_group": min_per_group,
                    "avg_projects_per_group": round(_safe_mean(counts), 2) if counts else 0.0,
                    "max_projects_per_group": max(counts) if counts else 0,
                    "min_projects_per_group": min(counts) if counts else 0,
                },
                "meta": {
                    "type": "merge_debug_after_round",
                },
                "groups": groups,
            }
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            return filename
        except Exception as exc:
            print(f"[合并][调试] 保存未合并结果失败: {exc}")
            return ""

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

    async def _cluster_projects(self, projects: List[Project], max_per_group: int) -> List[List[Project]]:
        """基于关键词Embedding主导的全局层次聚类分组"""
        if not projects:
            return []
        if len(projects) <= max_per_group:
            return [projects]

        print(f"[Grouping] 开始关键词Embedding主导分组，共 {len(projects)} 个项目")

        # 1. 计算全局Embedding
        print(f"[Grouping] 计算全局Embedding...")
        vector_map = self._embed_projects(projects)
        print(f"[Grouping] Embedding计算完成，共 {len(vector_map)} 个项目")

        # 2. 基于Embedding相似度进行全局层次聚类（带LLM验证）
        print(f"[Grouping] 进行全局层次聚类...")
        clusters = await self._hierarchical_cluster_by_embedding(projects, vector_map, similarity_threshold=0.7)
        print(f"[Grouping] 初始聚类完成，生成 {len(clusters)} 个组")

        # 2.5 【学科大类约束】按学科大类拆分混合组
        print(f"[Grouping] 按学科大类拆分混合组...")
        clusters = self._split_by_discipline_category(clusters)
        print(f"[Grouping] 学科大类拆分完成，共 {len(clusters)} 个组")

        # 3. 处理过大组（基于Embedding重新聚类拆分）
        print(f"[Grouping] 处理过大组...")
        clusters = self._split_large_clusters_by_embedding(clusters, max_per_group, vector_map)
        print(f"[Grouping] 过大组拆分完成，共 {len(clusters)} 个组")

        # 4. 处理过小组合并到最相似的组（带LLM验证）
        print(f"[Grouping] 处理过小组合并...")
        clusters = await self._merge_small_clusters_by_embedding(clusters, self.min_per_group, max_per_group, vector_map)
        print(f"[Grouping] 过小组合并完成，共 {len(clusters)} 个组")

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
        # 先清洗HTML标签
        text = re.sub(r'<[^>]+>', ' ', text or "")
        # 清洗HTML实体
        text = re.sub(r'&[a-zA-Z]+;', ' ', text)
        # 清洗CSS样式相关的内容
        text = re.sub(r'\b\d+px\b', ' ', text)  # 移除 16px, 12px 等
        text = re.sub(r'\b[a-z]+-[a-z]+\b', ' ', text)  # 移除 font-style 等CSS属性
        
        # 提取中文词（2-6个字的词）
        chinese_tokens = re.findall(r"[\u4e00-\u9fff]{2,6}", text)
        # 提取英文/数字词
        english_tokens = re.findall(r"[A-Za-z][a-zA-Z0-9]*", text)
        
        tokens = chinese_tokens + english_tokens
        
        stopwords = {
            "项目", "研究", "技术", "系统", "方法", "应用", "开发", "平台", "关键", "实现",
            "相关", "面向", "基于", "一种", "及其", "关键技术", "理论", "模型", "机制",
            "设计", "分析", "优化", "控制", "检测", "监测", "识别", "预测", "决策",
            "协同", "联合", "综合", "新型", "智能", "智慧", "自动", "集成",
            # HTML/CSS常见词
            "font", "style", "size", "color", "px", "indent", "margin", "text", "align",
            "span", "div", "p", "br", "strong", "em", "b", "i", "u",
        }
        return [token for token in tokens if token not in stopwords and len(token) <= 10]

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
            for project in cluster:
                score = 1.0
                # 使用数据库的gjc字段作为关键词
                keywords = _parse_keywords_to_list(project.gjc)[:10]  # 最多10个
                
                project_items.append(
                    ProjectInGroup(
                        project_id=project.id,
                        xmmc=project.xmmc,
                        xmjj=project.xmjj or "",
                        subject_code=project.ssxk1,
                        subject_name=subject_name or self._get_subject_name(project.ssxk1 or "unknown"),
                        semantic_score=score,
                        reason=summary or f"语义归入：{title}",
                        original_subject_code=project.ssxk1,
                        original_subject_name=self._get_subject_name(project.ssxk1 or ""),
                        keywords=keywords,
                    )
                )

            group = ProjectGroup(
                group_id=index,
                subject_code=cluster[0].ssxk1 if cluster and cluster[0].ssxk1 else None,
                subject_name=subject_name or title,
                projects=project_items,
                count=len(cluster),
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
                "subject_purity": 1.0,
                "split_correctness": 1.0,
            }

        counts = [group.count for group in groups]
        avg_count = _safe_mean(counts)
        quantity_balance = 1.0 if not counts or avg_count == 0 else max(0.0, 1 - (np.std(counts) / (avg_count + 1e-8)))

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
            "subject_purity": round(float(subject_purity), 3),
            "split_correctness": round(float(split_correctness), 3),
        }

    async def group_projects(self, request: GroupingRequest) -> GroupingResult:
        start_time = time.time()
        self.max_per_group = request.max_per_group
        if request.merge_min_total_score is not None:
            self.merge_min_total_score = request.merge_min_total_score
        if request.merge_min_text_score is not None:
            self.merge_min_text_score = request.merge_min_text_score

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
        clusters = await self._cluster_projects(projects, self.max_per_group)
        print(f"[Grouping] 初步生成 {len(clusters)} 个语义簇，用时 {time.time() - cluster_start:.2f} 秒")

        build_group_start = time.time()
        groups = await self._build_groups(clusters)
        print(f"[Grouping] ProjectGroup 构建完成，用时 {time.time() - build_group_start:.2f} 秒")

        counts = [group.count for group in groups]
        metrics = self._balance_metrics(groups)
        balance_score = (
            metrics["quantity_balance"] * 0.5
            + metrics["subject_purity"] * 0.5
        )

        stats = GroupingStatistics(
            total_projects=len(projects),
            group_count=len(groups),
            balance_score=round(balance_score, 3),
            avg_projects_per_group=round(_safe_mean(counts), 2),
            quantity_balance=metrics["quantity_balance"],
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
                "merge_min_total_score": self.merge_min_total_score,
                "merge_min_text_score": self.merge_min_text_score,
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


# ========== Embedding主导分组新方法 ==========

    def _split_by_discipline_category(
        self,
        clusters: List[List[Project]]
    ) -> List[List[Project]]:
        """按三级学科优先拆分混合组

        先按三级学科代码（前5位）拆分，避免同大类内细分方向混杂。
        """
        result = []
        
        for cluster in clusters:
            if not cluster:
                continue
            
            # 按三级学科分组
            category_groups: Dict[str, List[Project]] = {}
            for project in cluster:
                code = project.ssxk1 or project.ssxk2 or ""
                cat = self._get_third_level_code(code)
                if not cat:
                    cat = "unknown"
                if cat not in category_groups:
                    category_groups[cat] = []
                category_groups[cat].append(project)
            
            # 如果只有一个三级代码，保持原组
            if len(category_groups) <= 1:
                result.append(cluster)
            else:
                # 拆分成多个组
                for cat, projects in category_groups.items():
                    if projects:
                        result.append(projects)
                        print(f"  [学科拆分] 拆出 {cat} 组，{len(projects)} 个项目")
        
        return result
    
    async def _hierarchical_cluster_by_embedding(
        self,
        projects: List[Project],
        vector_map: Dict[str, np.ndarray],
        similarity_threshold: float = 0.7
    ) -> List[List[Project]]:
        """基于Embedding相似度进行全局层次聚类（使用scipy优化版本）
        
        【改进】在初始聚类后进行学科一致性验证：
        1. 先按Embedding相似度聚类
        2. 对每个聚类检查学科一致性
        3. 以主导学科（项目数最多）为锚点
        4. 对非主导学科的项目进行LLM验证
        5. 验证失败的项目从聚类中移除
        """
        n = len(projects)
        if n == 0:
            return []
        if n == 1:
            return [projects]
        
        print(f"[初始聚类] 开始，共 {n} 个项目")
        
        # 获取所有embedding向量
        vectors = np.array([vector_map.get(p.id, np.zeros(1536)) for p in projects])
        
        # 使用scipy的层次聚类（C实现，比Python快100倍+）
        from scipy.cluster.hierarchy import linkage, fcluster
        from scipy.spatial.distance import pdist
        
        # 计算距离矩阵并聚类（向量化，比Python循环快）
        distances = pdist(vectors, metric='cosine')
        linkage_matrix = linkage(distances, method='average')
        
        # 根据相似度阈值确定聚类
        distance_threshold = 1 - similarity_threshold
        labels = fcluster(linkage_matrix, t=distance_threshold, criterion='distance')
        
        # 按标签分组
        clusters_dict: Dict[int, List[int]] = {}
        for idx, label in enumerate(labels):
            if label not in clusters_dict:
                clusters_dict[label] = []
            clusters_dict[label].append(idx)
        
        # 将索引转换为项目对象
        initial_clusters = [[projects[idx] for idx in cluster] for cluster in clusters_dict.values()]
        print(f"[初始聚类] 完成，生成 {len(initial_clusters)} 个初始组")
        
        # 【新增】对每个聚类进行学科一致性验证
        if not self.use_llm_validation:
            print(f"[初始聚类] 未启用LLM验证，跳过学科一致性检查")
            return initial_clusters
        
        print(f"[初始聚类] 开始学科一致性验证...")
        validated_clusters = await self._validate_initial_clusters_with_llm(initial_clusters, vector_map)
        print(f"[初始聚类] 验证完成，最终 {len(validated_clusters)} 个组")
        
        return validated_clusters

    async def _validate_initial_clusters_with_llm(
        self,
        clusters: List[List[Project]],
        vector_map: Dict[str, np.ndarray]
    ) -> List[List[Project]]:
        """【新增】验证初始聚类的学科一致性，以主导学科为锚点
        
        【优化】先收集所有组的验证请求，然后一次性并发执行
        
        对每个聚类：
        1. 统计各三级学科的项目数量
        2. 确定主导学科（项目数最多的学科）
        3. 对非主导学科的项目进行LLM验证
        4. 验证失败的项目从聚类中移除，形成新的独立组
        """
        # 第一步：收集所有需要验证的请求
        all_validations = []  # List of (cluster_idx, project, dominant_subject, representative_projects, project_subject)
        cluster_info = []  # 保存每个组的信息
        
        for cluster_idx, cluster in enumerate(clusters):
            if len(cluster) <= 1:
                cluster_info.append({
                    'cluster': cluster,
                    'skip': True,
                    'dominant_subject': None,
                    'project_subject_map': {},
                    'to_validate_indices': []
                })
                continue
            
            # 统计三级学科分布
            subject_counter = Counter()
            project_subject_map = {}
            
            for project in cluster:
                code = project.ssxk1 or project.ssxk2 or ""
                third_level_code = self._get_third_level_code(code)
                subject_counter[third_level_code] += 1
                project_subject_map[project.id] = third_level_code
            
            # 如果只有一个三级学科，跳过验证
            if len(subject_counter) <= 1:
                cluster_info.append({
                    'cluster': cluster,
                    'skip': True,
                    'dominant_subject': None,
                    'project_subject_map': project_subject_map,
                    'to_validate_indices': []
                })
                print(f"  [组{cluster_idx+1}] 单一学科，跳过验证")
                continue
            
            # 确定主导学科
            dominant_subject = subject_counter.most_common(1)[0][0]
            dominant_count = subject_counter[dominant_subject]
            
            print(f"  [组{cluster_idx+1}] 包含{len(subject_counter)}个学科，主导学科: {dominant_subject} ({dominant_count}个项目)")
            
            # 收集需要验证的项目
            to_validate_indices = []
            representative_projects = [p for p in cluster if (p.ssxk1 or p.ssxk2 or "").startswith(dominant_subject[:3])][:3]
            
            for proj_idx, project in enumerate(cluster):
                code = project_subject_map[project.id]
                if code != dominant_subject:
                    to_validate_indices.append(proj_idx)
                    all_validations.append((
                        cluster_idx,
                        project,
                        dominant_subject,
                        representative_projects,
                        code
                    ))
            
            cluster_info.append({
                'cluster': cluster,
                'skip': False,
                'dominant_subject': dominant_subject,
                'project_subject_map': project_subject_map,
                'to_validate_indices': to_validate_indices
            })
        
        # 第二步：如果没有任何验证请求，直接返回
        if not all_validations:
            print(f"[初始聚类] 无需验证，直接返回 {len(clusters)} 个组")
            return clusters
        
        # 第三步：一次性并发执行所有验证
        print(f"[LLM并发验证] 共收集 {len(all_validations)} 个验证请求，开始并发执行...")
        
        # 构造批量验证参数：(cluster_a, cluster_b, code_a, code_b)
        # cluster_a: 主导学科的代表项目
        # cluster_b: 待验证的单个项目
        # code_a: 主导学科代码
        # code_b: 待验证项目的学科代码
        validations_for_batch = [
            (info[3], [info[1]], info[2], info[4])  # (representative_projects, [project], dominant_subject, project_subject)
            for info in all_validations
        ]
        
        # 调用批量验证
        validation_results = await self._batch_llm_validate_merges(validations_for_batch)
        
        # 第四步：根据验证结果处理每个组
        validated_clusters = []
        removed_projects = []
        
        # 建立验证结果的索引
        validation_idx = 0
        for cluster_idx, info in enumerate(cluster_info):
            cluster = info['cluster']
            
            if info['skip']:
                validated_clusters.append(cluster)
                continue
            
            dominant_subject = info['dominant_subject']
            project_subject_map = info['project_subject_map']
            to_validate_indices = info['to_validate_indices']
            
            # 根据验证结果分离项目
            keep_projects = []
            for i, proj_idx in enumerate(to_validate_indices):
                project = cluster[proj_idx]
                if validation_results[validation_idx]:
                    keep_projects.append(project)
                else:
                    removed_projects.append(project)
                    print(f"    ❌ 移除: {project.xmmc[:30]}...")
                validation_idx += 1
            
            # 保留主导学科项目 + 验证通过的项目
            main_cluster = [p for p in cluster if project_subject_map[p.id] == dominant_subject]
            main_cluster.extend(keep_projects)
            
            if main_cluster:
                validated_clusters.append(main_cluster)
        
        # 第五步：为移除的项目创建独立组
        for project in removed_projects:
            validated_clusters.append([project])
            print(f"  [新增独立组] {project.xmmc[:30]}...")
        
        return validated_clusters

    async def _batch_validate_single_projects(
        self,
        cluster: List[Project],
        to_validate: List[Project],
        dominant_subject: str,
        vector_map: Dict[str, np.ndarray]
    ) -> List[bool]:
        """【新增】批量验证单个项目是否应该保留在主导学科组中
        
        Args:
            cluster: 原始聚类
            to_validate: 需要验证的项目列表
            dominant_subject: 主导三级学科代码
        
        Returns:
            List[bool]: 每个项目是否应该保留
        """
        if not to_validate:
            return []
        
        # 批量调用LLM验证
        validations = []
        for project in to_validate:
            dominant_subject_name = self._get_subject_name(dominant_subject)
            project_subject_name = self._get_subject_name(project.ssxk1 or project.ssxk2 or "")
            
            validations.append((
                [p for p in cluster if (p.ssxk1 or p.ssxk2 or "").startswith(dominant_subject[:3])][:3],  # 主导学科的代表项目
                [project],  # 待验证的单个项目
                dominant_subject,
                project.ssxk1 or project.ssxk2 or ""
            ))
        
        # 批量验证
        results = await self._batch_llm_validate_merges(validations)
        return results

    async def _batch_llm_validate_merges(
        self,
        validations: List[Tuple[List[Project], List[Project], str, str]],
        persist_cache: bool = True,
    ) -> List[bool]:
        """【P1】批量并发执行LLM验证（限制并发数为10）
        
        Args:
            validations: 列表，每个元素是 (cluster_a, cluster_b, code_a, code_b)
            
        Returns:
            列表，每个元素是对应验证的结果（True=可以合并，False=拒绝合并）
        """
        if not validations or not self.use_llm_validation:
            return [True] * len(validations)

        import asyncio
        
        # 使用实例并发配置
        sem = asyncio.Semaphore(max(1, int(self.concurrency)))
        
        # 打印并发信息
        print(f"[LLM并发验证] 启动 {len(validations)} 个验证任务（并发限制：{max(1, int(self.concurrency))}）")

        async def validate_one(cluster_a, cluster_b, code_a, code_b, idx):
            async with sem:
                try:
                    print(f"[LLM并发验证] 启动第{idx+1}/{len(validations)}个任务")
                    r = await self._llm_validate_merge(
                        cluster_a, cluster_b, code_a, code_b, persist_cache=persist_cache
                    )
                    print(f"[LLM并发验证] 第{idx+1}/{len(validations)}个任务完成")
                    return r
                except Exception as e:
                    print(f"[LLM并发验证] 第{idx+1}个异常: {e}，默认允许合并")
                    return True

        # 创建所有任务并同时启动
        tasks = [
            validate_one(cluster_a, cluster_b, code_a, code_b, i)
            for i, (cluster_a, cluster_b, code_a, code_b) in enumerate(validations)
        ]

        # 使用asyncio.gather并发执行（信号量控制实际并发数）
        all_results = await asyncio.gather(*tasks, return_exceptions=False)
        print(f"[LLM并发验证] 所有 {len(validations)} 个任务已完成")
        return all_results

    async def _llm_validate_merge(
        self,
        cluster_a: List[Project],
        cluster_b: List[Project],
        code_a: str,
        code_b: str,
        persist_cache: bool = True,
    ) -> bool:
        """使用LLM验证两个不同三级学科代码的组是否应该合并

        返回: True 表示应该合并，False 表示不应该合并
        """
        if not self.use_llm_validation:
            return True

        # 如果学科代码相同，不需要LLM验证
        if code_a == code_b:
            return True

        # 检查缓存（学科代码 + 代表项目上下文）
        context_a = self._validation_context_hash(cluster_a)
        context_b = self._validation_context_hash(cluster_b)
        cache_key = f"{code_a}:{code_b}:{context_a}:{context_b}"
        reverse_key = f"{code_b}:{code_a}:{context_b}:{context_a}"
        if cache_key in self._llm_validation_cache:
            return self._llm_validation_cache[cache_key]
        if reverse_key in self._llm_validation_cache:
            return self._llm_validation_cache[reverse_key]

        # 构造LLM判断的prompt
        subject_name_a = self._get_subject_name(code_a)
        subject_name_b = self._get_subject_name(code_b)

        # 提取每个组的代表性项目信息（最多3个）
        projects_a_info = []
        for p in cluster_a[:3]:
            keywords = _parse_keywords_to_list(p.gjc)
            projects_a_info.append({
                "name": p.xmmc,
                "keywords": keywords,
                "abstract": _clean_html_text(p.xmjj)[:200] if p.xmjj else "",
            })

        projects_b_info = []
        for p in cluster_b[:3]:
            keywords = _parse_keywords_to_list(p.gjc)
            projects_b_info.append({
                "name": p.xmmc,
                "keywords": keywords,
                "abstract": _clean_html_text(p.xmjj)[:200] if p.xmjj else "",
            })

        prompt = f"""你是一位科研项目分组专家。请判断以下两个来自不同三级学科的项目组是否应该分在同一评审组。

【学科A】{code_a} ({subject_name_a})
代表项目：
"""
        for i, p in enumerate(projects_a_info, 1):
            prompt += f"{i}. {p['name']}\n"
            if p['keywords']:
                prompt += f"   关键词：{', '.join(p['keywords'])}\n"
            if p['abstract']:
                prompt += f"   简介：{p['abstract']}\n"

        prompt += f"""
【学科B】{code_b} ({subject_name_b})
代表项目：
"""
        for i, p in enumerate(projects_b_info, 1):
            prompt += f"{i}. {p['name']}\n"
            if p['keywords']:
                prompt += f"   关键词：{', '.join(p['keywords'])}\n"
            if p['abstract']:
                prompt += f"   简介：{p['abstract']}\n"

        prompt += """
【判断标准】
1. 两个组的研究内容是否高度相关，可以由同一批专家评审？
2. 如果合并，是否会导致评审专家难以公正评价（因为超出专业范围）？

请回答：
- 如果应该合并（研究内容高度相关，适合同一批专家评审），回答：是
- 如果不应该合并（研究内容差异大，不适合同一批专家评审），回答：否

只回答"是"或"否"，不要解释。"""

        try:
            print(f"[LLM验证] 开始调用: {code_a} vs {code_b}")
            import asyncio
            # 添加60秒超时
            response = await asyncio.wait_for(self.llm.ainvoke(prompt), timeout=60.0)
            result = response.content.strip().lower() if hasattr(response, 'content') else str(response).strip().lower()
            should_merge = "是" in result or "yes" in result or "true" in result

            # 缓存结果（双向都存）
            self._llm_validation_cache[cache_key] = should_merge
            self._llm_validation_cache[reverse_key] = should_merge
            if persist_cache:
                self._save_llm_validation_cache()  # 持久化保存
            print(f"[LLM验证] 学科{code_a} vs {code_b}: {'通过' if should_merge else '拒绝'}合并")
            return should_merge
        except asyncio.TimeoutError:
            print(f"[LLM验证] 学科{code_a} vs {code_b}: 超时，默认不允许合并")
            return False
        except Exception as e:
            print(f"[LLM验证] 调用失败: {e}，默认不允许合并")
            return False

    def _validation_context_hash(self, cluster: List[Project]) -> str:
        tokens: List[str] = []
        for project in cluster[:3]:
            code = project.ssxk1 or project.ssxk2 or ""
            third = self._get_third_level_code(code)
            keywords = ",".join(_parse_keywords_to_list(project.gjc)[:5])
            tokens.append(f"{third}|{(project.xmmc or '')[:60]}|{keywords}")
        raw = "||".join(tokens)
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]

    def _get_third_level_code(self, code: str) -> str:
        """获取三级学科代码（前5位）"""
        code = (code or "").strip()
        if len(code) >= 5:
            return code[:5]
        return code
