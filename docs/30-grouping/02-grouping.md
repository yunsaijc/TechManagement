# 📋 分组子服务设计

## 概述

分组子服务是智能分组与专家匹配服务的核心组件之一，负责将申报项目按学科分类，并对超出30项的学科进行质量均衡分配，实现组内数量与质量的双均衡。

---

## 核心逻辑（重构后）

### 原有方案问题

| 问题 | 原因 |
|------|------|
| 语义聚类 ≠ 学科分组 | Embedding 只保证语义相近，不保证学科一致 |
| 质量不均衡 | 聚类只保证语义相似，不保证质量分布 |

### 新方案：按学科分组 + 质量均衡分配

```
1. 按三级学科初步分组（利用 ssxk1 字段）
2. 数量 ≤30 → 直接保留
3. 数量 >30 → 进入质量均衡分配流程
   3.1 LLM 评估每个项目质量（创新性/技术难度/应用价值）
   3.2 贪心算法分配，保证组间质量均衡
4. 合并结果，输出 15 个分组
```

---

## 业务流程

```
┌─────────────────────────────────────────────────────────────────┐
│                        分组子服务流程                              │
└─────────────────────────────────────────────────────────────────┘

     输入: year, target_groups=15
         │
         ▼
┌─────────────────────┐
│  1. 获取项目列表     │
│     + 学科代码       │
└──────┬──────────────┘
         │
         ▼
┌─────────────────────┐
│  2. 查询学科层级    │
│  sys_xkfl 表        │
└──────┬──────────────┘
         │
         ▼
┌─────────────────────┐
│  3. 按三级学科分组  │
└──────┬──────────────┘
         │
         ▼
    ┌────┴────┐
    │         │
    ▼         ▼
┌────────┐ ┌────────┐
│ ≤30项  │ │ >30项  │
│ 保留   │ │ 质量评估│
│ 原分组 │ │ +均衡分配│
└────────┘ └────┬────┘
                 │
                 ▼
┌─────────────────────┐
│  4. 合并分组结果   │
│     + 质量统计      │
└──────┬──────────────┘
                 │
                 ▼
             输出: 15个分组
```

---

## 核心模块

### 1. 学科分组 (Subject Grouping)

#### 1.1 学科层级判断

```python
def get_subject_level(code: str) -> int:
    """判断学科层级
    
    - code 长度=2 → 一级学科 (如 01, 02, 03)
    - code 长度=3 → 二级学科 (如 010, 011)
    - code 长度≥4 → 三级学科 (如 0101, 0102)
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
```

#### 1.2 按三级学科分组

```python
def group_by_subject(projects: List[Project]) -> Dict[str, List[Project]]:
    """按三级学科代码分组
    
    Returns:
        {
            "0101": [Project, Project, ...],  # 计算机软件与理论
            "0201": [Project, ...],           # 理论物理
            ...
        }
    """
    subject_groups = defaultdict(list)
    
    for project in projects:
        # 取三级学科代码（前4位）
        if project.ssxk1 and len(project.ssxk1) >= 4:
            subject_code = project.ssxk1[:4]
        else:
            subject_code = "unknown"
        
        subject_groups[subject_code].append(project)
    
    return dict(subject_groups)
```

### 2. 质量评估 (Quality Assessment)

对数量 >30 的学科，评估每个项目的质量。

#### 2.1 评估维度

| 维度 | 权重 | 说明 |
|------|------|------|
| 创新性 | 33.3% | 技术的原创性、领先程度 |
| 技术难度 | 33.3% | 技术的复杂程度、实现难度 |
| 应用价值 | 33.3% | 推广应用前景，经济效益 |

#### 2.2 LLM 评估 Prompt

```python
def build_quality_prompt(project: Project) -> str:
    """构建质量评估 prompt"""
    # 清洗 HTML
    clean_xmjj = clean_html(project.xmjj)[:1000]
    
    return f"""
项目名称: {project.xmmc}
关键词: {project.gjc or '无'}
项目简介: {clean_xmjj}

请从以下三个维度评估该项目质量（每个维度0-100分）：
1. 创新性: 项目的创新程度
2. 技术难度: 技术实现的复杂程度  
3. 应用价值: 实际应用和推广价值

请返回JSON格式：
{{"innovation": 85, "difficulty": 70, "value": 90, "comment": "简要评语"}}
"""
```

#### 2.3 并发评估

```python
async def assess_all_quality(
    projects: List[Project], 
    concurrency: int = 10
) -> Dict[str, ProjectQuality]:
    """并发评估所有项目质量
    
    Args:
        projects: 项目列表
        concurrency: 并发数
    
    Returns:
        {project_id: ProjectQuality}
    """
    semaphore = asyncio.Semaphore(concurrency)
    
    async def assess_with_limit(p: Project):
        async with semaphore:
            return p.id, await llm_assess(p)
    
    tasks = [assess_with_limit(p) for p in projects]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    return {
        pid: quality 
        for pid, quality in results 
        if not isinstance(quality, Exception)
    }
```

### 3. 均衡分配 (Balanced Distribution)

对数量 >30 的学科，使用贪心算法进行均衡分配。

#### 3.1 算法逻辑

```python
def balanced_distribute(
    projects: List[Project],
    quality_scores: Dict[str, ProjectQuality],
    max_per_group: int = 15
) -> List[List[Project]]:
    """质量均衡分配算法
    
    目标: 每组数量均衡 + 质量总分均衡
    方法: 贪心分配（先按质量排序，然后轮转分配）
    
    Args:
        projects: 项目列表
        quality_scores: 质量分数 {project_id: ProjectQuality}
        max_per_group: 每组目标项目数 (默认15)
    
    Returns:
        分组结果 [[Project, ...], [Project, ...], ...]
    """
    # 计算需要的组数
    target_groups = max(1, (len(projects) + max_per_group - 1) // max_per_group)
    sorted_projects = sorted(
        projects, 
        key=lambda p: quality_scores.get(p.id, ProjectQuality()).total_score,
        reverse=True
    )
    
    # 2. 初始化分组
    groups = [[] for _ in range(target_groups)]
    group_scores = [0.0] * target_groups
    
    # 3. 贪心分配：总是加入分数最低的组
    for p in sorted_projects:
        min_idx = group_scores.index(min(group_scores))
        groups[min_idx].append(p)
        group_scores[min_idx] += quality_scores.get(p.id, ProjectQuality()).total_score
    
    return groups
```

#### 3.2 均衡约束

| 约束 | 容忍度 |
|------|--------|
| 数量差异 | ≤ 3 项 |
| 质量差异 | ≤ 10% |

#### 3.3 均衡性检查

```python
def check_balance(groups: List[List[Project]], quality_scores: Dict) -> bool:
    """检查分组是否满足均衡约束"""
    sizes = [len(g) for g in groups]
    scores = [sum(quality_scores[p.id].total_score for p in g) for g in groups]
    
    # 数量差异检查
    if max(sizes) - min(sizes) > 3:
        return False
    
    # 质量差异检查 (10%)
    avg_score = sum(scores) / len(scores)
    for s in scores:
        if abs(s - avg_score) / avg_score > 0.1:
            return False
    
    return True
```

---

## 参数配置

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `max_per_group` | 15 | 每组目标项目数 |
| `split_threshold` | 30 | 超过此数量则拆分该学科 |
| `quality_weights` | 1:1:1 | 创新性:技术难度:应用价值 |
| `quantity_tolerance` | 3 | 数量差异容忍 |
| `quality_tolerance` | 0.1 | 质量差异容忍 (10%) |
| `llm_concurrency` | 10 | LLM 并发数 |

---

## 性能优化

### 5000+ 项目处理预估

| 步骤 | 时间 |
|------|------|
| 获取项目 + 学科 | ~5秒 |
| 学科分组统计 | ~1秒 |
| 质量评估 (LLM并发10) | ~10分钟 (5000项目) |
| 均衡分配算法 | ~1秒 |
| **总计** | **~10分钟** |

### 优化策略

1. **质量分数缓存**: 评估过的项目结果缓存，避免重复评估
2. **LLM 并发**: 控制并发数，避免 API 限流
3. **超时处理**: 单项目评估超时跳过，使用默认分

---

## 核心代码结构

### GroupingAgent (重构后)

```python
class GroupingAgent:
    """分组 Agent"""
    
    def __init__(self, llm=None):
        self.llm = llm or get_default_llm_client()
        self.quality_cache = {}  # 质量分数缓存
    
    async def group_projects(
        self,
        projects: List[Project],
        target_groups: int = 15
    ) -> GroupingResult:
        """执行项目分组"""
        
        # 1. 按三级学科初步分组
        subject_groups = self._group_by_subject(projects)
        
        # 2. 处理每个学科
        final_groups = []
        
        for subject_code, subject_projects in subject_groups.items():
            if len(subject_projects) <= 30:
                # 数量≤30，直接保留
                final_groups.append(subject_projects)
            else:
                # 数量>30，质量均衡分配
                # 2.1 评估质量
                quality_scores = await self._assess_quality(subject_projects)
                # 2.2 均衡分配
                split_groups = self._balanced_distribute(
                    subject_projects, 
                    quality_scores,
                    len(subject_projects) // 30 + 1
                )
                final_groups.extend(split_groups)
        
        # 3. 合并并返回结果
        return self._merge_groups(final_groups, target_groups)
```

---

## 输出结果

### 分组结果示例

```json
{
  "groups": [
    {
      "group_id": 1,
      "subject_code": "0101",
      "subject_name": "计算机软件与理论",
      "projects": [
        {"id": "p1", "xmmc": "项目A", "quality_score": 85.0},
        {"id": "p2", "xmmc": "项目B", "quality_score": 78.3}
      ],
      "statistics": {
        "count": 28,
        "avg_quality": 81.5,
        "max_quality": 95.0,
        "min_quality": 65.0
      }
    }
  ],
  "statistics": {
    "total_groups": 15,
    "total_projects": 5000,
    "avg_projects_per_group": 333.3,
    "avg_quality_per_group": 75.0
  }
}
```

---

## 相关文档

- [服务概述 →](01-overview.md)
- [专家匹配子服务 →](03-matching.md)
- [数据模型 →](04-models.md)
- [API 接口 →](05-api.md)
