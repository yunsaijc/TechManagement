# 📋 分组子服务设计

## 概述

分组子服务是智能分组与专家匹配服务的核心组件之一，负责将申报项目按学科分类，并对超出 `max_per_group` 项的学科进行质量均衡分配，同时合并项目过少的学科组。

---

## 核心逻辑

### 分组策略

```
1. 按学科代码分组（使用 ssxk1 字段，优先7位， fallback 到5位/3位/2位）
2. 数量 > max_per_group(15) → 质量评估 + 均衡分配（拆分）
3. 数量 < min_per_group(5) → 尝试与同一级学科(前3位)合并
4. 输出最终分组结果
```

### 拆分逻辑 (Split)

当某学科项目数超过 `max_per_group`（默认15）时：

1. **质量评估**: 使用 LLM 评估每个项目的质量分数
2. **贪心分配**: 将项目按质量排序，轮转分配到各组
3. **拆分标记**: 拆分后的组名添加 `(1)(2)` 后缀

```
例如: "材料科学与工程(1)", "材料科学与工程(2)"
```

### 合并逻辑 (Merge)

当某学科项目数少于 `min_per_group`（默认5）时：

1. **查找同源组**: 寻找与该组前3位（一级学科）相同的其他小组
2. **合并条件**: 目标组也小于 `min_per_group` 才合并
3. **不跨学科**: 前3位不同的组不合并，即使项目很少

```
例如: 
- 6303550(2项) + 6303551(3项) → 合并（同为630）
- 6303550(2项) + 460(5项) → 不合并（630 ≠ 460）
```

### 学科代码优先级

使用完整的 ssxk1 代码进行分组：

| 长度 | 示例 | 层级 |
|------|------|------|
| 7位 | 6303550 | 三级学科 |
| 5位 | 63035 | 二级学科 |
| 3位 | 630 | 一级学科 |
| <3位 | 63 | 一级学科(短码) |

名称查找时支持逐级 fallback：
```
6303550 → 精确匹配 → "科技管理学"
6303551 → 精确匹配失败 → 尝试前缀 63035 → 失败 → 尝试 630 → 成功 → "管理科学与工程"
```

---

## 业务流程

```
┌─────────────────────────────────────────────────────────────────┐
│                        分组子服务流程                              │
└─────────────────────────────────────────────────────────────────┘

     输入: year, limit
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
│  3. 按学科代码分组  │
│  (7位→5位→3位)       │
└──────┬──────────────┘
         │
    ┌────┴────┐
    │         │
    ▼         ▼
┌────────┐ ┌────────┐
│ >15项  │ │ ≤15项  │
│ 拆分   │ │ 保留   │
└───┬────┘ └───┬────┘
    │          │
    ▼          ▼
┌──────────┐  ┌──────────┐
│ 质量评估 │  │ 检查<5项 │
│+均衡分配 │  │ 同学科合并│
└────┬─────┘  └────┬─────┘
     │             │
     └──────┬──────┘
            ▼
┌─────────────────────┐
│  4. 合并分组结果   │
│     + 质量统计      │
└──────┬──────────────┘
            │
            ▼
        输出: 分组结果
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

对数量 > `max_per_group` (15) 的学科，评估每个项目的质量。

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

### 2.X 质量评估可靠性验证

为确保 LLM 评分的可靠性，采用双重验证机制：
1. **双重评估**：自动一致性检验
2. **抽样人工验证**：外部专家基准对比

#### 2.X.1 双重评估

**原理**：同一项目用两个独立 prompt 评估，比较结果差异

| 组件 | 说明 |
|------|------|
| Prompt A | 原始评估 prompt |
| Prompt B | 措辞略有差异的复本 |
| 阈值 | 差异 > 15 分视为不稳定 |

**处理逻辑**：
- Δ ≤ 15：评分稳定，取两者的平均值
- Δ > 15：标记"待人工复核"，记录差异

#### 2.X.2 抽样人工验证

**触发条件**：每累计评估 50 个项目，随机抽取 5 个

**人工验证指标**：

| 指标 | 合格标准 | 行动 |
|------|---------|------|
| Spearman ρ | ≥ 0.7 | 继续使用 |
| MAE | ≤ 10 | 继续使用 |
| 一致率 | ≥ 80% | 继续使用 |
| 上述任一不达标 | - | 调整评估 prompt |

#### 2.X.3 验证流程

```
评估任务 → 双重评估 → 差异检查 → 结果入库
                │              │
                │         每50个触发
                │              │
                ▼              ▼
           稳定项目       抽样人工验证
                │              │
                │         计算相关系数
                │              │
                ▼              ▼
              继续          达标？
                           是/否 → 调整prompt
```

#### 2.X.4 配置参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `dual_eval_threshold` | 15 | 双重评估差异阈值 |
| `use_mean_on_stable` | True | 稳定时取平均分 |
| `sample_size` | 15 | 抽样数量 |
| `sample_frequency` | 50 | 每多少项目抽一次 |
| `min_spearman_rho` | 0.7 | 相关系数最低要求 |
| `max_mae` | 10 | 平均绝对误差上限 |
| `min_consistency_rate` | 0.8 | 一致率最低要求 |

### 3. 均衡分配 (Balanced Distribution)

对数量 > `max_per_group` (15) 的学科，使用贪心算法进行均衡分配。

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
| `max_per_group` | 15 | 每组最大项目数，超过则拆分 |
| `min_per_group` | 5 | 每组最小项目数，少于此值尝试合并 |
| `split_threshold` | 15 | 超过此数量则拆分该学科（与 max_per_group 相同） |
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

### GroupingAgent

```python
class GroupingAgent:
    """分组 Agent"""
    
    def __init__(
        self,
        llm=None,
        max_per_group: int = 15,
        min_per_group: int = 5,
        quality_weights: List[float] = None,
        concurrency: int = 10
    ):
        self.llm = llm or get_default_llm_client()
        self.max_per_group = max_per_group  # 每组最大项目数
        self.min_per_group = min_per_group  # 每组最小项目数
        self.quality_weights = quality_weights or [1.0, 1.0, 1.0]
        self.concurrency = concurrency
    
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
            if len(subject_projects) <= self.max_per_group:
                # 数量≤max_per_group，直接保留
                final_groups.append(subject_projects)
            else:
                # 数量>max_per_group，质量均衡分配
                # 2.1 评估质量
                quality_scores = await self._assess_quality(subject_projects)
                # 2.2 均衡分配
                split_groups = self._balanced_distribute(
                    subject_projects, 
                    quality_scores,
                    len(subject_projects) // self.max_per_group + 1
                )
                final_groups.extend(split_groups)
        
        # 2.5 合并小组（< min_per_group）
        final_groups = self._merge_small_groups(final_groups, self.min_per_group)
        
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
