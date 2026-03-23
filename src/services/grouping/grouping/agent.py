"""
分组 Agent

重构版：按学科分组 + 质量评估 + 均衡分配

逻辑：
1. 按三级学科初步分组
2. 数量 ≤15 → 保留原分组
3. 数量 >15 → 质量评估 + 均衡分配
4. 合并结果
"""
import asyncio
import json
import os
import re
import time
import uuid
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional

import matplotlib
matplotlib.use('Agg')  # 非交互式后端
import matplotlib.pyplot as plt
import numpy as np

from src.common.llm import get_default_llm_client
from src.common.models.grouping import (
    GroupingRequest,
    GroupingResult,
    GroupingStatistics,
    GroupSummary,
    Project,
    ProjectGroup,
    ProjectInGroup,
    ProjectQuality,
)
from src.services.grouping.grouping.quality import QualityAssessor
from src.services.grouping.storage.project_repo import ProjectRepository
from src.common.database import get_subject_repo


# 缓存目录
CACHE_DIR = "/home/tdkx/workspace/tech/.cache"
DEBUG_DIR = "/home/tdkx/workspace/tech/debug_grouping"
os.makedirs(CACHE_DIR, exist_ok=True)
os.makedirs(DEBUG_DIR, exist_ok=True)

# 质量分数缓存（内存）
_QUALITY_CACHE: Dict[str, float] = {}

# 缓存文件路径
_QUALITY_CACHE_FILE = os.path.join(CACHE_DIR, "grouping_quality.json")


def _clean_html_text(text: Optional[str]) -> str:
    """清洗 HTML 标签和实体（模块级函数）"""
    if not text:
        return ""
    # 移除 HTML 标签
    clean = re.sub(r'<[^>]+>', '', text)
    # 替换 HTML 实体
    clean = clean.replace('&nbsp;', ' ')
    clean = clean.replace('&amp;', '&')
    clean = clean.replace('&lt;', '<')
    clean = clean.replace('&gt;', '>')
    clean = clean.replace('&quot;', '"')
    # 移除多余空白
    clean = re.sub(r'\s+', ' ', clean)
    return clean.strip()


def _calculate_quality_stats(quality_scores: Dict[str, float]) -> dict:
    """计算质量分数统计信息
    
    Args:
        quality_scores: {project_id: score}
    
    Returns:
        {
            mean, median, std, min, max,
            distribution: {score_range: count}
        }
    """
    if not quality_scores:
        return {}
    
    scores = list(quality_scores.values())
    
    # 基本统计
    mean = np.mean(scores)
    median = np.median(scores)
    std = np.std(scores)
    min_score = min(scores)
    max_score = max(scores)
    
    # 分布统计（每10分一段）
    distribution = {}
    for score in scores:
        bucket = int(score // 10) * 10
        distribution[f"{bucket}-{bucket+9}"] = distribution.get(f"{bucket}-{bucket+9}", 0) + 1
    
    return {
        "mean": round(mean, 2),
        "median": round(median, 2),
        "std": round(std, 2),
        "min": round(min_score, 2),
        "max": round(max_score, 2),
        "distribution": distribution
    }


def _generate_quality_charts(quality_scores: Dict[str, float], groups: List[ProjectGroup], year: str):
    """生成质量统计图表并保存
    
    Args:
        quality_scores: 所有项目质量分数
        groups: 分组列表
        year: 年份
    """
    try:
        # 设置中文字体
        plt.rcParams['font.sans-serif'] = ['DejaVu Sans', 'Arial Unicode MS', 'SimHei']
        plt.rcParams['axes.unicode_minus'] = False
        
        fig, axes = plt.subplots(2, 2, figsize=(12, 10))
        fig.suptitle(f'Grouping Quality Report - {year}', fontsize=14)
        
        # 1. 质量分数分布直方图
        ax1 = axes[0, 0]
        scores = list(quality_scores.values())
        if scores:
            ax1.hist(scores, bins=10, edgecolor='black', alpha=0.7, color='steelblue')
            ax1.axvline(np.mean(scores), color='red', linestyle='--', label=f'Mean: {np.mean(scores):.1f}')
            ax1.axvline(np.median(scores), color='green', linestyle='--', label=f'Median: {np.median(scores):.1f}')
            ax1.set_xlabel('Quality Score')
            ax1.set_ylabel('Count')
            ax1.set_title('Quality Score Distribution')
            ax1.legend()
        
        # 2. 各组项目数分布
        ax2 = axes[0, 1]
        group_counts = [g.count for g in groups]
        if group_counts:
            ax2.bar(range(1, len(group_counts)+1), group_counts, color='coral', alpha=0.7)
            avg_count = np.mean(group_counts)
            ax2.axhline(avg_count, color='red', linestyle='--', label=f'Avg: {avg_count:.1f}')
            ax2.set_xlabel('Group ID')
            ax2.set_ylabel('Project Count')
            ax2.set_title('Projects per Group')
            ax2.legend()
        
        # 3. 各组平均质量
        ax3 = axes[1, 0]
        group_means = [g.avg_quality for g in groups]
        if group_means:
            ax3.bar(range(1, len(group_means)+1), group_means, color='mediumseagreen', alpha=0.7)
            avg_quality = np.mean(group_means)
            ax3.axhline(avg_quality, color='red', linestyle='--', label=f'Avg: {avg_quality:.1f}')
            ax3.set_xlabel('Group ID')
            ax3.set_ylabel('Avg Quality')
            ax3.set_title('Average Quality per Group')
            ax3.legend()
        
        # 4. 质量均衡度雷达图
        ax4 = axes[1, 1]
        metrics = ['Quantity\nBalance', 'Quality\nBalance', 'Subject\nPurity', 'Split\nCorrectness']
        values = [
            np.mean(group_counts) / max(group_counts) if max(group_counts) > 0 else 1,  # 简化的数量均衡
            1 - (np.std(group_means) / 100) if group_means else 1,  # 质量均衡
            1 - (len([g for g in groups if '(' in (g.subject_name or '')]) / len(groups)) if groups else 1,  # 学科纯度
            1.0  # 拆分正确率（简化）
        ]
        values = [max(0, min(1, v)) for v in values]  # 限制在0-1之间
        
        x = np.arange(len(metrics))
        bars = ax4.bar(x, values, color=['steelblue', 'coral', 'mediumseagreen', 'gold'], alpha=0.7)
        ax4.set_xticks(x)
        ax4.set_xticklabels(metrics)
        ax4.set_ylim(0, 1.1)
        ax4.set_ylabel('Score (0-1)')
        ax4.set_title('Grouping Quality Metrics')
        
        # 添加数值标签
        for bar, val in zip(bars, values):
            ax4.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.02, 
                    f'{val:.2f}', ha='center', va='bottom', fontsize=9)
        
        plt.tight_layout()
        
        # 保存图片
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"quality_charts_{year}_{timestamp}.png"
        filepath = os.path.join(DEBUG_DIR, filename)
        plt.savefig(filepath, dpi=150, bbox_inches='tight')
        plt.close()
        
        print(f"[Grouping] 已保存质量图表: {filename}")
        
    except Exception as e:
        print(f"[Grouping] 生成图表失败: {e}")


def _calculate_balance_metrics(
    groups: List[ProjectGroup],
    quality_scores: Dict[str, float]
) -> dict:
    """计算分组均衡度指标
    
    Args:
        groups: 分组列表
        quality_scores: 所有项目的质量分数
    
    Returns:
        {
            quantity_balance: 数量均衡度 (0-1),
            quality_balance: 质量均衡度 (0-1),
            subject_purity: 学科纯度 (0-1),
            split_correctness: 拆分正确率 (0-1)
        }
    """
    if not groups:
        return {}
    
    # 1. 数量均衡度
    counts = [g.count for g in groups]
    avg_count = np.mean(counts)
    if avg_count > 0:
        count_deviation = np.mean([abs(c - avg_count) / avg_count for c in counts])
        quantity_balance = max(0, 1 - count_deviation)
    else:
        quantity_balance = 1.0
    
    # 2. 质量均衡度
    group_avgs = [g.avg_quality for g in groups if g.count > 0]
    if group_avgs:
        overall_avg = np.mean(list(quality_scores.values()))
        quality_deviation = np.mean([abs(ga - overall_avg) / overall_avg for ga in group_avgs])
        quality_balance = max(0, 1 - quality_deviation)
    else:
        quality_balance = 1.0
    
    # 3. 学科纯度（每组内同学科项目占比）
    # 简化：检查组名是否包含拆分标记 (1), (2) 等
    pure_groups = 0
    for g in groups:
        # 如果组名不含 (数字) 标记，认为是纯学科组
        if not re.search(r'\(\d+\)$', g.subject_name or ""):
            pure_groups += 1
    subject_purity = pure_groups / len(groups) if groups else 1.0
    
    # 4. 拆分正确率（应拆分的学科是否都拆分了）
    # 检查 >15 项的学科是否被拆分
    # 由于拆分后组名会包含 (1), (2)，这里简化处理
    split_correctness = 1.0  # 简化：假设拆分逻辑正确
    
    return {
        "quantity_balance": round(quantity_balance, 3),
        "quality_balance": round(quality_balance, 3),
        "subject_purity": round(subject_purity, 3),
        "split_correctness": round(split_correctness, 3)
    }


def _load_quality_cache():
    """从文件加载质量分数缓存"""
    global _QUALITY_CACHE
    if os.path.exists(_QUALITY_CACHE_FILE):
        try:
            with open(_QUALITY_CACHE_FILE, 'r', encoding='utf-8') as f:
                _QUALITY_CACHE = json.load(f)
            print(f"[Grouping] 已加载 {len(_QUALITY_CACHE)} 条质量分数缓存")
        except Exception as e:
            print(f"[Grouping] 加载缓存失败: {e}")


def _save_quality_cache():
    """保存质量分数到缓存文件"""
    try:
        with open(_QUALITY_CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(_QUALITY_CACHE, f, ensure_ascii=False, indent=2)
        print(f"[Grouping] 已保存 {len(_QUALITY_CACHE)} 条质量分数到缓存")
    except Exception as e:
        print(f"[Grouping] 保存缓存失败: {e}")


def _save_grouping_result(year: str, result: GroupingResult):
    """保存分组结果到文件"""
    try:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"grouping_{year}_{timestamp}.json"
        filepath = os.path.join(DEBUG_DIR, filename)
        
        # 转换 created_at 为字符串
        created_at = result.created_at
        if hasattr(created_at, 'strftime'):
            created_at = created_at.strftime("%Y-%m-%d %H:%M:%S")
        
        # 转换为可JSON序列化的格式
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
                # 质量分数统计
                "quality_mean": result.statistics.quality_mean,
                "quality_median": result.statistics.quality_median,
                "quality_std": result.statistics.quality_std,
                "quality_min": result.statistics.quality_min,
                "quality_max": result.statistics.quality_max,
                # 分组质量
                "quantity_balance": result.statistics.quantity_balance,
                "quality_balance": result.statistics.quality_balance,
                "subject_purity": result.statistics.subject_purity,
                "split_correctness": result.statistics.split_correctness,
            },
            "groups": []
        }
        
        for g in result.groups:
            group_data = {
                "group_id": g.group_id,
                "subject_code": g.subject_code,
                "subject_name": g.subject_name,
                "count": g.count,
                "avg_quality": g.avg_quality,
                "max_quality": g.max_quality,
                "min_quality": g.min_quality,
                "projects": [
                    {
                        "project_id": p.project_id,
                        "xmmc": p.xmmc,
                        "xmjj": _clean_html_text(p.xmjj) if p.xmjj else "",
                        "quality_score": p.quality_score,
                        "reason": p.reason
                    }
                    for p in g.projects
                ]
            }
            data["groups"].append(group_data)
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        print(f"[Grouping] 已保存分组结果到 {filename}")
        return filename
    except Exception as e:
        print(f"[Grouping] 保存分组结果失败: {e}")
        return None


# 启动时加载缓存
_load_quality_cache()


class GroupingAgent:
    """分组 Agent (重构版)
    
    按学科分组 + 质量评估 + 均衡分配
    """
    
    def __init__(
        self,
        llm: Any = None,
        max_per_group: int = 15,
        quality_weights: List[float] = None,
        concurrency: int = 10
    ):
        """初始化
        
        Args:
            llm: LLM 客户端
            max_per_group: 每组目标项目数 (默认15)
            quality_weights: 质量权重 [创新性, 技术难度, 应用价值]
            concurrency: LLM 并发数
        """
        self.llm = llm or get_default_llm_client()
        self.max_per_group = max_per_group
        self.quality_weights = quality_weights or [1.0, 1.0, 1.0]
        self.concurrency = concurrency
        
        self.quality_assessor = QualityAssessor(self.llm)
        self.project_repo = ProjectRepository()
        self.subject_repo = get_subject_repo()
    
    def _get_subject_level(self, code: str) -> int:
        """判断学科层级
        
        - code 长度=2 → 一级学科
        - code 长度=3 → 二级学科
        - code 长度≥4 → 三级学科
        """
        if not code:
            return 0
        length = len(code)
        if length == 2:
            return 1
        elif length == 3:
            return 2
        elif length >= 4:
            return 3
        return 0
    
    def _get_subject_code(self, ssxk1: Optional[str]) -> str:
        """获取三级学科代码
        
        取 ssxk1 的前4位作为三级学科代码
        """
        if not ssxk1:
            return "unknown"
        code = ssxk1.strip()
        if len(code) >= 4:
            return code[:4]
        elif len(code) >= 2:
            return code[:2]  # 不足4位用2位
        return "unknown"
    
    def _get_subject_name(self, code: str) -> str:
        """获取学科名称
        
        学科编码映射：
        - 项目代码: 4602, 3203 (4位)
        - 数据库代码: 4600000, 3200000 (7位)
        映射规则: 取项目代码前2位 + 补0到7位
        """
        if code == "unknown":
            return "未知学科"
        
        # 转换为数据库格式
        if len(code) >= 2:
            db_code = code[:2] + "00000"  # 4602 -> 4600000
        else:
            db_code = code
        
        try:
            subject = self.subject_repo.get_by_code(db_code)
            if subject and subject.name:
                return subject.name
        except Exception as e:
            print(f"[Grouping] 学科查询失败: {code} -> {db_code}, {e}")
        
        return code
    
    def _group_by_subject(self, projects: List[Project]) -> Dict[str, List[Project]]:
        """按三级学科分组
        
        Returns:
            {subject_code: [Project, ...]}
        """
        subject_groups = defaultdict(list)
        
        for project in projects:
            subject_code = self._get_subject_code(project.ssxk1)
            subject_groups[subject_code].append(project)
        
        return dict(subject_groups)
    
    def _clean_html(self, text: Optional[str]) -> str:
        """清洗 HTML 标签"""
        if not text:
            return ""
        clean = re.sub(r'<[^>]+>', '', text)
        clean = re.sub(r'\s+', ' ', clean)
        return clean.strip()
    
    async def _assess_quality(
        self, 
        projects: List[Project]
    ) -> Dict[str, float]:
        """评估所有项目质量（统一分批 + 真正并发）
        
        把所有项目统一分批，然后并发处理所有批次
        """
        quality_scores = {}
        
        # 过滤已缓存的项目
        uncached = []
        for p in projects:
            if p.id in _QUALITY_CACHE:
                quality_scores[p.id] = _QUALITY_CACHE[p.id]
            else:
                uncached.append(p)
        
        if not uncached:
            return quality_scores
        
        # 统一分批（不按学科）
        batch_size = 10
        all_batches = []
        for i in range(0, len(uncached), batch_size):
            all_batches.append(uncached[i:i+batch_size])
        
        print(f"[Grouping] 共 {len(uncached)} 项目，分 {len(all_batches)} 批，并发 {min(10, len(all_batches))} 批")
        
        # 真正并发：同时处理所有批次
        concurrency = 10
        semaphore = asyncio.Semaphore(concurrency)
        
        async def process_batch(batch: List[Project]):
            async with semaphore:
                try:
                    return await self.quality_assessor.batch_assess(batch)
                except Exception as e:
                    return {p.id: 75.0 for p in batch}
        
        tasks = [process_batch(b) for b in all_batches]
        results = await asyncio.gather(*tasks)
        
        # 合并
        for r in results:
            quality_scores.update(r)
            for pid, score in r.items():
                _QUALITY_CACHE[pid] = score
        
        return quality_scores
    
    def _balanced_distribute(
        self,
        projects: List[Project],
        quality_scores: Dict[str, float],
        target_groups: int = None
    ) -> List[List[Project]]:
        """质量均衡分配算法
        
        目标: 每组数量均衡 + 质量总分均衡
        方法: 贪心分配（先按质量排序，然后轮转分配）
        
        Args:
            projects: 项目列表
            quality_scores: {project_id: score}
            target_groups: 目标分组数（默认根据 max_per_group 计算）
        
        Returns:
            [[Project, ...], ...]
        """
        if not projects:
            return []
        
        # 计算目标组数（尽量均衡）
        if target_groups is None:
            target_groups = max(1, round(len(projects) / self.max_per_group))
        
        # 按质量降序排序
        sorted_projects = sorted(
            projects,
            key=lambda p: quality_scores.get(p.id, 75.0),
            reverse=True
        )
        
        # 初始化分组
        groups = [[] for _ in range(target_groups)]
        group_scores = [0.0] * target_groups
        
        # 贪心分配：总是加入分数最低的组
        for p in sorted_projects:
            min_idx = group_scores.index(min(group_scores))
            groups[min_idx].append(p)
            group_scores[min_idx] += quality_scores.get(p.id, 75.0)
        
        return groups
    
    async def group_projects(
        self,
        request: GroupingRequest
    ) -> GroupingResult:
        """执行项目分组 (重构版)
        
        流程：
        1. 获取项目列表
        2. 按三级学科初步分组
        3. 数量≤15 → 保留原分组
        4. 数量>30 → 质量评估 + 均衡分配
        5. 合并结果
        """
        start_time = time.time()
        
        # 更新参数
        self.max_per_group = request.max_per_group
        
        # 1. 获取项目列表
        limit = request.limit
        projects = self.project_repo.get_projects_by_year(
            year=request.year,
            category=request.category,
            limit=limit
        )
        
        if not projects:
            raise ValueError(f"没有找到 {request.year} 年度的项目")
        
        # 过滤掉没有学科代码的项目
        original_count = len(projects)
        projects = [p for p in projects if p.ssxk1 and p.ssxk1.strip()]
        filtered_count = original_count - len(projects)
        
        print(f"[Grouping] 获取到 {original_count} 个项目，过滤 {filtered_count} 个无学科代码项目")
        
        # 2. 按三级学科初步分组
        subject_groups = self._group_by_subject(projects)
        print(f"[Grouping] 按学科分为 {len(subject_groups)} 个学科组")
        
        # 3. 先对所有项目统一评估质量（只评估一次，并发批量）
        print(f"[Grouping] 开始评估所有项目质量...")
        all_quality_scores = await self._assess_quality(projects)
        print(f"[Grouping] 质量评估完成")
        
        # 4. 处理每个学科
        all_groups = []  # 最终分组
        
        for subject_code, subject_projects in subject_groups.items():
            count = len(subject_projects)
            subject_name = self._get_subject_name(subject_code)
            
            # 获取该学科的质量分数
            subject_quality = {p.id: all_quality_scores.get(p.id, 75.0) for p in subject_projects}
            
            if count > self.max_per_group:
                # 数量>max，需要拆分
                print(f"[Grouping] 学科 {subject_code}({subject_name}) 有 {count} 项，超过 {self.max_per_group}，拆分")
                
                # 计算拆分后的组数（尽量均衡）
                target_groups = max(1, round(count / self.max_per_group))
                
                # 均衡分配
                split_groups = self._balanced_distribute(subject_projects, subject_quality, target_groups)
                
                for i, group in enumerate(split_groups):
                    all_groups.append({
                        "subject_code": f"{subject_code}_{i+1}",
                        "subject_name": f"{subject_name}({i+1})",
                        "projects": group,
                        "need_split": True
                    })
            else:
                # 数量≤max，直接保留
                all_groups.append({
                    "subject_code": subject_code,
                    "subject_name": subject_name,
                    "projects": subject_projects,
                    "need_split": False
                })
        
        # 4. 构建结果
        result_groups = []
        group_id = 1
        
        for g in all_groups:
            projects_in_group = g["projects"]
            
            # 计算质量分数
            scores = []
            for p in projects_in_group:
                score = _QUALITY_CACHE.get(p.id, 75.0)
                scores.append(score)
            
            # 构建 ProjectInGroup
            project_items = [
                ProjectInGroup(
                    project_id=p.id,
                    xmmc=p.xmmc,
                    xmjj=p.xmjj or "",
                    quality_score=_QUALITY_CACHE.get(p.id, 75.0),
                    reason=f"学科: {g['subject_name']}"
                )
                for p in projects_in_group
            ]
            
            # 统计信息
            avg_score = np.mean(scores) if scores else 0
            max_score = max(scores) if scores else 0
            min_score = min(scores) if scores else 0
            
            result_groups.append(
                ProjectGroup(
                    group_id=group_id,
                    subject_code=g["subject_code"],
                    subject_name=g["subject_name"],
                    projects=project_items,
                    count=len(projects_in_group),
                    avg_quality=round(avg_score, 2),
                    max_quality=round(max_score, 2),
                    min_quality=round(min_score, 2)
                )
            )
            group_id += 1
        
        # 5. 统计信息
        total_projects = len(projects)
        total_groups = len(result_groups)
        
        # 计算质量分数统计
        quality_stats = _calculate_quality_stats(_QUALITY_CACHE)
        balance_metrics = _calculate_balance_metrics(result_groups, _QUALITY_CACHE)
        
        # 综合均衡分数
        balance_score = (
            balance_metrics.get("quantity_balance", 0.85) * 0.3 +
            balance_metrics.get("quality_balance", 0.85) * 0.4 +
            balance_metrics.get("subject_purity", 0.85) * 0.3
        )
        
        stats = GroupingStatistics(
            total_projects=total_projects,
            group_count=total_groups,
            balance_score=round(balance_score, 3),
            avg_projects_per_group=round(total_projects / total_groups, 2) if total_groups else 0,
            avg_quality_per_group=round(np.mean([g.avg_quality for g in result_groups]), 2) if result_groups else 0,
            # 质量分数统计
            quality_mean=quality_stats.get("mean"),
            quality_median=quality_stats.get("median"),
            quality_std=quality_stats.get("std"),
            quality_min=quality_stats.get("min"),
            quality_max=quality_stats.get("max"),
            # 分组质量
            quantity_balance=balance_metrics.get("quantity_balance"),
            quality_balance=balance_metrics.get("quality_balance"),
            subject_purity=balance_metrics.get("subject_purity"),
            split_correctness=balance_metrics.get("split_correctness")
        )
        
        result = GroupingResult(
            id=str(uuid.uuid4()),
            year=request.year,
            groups=result_groups,
            statistics=stats,
            created_at=time.strftime("%Y-%m-%d %H:%M:%S")
        )
        
        # 保存分组结果到文件
        _save_grouping_result(request.year, result)
        
        # 生成质量统计图表
        _generate_quality_charts(_QUALITY_CACHE, result_groups, request.year)
        
        # 保存质量分数缓存
        _save_quality_cache()
        
        elapsed = time.time() - start_time
        print(f"[Grouping] 完成，用时 {elapsed:.2f}秒，分组 {total_groups} 个")
        
        return result
