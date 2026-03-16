# 📋 分组子服务设计

## 概述

分组子服务是智能分组与专家匹配服务的核心组件之一，负责将申报项目智能地分配到不同的评审组，实现组内数量与质量的双均衡。

## 功能说明

1. **项目内容分析**：使用 LLM 提取项目的核心创新点、技术方向、研究领域
2. **智能分组计算**：根据项目数量自动计算最优分组数
3. **质量评估**：评估每个项目的创新性、技术难度、应用价值
4. **分组优化**：确保各组数量均衡、质量均衡、主题相关

---

## 业务流程

```
┌─────────────────────────────────────────────────────────────────┐
│                        分组子服务流程                              │
└─────────────────────────────────────────────────────────────────┘

     输入: 项目列表 (含 xmjj, gjc, ssxk)
         │
         ▼
┌─────────────────────┐
│   1. 数据预处理      │
│   - 清洗 HTML 标签  │
│   - 提取纯文本      │
│   - 字段拼接        │
└──────┬──────────────┘
         │
         ▼
┌─────────────────────┐
│   2. 项目内容分析    │
│   (LLM)             │
│   - 提取创新点      │
│   - 提取技术方向    │
│   - 提取研究领域    │
└──────┬──────────────┘
         │
         ▼
┌─────────────────────┐
│   3. 项目向量化      │
│   (Embedding)       │
│   - 文本向量化      │
│   - 向量存储        │
└──────┬──────────────┘
         │
         ▼
    ┌────┴────┐
    │         │
    ▼         ▼
┌────────┐ ┌────────┐
│4a.聚类 │ │4b.质量│
│分组   │ │评估   │
└───┬────┘ └───┬────┘
    │         │
    └────┬────┘
         │
         ▼
┌─────────────────────┐
│   5. 分组优化       │
│   - 数量均衡        │
│   - 质量均衡        │
│   - 学科内聚        │
└──────┬──────────────┘
         │
         ▼
     输出: 分组结果
```

---

## 核心模块

### 1. 项目内容分析 (Analyzer)

负责使用 LLM 分析项目内容，提取关键信息。

#### 输入

```python
# 项目原始数据
{
    "xmmc": "基于多尺度分析的智能电网故障预测系统",
    "gjc": "智能电网,故障预测,机器学习",
    "xmjj": "<p>本项目拟开展基于多尺度分析的智能电网故障预测研究...</p>",
    "ssxk1": "4704017"
}
```

#### 处理流程

1. **HTML 清洗**：去除富文本标签，提取纯文本
2. **内容融合**：拼接项目名称 + 关键词 + 简介
3. **LLM 分析**：提取创新点、技术方向、研究领域

#### LLM Prompt 示例

```
请分析以下项目内容，提取关键信息：

项目名称：{xmmc}
关键词：{gjc}
项目简介：{xmjj}

请提取：
1. 核心创新点（100字以内）
2. 技术方向（如：人工智能、电力系统、自动化等）
3. 研究领域（如：故障预测、智能电网、数据挖掘等）
4. 应用场景（如：电力系统、工业物联网等）
```

#### 输出

```python
{
    "innovation": "提出基于多尺度时空特征融合的故障预测方法",
    "tech_direction": "人工智能,电力系统",
    "research_field": "故障预测,智能电网",
    "application": "电力系统,智能电网"
}
```

### 2. 聚类分组 (Cluster)

基于项目内容向量进行智能聚类。

#### 算法选择

| 算法 | 适用场景 | 优点 |
|------|----------|------|
| K-means | 项目数量大，主题分散 | 速度快，效果稳定 |
| 层次聚类 | 项目数量中等，需要层次结构 | 可解释性强 |
| DBSCAN | 项目密度不均 | 可发现异常项目 |

#### 自动分组数计算

```python
def calculate_optimal_groups(project_count: int, max_per_group: int = 30) -> int:
    """自动计算最优分组数
    
    Args:
        project_count: 项目总数
        max_per_group: 每组最大项目数
    
    Returns:
        最优分组数
    """
    # 基础分组数
    base_groups = ceil(project_count / max_per_group)
    
    # 根据项目总数调整
    if project_count < 50:
        return max(2, base_groups)
    elif project_count < 100:
        return max(3, base_groups)
    elif project_count < 200:
        return max(4, base_groups)
    else:
        return max(5, min(10, base_groups))
```

### 3. 质量评估 (Quality Assessment)

使用 LLM 评估每个项目的质量分数。

#### 评估维度

| 维度 | 权重 | 说明 |
|------|------|------|
| 创新性 | 40% | 技术的原创性、领先程度 |
| 技术难度 | 30% | 技术的复杂程度、实现难度 |
| 应用价值 | 30% | 推广应用前景、经济效益 |

#### LLM 评估 Prompt

```
请评估以下项目的质量分数（0-100分）：

项目名称：{xmmc}
项目简介：{xmjj}

评估维度：
1. 创新性（40%）：技术是否具有原创性，是否处于领先水平
2. 技术难度（30%）：技术实现是否复杂，难度高低
3. 应用价值（30%）：推广应用前景如何，经济效益如何

请给出：
- 创新性得分：XX分
- 技术难度得分：XX分  
- 应用价值得分：XX分
- 综合得分：XX分
- 简要评语：XX
```

### 4. 分组优化 (Optimizer)

确保分组结果满足约束条件。

#### 约束条件

1. **数量均衡**：每组项目数尽量接近，差异 ≤ 3
2. **质量均衡**：各组平均质量得分差异 ≤ 5分
3. **学科内聚**：同组分尽量包含相似学科的项目

#### 优化算法

```python
def optimize_groups(groups: List[ProjectGroup]) -> List[ProjectGroup]:
    """分组优化
    
    Args:
        groups: 初始分组结果
    
    Returns:
        优化后的分组结果
    """
    # 1. 数量均衡优化
    groups = balance_count(groups)
    
    # 2. 质量均衡优化
    groups = balance_quality(groups)
    
    # 3. 学科内聚优化
    groups = optimize_subject_cohesion(groups)
    
    return groups
```

---

## 核心代码结构

### GroupingAgent

```python
class GroupingAgent:
    """分组 Agent，负责协调各组件完成项目分组"""
    
    def __init__(
        self,
        llm: Any = None,
        embedder: Any = None,
        cluster_algorithm: str = "kmeans"
    ):
        self.llm = llm or get_default_llm_client()
        self.embedder = embedder or get_default_embedder()
        self.analyzer = ProjectAnalyzer(self.llm)
        self.cluster = ProjectCluster(self.embedder, cluster_algorithm)
        self.optimizer = GroupOptimizer()
    
    async def group_projects(
        self,
        projects: List[Project],
        group_count: int = None,
        max_per_group: int = 30,
        strategy: str = "balanced"
    ) -> GroupingResult:
        """执行项目分组
        
        Args:
            projects: 项目列表
            group_count: 分组数量（None 则自动计算）
            max_per_group: 每组最大项目数
            strategy: 分组策略 (balanced/quality)
        
        Returns:
            分组结果
        """
        # 1. 项目内容分析
        analyzed = await self.analyzer.analyze_projects(projects)
        
        # 2. 项目向量化
        vectors = self.embedder.embed([p.text for p in analyzed])
        
        # 3. 计算分组数
        if group_count is None:
            group_count = self._calculate_optimal_groups(
                len(projects), max_per_group
            )
        
        # 4. 聚类分组
        cluster_labels = self.cluster.fit_predict(vectors, group_count)
        
        # 5. 质量评估
        quality_scores = await self._assess_quality(analyzed)
        
        # 6. 分组优化
        groups = self.optimizer.optimize(
            cluster_labels, quality_scores, strategy
        )
        
        return GroupingResult(groups=groups, statistics=...)
```

---

## 分组策略

### 1. 均衡策略 (balanced)

优先保证各组数量和质量均衡。

适用场景：评审资源均匀分布

### 2. 质量策略 (quality)

优先保证各组质量层次分明。

适用场景：需要区分重点项目

---

## 扩展性设计

### 新增分组算法

```
1. 在 grouping/cluster/ 下创建新算法类
2. 继承 BaseCluster
3. 实现 fit_predict() 方法
4. 在 GroupingAgent 中注册
```

### 新增质量评估维度

```
1. 在 grouping/analyzer/ 下创建新评估器
2. 继承 BaseQualityAssessor
3. 实现 assess() 方法
4. 在 GroupingAgent 中注册
```

---

## 相关文档

- [服务概述 →](01-overview.md)
- [专家匹配子服务 →](03-matching.md)
- [数据模型 →](04-models.md)
- [API 接口 →](05-api.md)
