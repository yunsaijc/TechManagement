# 👥 专家匹配子服务设计

## 概述

专家匹配子服务是智能分组与专家匹配服务的核心组件之一，负责为每个分组匹配最合适的评审专家，实现全局最优匹配。

## 功能说明

1. **专家画像构建**：从研究领域、论文、擅长专业提取专家研究方向
2. **项目-专家匹配度计算**：基于向量相似度计算匹配度
3. **全局最优匹配**：以组为单元的整体优化匹配
4. **关系回避检测**：自动检测并回避师生、历史合作等关系

---

## 业务流程

```
┌─────────────────────────────────────────────────────────────────┐
│                      专家匹配子服务流程                            │
└─────────────────────────────────────────────────────────────────┘

     输入: 项目列表 + 专家库
         │
         ▼
┌─────────────────────┐
│   1. 数据预处理     │
│   - 专家数据加载    │
│   - 文本融合        │
└──────┬──────────────┘
         │
         ▼
┌─────────────────────┐
│   2. 专家画像构建   │
│   (LLM)             │
│   - 研究方向提取    │
│   - 领域标签提取    │
└──────┬──────────────┘
         │
         ▼
┌─────────────────────┐
│   3. 专家向量化     │
│   (Embedding)      │
└──────┬──────────────┘
         │
         ▼
┌─────────────────────┐
│   4. 匹配度计算     │
│   - 向量相似度      │
│   - 学科匹配        │
│   - 历史相关性      │
└──────┬──────────────┘
         │
         ▼
┌─────────────────────┐
│   5. 全局最优匹配   │
│   (约束优化)        │
│   - 匈牙利算法      │
│   - 约束满足        │
└──────┬──────────────┘
         │
         ▼
┌─────────────────────┐
│   6. 关系回避检测   │
│   - 师生关系        │
│   - 历史合作        │
│   - 单位回避        │
└──────┬──────────────┘
         │
         ▼
     输出: 匹配结果
```

---

## 核心模块

### 1. 专家画像构建 (Profiler)

负责使用 LLM 分析专家信息，构建专家画像。

#### 输入

```python
# 专家原始数据
{
    "XM": "张教授",
    "SXXK1": "1502040",
    "SXZY": "有机化学,药物化学",
    "YJLY": "主要从事有机合成方法学、金属催化反应、药物分子设计合成研究...",
    "LWLZ": "在JACS、Angew等期刊发表论文80余篇，承担国家自然科学基金重点项目...",
    "GZDW": "北京大学化学与分子工程学院"
}
```

#### 处理流程

1. **文本融合**：拼接擅长专业 + 研究领域 + 论文论著
2. **LLM 分析**：提取研究方向、领域专长

#### LLM Prompt 示例

```
请分析以下专家信息，构建专家画像：

姓名：张教授
擅长专业：有机化学,药物化学
研究领域：主要从事有机合成方法学、金属催化反应、药物分子设计合成研究...
论文论著：在JACS、Angew等期刊发表论文80余篇，承担国家自然科学基金重点项目...

请提取：
1. 主要研究方向（如：有机合成、药物化学、金属催化等）
2. 细分领域专长（如：不对称合成、药物设计等）
3. 技术专长（如：有机合成、实验设计等）
```

#### 输出

```python
{
    "main_research_area": "有机化学",
    "sub_research_fields": ["有机合成", "药物化学", "金属催化"],
    "tech_expertise": ["有机合成", "实验设计", "催化剂开发"],
    "keywords": ["有机合成", "药物化学", "金属催化", "不对称合成"]
}
```

### 2. 匹配度计算 (Scorer)

计算项目与专家之间的匹配度。

#### 匹配维度

| 维度 | 权重 | 说明 |
|------|------|------|
| 研究方向匹配 | 50% | 专家研究方向与项目内容的一致性 |
| 学科匹配 | 30% | 专家熟悉学科与项目学科的匹配度 |
| 历史相关性 | 20% | 专家历史评审相似项目的经验 |

#### 计算流程

```python
def calculate_match_score(
    project: Project,
    expert: Expert,
    project_vector: np.ndarray,
    expert_vector: np.ndarray
) -> float:
    """计算项目-专家匹配度
    
    Args:
        project: 项目
        expert: 专家
        project_vector: 项目向量
        expert_vector: 专家向量
    
    Returns:
        匹配度分数 (0-100)
    """
    # 1. 向量相似度 (50%)
    vector_similarity = cosine_similarity(project_vector, expert_vector)
    
    # 2. 学科匹配 (30%)
    subject_match = calculate_subject_match(
        project.ssxg1, expert.sxxk1, expert.sxxk2
    )
    
    # 3. 历史评审经验 (20%)
    history_score = calculate_history_score(
        expert.zjno, project.ssxz1
    )
    
    # 加权计算
    score = (
        vector_similarity * 0.5 +
        subject_match * 0.3 +
        history_score * 0.2
    )
    
    return score
```

### 3. 全局最优匹配 (Optimizer)

使用约束优化算法实现全局最优匹配。

#### 目标函数

```
最大化: Σ(匹配度 × 分配标志)

约束条件:
1. 每项目分配 N 个专家 (N=5)
2. 每组 ≥ M 个懂行专家 (M=10)
3. 每位专家评审项目数 ≤ 上限
4. 回避关系专家不能分配
```

#### 匹配算法

| 阶段 | 算法 | 说明 |
|------|------|------|
| 初筛 | 规则过滤 | 排除必须回避的专家 |
| 打分 | 向量相似度 | 计算所有项目-专家匹配度 |
| 分配 | 匈牙利算法 | 最优指派问题求解 |
| 调优 | 贪心 + 模拟退火 | 局部优化 |

#### 算法流程

```python
def optimize_matching(
    projects: List[Project],
    experts: List[Expert],
    match_scores: np.ndarray,
    constraints: MatchingConstraints
) -> MatchingResult:
    """全局最优匹配
    
    Args:
        projects: 项目列表
        experts: 专家列表
        match_scores: 匹配度矩阵 (projects × experts)
        constraints: 约束条件
    
    Returns:
        匹配结果
    """
    # 1. 初筛 - 排除回避专家
    valid_experts = filter_avoidance(projects, experts)
    
    # 2. 构建指派问题矩阵
    # 每个项目需要分配 N 个专家
    
    # 3. 匈牙利算法求解
    assignments = hungarian_algorithm(match_scores)
    
    # 4. 约束满足调整
    assignments = satisfy_constraints(assignments, constraints)
    
    # 5. 生成结果
    return MatchingResult(assignments=assignments)
```

### 4. 关系回避 (Avoidance)

检测并回避可能影响评审公平性的关系。

#### 回避类型

| 类型 | 检测方法 | 处理方式 |
|------|----------|----------|
| 师生关系 | 专家毕业院校 = 项目负责人学位获取单位 | 排除 |
| 历史合作 | 专家与项目负责人共同署名论文/项目 | 排除 |
| 同一单位 | 专家单位 = 项目完成单位 | 警告，可保留 |
| 竞争关系 | 专家所在单位与项目单位有利益冲突 | 排除 |

#### 检测实现

```python
class AvoidanceChecker:
    """关系回避检测器"""
    
    def check_teacher_student(
        self,
        expert: Expert,
        project: Project
    ) -> AvoidanceResult:
        """检测师生关系
        
        Args:
            expert: 专家
            project: 项目
        
        Returns:
            回避结果
        """
        # 获取专家毕业院校
        expert_schools = self._get_expert_schools(expert)
        
        # 获取项目负责人学位获取单位
        project_schools = self._get_project_schools(project)
        
        # 检测重叠
        overlap = set(expert_schools) & set(project_schools)
        
        if overlap:
            return AvoidanceResult(
                avoided=True,
                reason=f"师生关系：共同院校 {overlap}",
                severity="high"
            )
        
        return AvoidanceResult(avoided=False)
    
    def check_history_cooperation(
        self,
        expert: Expert,
        project: Project
    ) -> AvoidanceResult:
        """检测历史合作关系"""
        # 检查论文共同署名
        # 检查项目共同承担
        pass
    
    def check_same_unit(
        self,
        expert: Expert,
        project: Project
    ) -> AvoidanceResult:
        """检测同一单位"""
        if expert.gzdw == project.cddw_mc:
            return AvoidanceResult(
                avoided=False,  # 不排除，但标记
                reason=f"同一单位：{expert.gzdw}",
                severity="low"
            )
        return AvoidanceResult(avoided=False)
```

---

## 核心代码结构

### MatchingAgent

```python
class MatchingAgent:
    """匹配 Agent，负责协调各组件完成专家匹配"""
    
    def __init__(
        self,
        llm: Any = None,
        embedder: Any = None
    ):
        self.llm = llm or get_default_llm_client()
        self.embedder = embedder or get_default_embedder()
        self.profiler = ExpertProfiler(self.llm)
        self.scorer = MatchScorer(self.embedder)
        self.optimizer = MatchingOptimizer()
        self.avoidance = AvoidanceChecker()
    
    async def match_experts(
        self,
        projects: List[Project],
        experts: List[Expert],
        group_id: int,
        experts_per_project: int = 5,
        min_experts_per_group: int = 10,
        avoid_relations: bool = True,
        max_reviews_per_expert: int = 5
    ) -> MatchingResult:
        """执行专家匹配
        
        Args:
            projects: 项目列表
            experts: 专家列表
            group_id: 分组ID
            experts_per_project: 每个项目分配的专家数
            min_experts_per_group: 每组最少懂行专家数
            avoid_relations: 是否回避关系
            max_reviews_per_expert: 每位专家最大评审数
        
        Returns:
            匹配结果
        """
        # 1. 专家画像构建
        profiles = await self.profiler.profile_experts(experts)
        
        # 2. 专家向量化
        expert_vectors = self.embedder.embed([
            p.text for p in profiles
        ])
        
        # 3. 项目向量化
        project_vectors = self.embedder.embed([
            p.content for p in projects
        ])
        
        # 4. 计算匹配度矩阵
        match_scores = self.scorer.calculate_matrix(
            project_vectors, expert_vectors
        )
        
        # 5. 关系回避过滤
        if avoid_relations:
            match_scores = self.avoidance.filter_scores(
                projects, experts, match_scores
            )
        
        # 6. 全局最优匹配
        constraints = MatchingConstraints(
            experts_per_project=experts_per_project,
            min_experts_per_group=min_experts_per_group,
            max_reviews_per_expert=max_reviews_per_expert
        )
        assignments = self.optimizer.optimize(
            projects, experts, match_scores, constraints
        )
        
        # 7. 生成结果
        return MatchingResult(
            group_id=group_id,
            assignments=assignments,
            statistics=calculate_statistics(assignments)
        )
```

---

## 匹配策略

### 1. 匹配优先 vs 回避优先

| 策略 | 说明 | 适用场景 |
|------|------|----------|
| match_first | 优先保证匹配度，回避作为后置过滤 | 匹配度优先 |
| avoid_first | 优先排除回避关系，再选最优 | 回避优先 |

### 2. 局部最优 vs 全局最优

| 策略 | 说明 | 适用场景 |
|------|------|----------|
| greedy | 贪心匹配，速度快 | 项目少 |
| global | 全局优化，结果最优 | 项目多 |

---

## 扩展性设计

### 新增回避规则

```
1. 在 matching/avoidance/ 下创建新规则类
2. 继承 BaseAvoidance
3. 实现 check() 方法
4. 在 AvoidanceChecker 中注册
```

### 新增匹配算法

```
1. 在 matching/optimizer/ 下创建新算法类
2. 继承 BaseOptimizer
3. 实现 optimize() 方法
4. 在 MatchingAgent 中注册
```

---

## 相关文档

- [服务概述 →](01-overview.md)
- [分组子服务 →](02-grouping.md)
- [数据模型 →](04-models.md)
- [API 接口 →](05-api.md)
