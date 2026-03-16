# 📋 分组子服务设计

## 概述

分组子服务是智能分组与专家匹配服务的核心组件之一，负责将申报项目智能地分配到不同的评审组，实现组内数量与质量的双均衡。

## 功能说明

1. **项目向量化**：使用 Embedding 模型将项目转换为向量（直接用项目名称+关键词，不需要 LLM 分析）
2. **智能分组计算**：根据项目数量自动计算最优分组数
3. **质量评估**：使用 LLM 评估每个项目的创新性、技术难度、应用价值（**抽样评估**）
4. **分组优化**：确保各组数量均衡，质量均衡、主题相关
5. **结果缓存**：避免重复计算

---

## 业务流程（优化后）

```
┌─────────────────────────────────────────────────────────────────┐
│                        分组子服务流程                              │
└─────────────────────────────────────────────────────────────────┘

     输入: 项目列表 (含 xmmc, gjc, ssxk)
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
│   2. 项目向量化      │
│   (Embedding)       │
│   - 直接用项目文本  │
│   - 无需LLM分析    │
│   - 结果缓存        │
└──────┬──────────────┘
         │
         ▼
    ┌────┴────┐
    │         │
    ▼         ▼
┌────────┐ ┌────────┐
│3a.聚类 │ │3b.质量│
│分组   │ │评估(抽)│
└───┬────┘ └───┬────┘
    │         │
    └────┬────┘
         │
         ▼
┌─────────────────────┐
│   4. 分组优化       │
│   - 数量均衡        │
│   - 质量均衡        │
│   - 学科内聚        │
└──────┬──────────────┘
         │
         ▼
     输出: 分组结果
```

### 优化要点

| 优化项 | 原方案 | 优化后 | 效果 |
|--------|--------|--------|------|
| 项目分析 | 每个LLM分析 | 直接用Embedding | 减少5000+次LLM调用 |
| 质量评估 | 全量评估 | 每组抽样3-5个 | 减少90% LLM调用 |
| LLM调用 | 逐个调用 | 批量调用 | 减少API往返 |
| 结果缓存 | 无 | 向量/结果缓存 | 避免重复计算 |

---

## 核心模块

### 1. 项目向量化 (Embedding)

直接使用 Embedding 模型将项目文本转换为向量，**不需要 LLM 分析步骤**。

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
2. **文本融合**：拼接 `项目名称 + 关键词 + 简介`（不超过2000字）
3. **Embedding 向量化**：使用 qwen text-embedding-v3 生成 1024 维向量

#### 向量缓存

```python
# 检查缓存
cached = cache.get(f"project_vector:{project_id}")
if cached:
    return cached

# 计算并缓存
vector = embedder.embed_documents([text])[0]
cache.set(f"project_vector:{project_id}", vector, ttl=7*24*3600)
return vector
```

#### 输出

```python
{
    "project_id": "xxx",
    "vector": [0.123, -0.456, ...],  # 1024维
    "text": "基于多尺度分析的智能电网故障预测系统..."
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

**优化：采用抽样评估策略**

对于每个分组，只评估 3-5 个代表性项目，然后推算全组质量。

#### 抽样策略

```python
def sample_projects_for_quality(group_projects: List[Project], sample_size: int = 5) -> List[Project]:
    """抽样选择需要评估的项目
    
    策略：
    1. 按向量距离选择中心点附近的3个
    2. 随机选择2个作为补充
    """
    if len(group_projects) <= sample_size:
        return group_projects
    
    # 计算组内向量中心
    center = np.mean([p.vector for p in group_projects], axis=0)
    
    # 选择距离中心最近的
    distances = [np.linalg.norm(p.vector - center) for p in group_projects]
    sorted_idx = np.argsort(distances)[:sample_size-2]
    
    # 补充随机
    random_idx = random.sample(range(len(group_projects)), 2)
    
    return [group_projects[i] for i in set(list(sorted_idx) + random_idx)]
```

#### 评估维度

| 维度 | 权重 | 说明 |
|------|------|------|
| 创新性 | 40% | 技术的原创性、领先程度 |
| 技术难度 | 30% | 技术的复杂程度、实现难度 |
| 应用价值 | 30% | 推广应用前景，经济效益 |

#### 批量LLM评估

```python
async def batch_assess_quality(projects: List[Project], batch_size: int = 10) -> List[QualityScore]:
    """批量评估项目质量
    
    优化：一次发送多个项目，减少API调用次数
    """
    results = []
    
    for i in range(0, len(projects), batch_size):
        batch = projects[i:i+batch_size]
        
        # 批量构建prompt
        prompt = build_batch_prompt(batch)
        
        # 一次LLM调用
        response = await llm.ainvoke(prompt)
        
        # 解析批量结果
        batch_results = parse_batch_quality(response)
        results.extend(batch_results)
    
    return results
```

### 4. 分组优化 (Optimizer)

确保分组结果满足约束条件。

#### 约束条件

1. **数量均衡**：每组项目数尽量接近，差异 ≤ 3
2. **质量均衡**：各组平均质量得分差异 ≤ 5分
3. **学科内聚**：同组分尽量包含相似学科的项目

---

## 性能优化

### 5000+ 项目处理预估

| 步骤 | 优化前 | 优化后 |
|------|--------|--------|
| 项目向量化 | ~10分钟 | ~10分钟 |
| 聚类计算 | ~1分钟 | ~1分钟 |
| 质量评估 | ~8小时 (10000次LLM) | ~5分钟 (100次抽样) |
| **总计** | **~8小时** | **~15分钟** |

### 缓存策略

```python
# 缓存配置
CACHE_CONFIG = {
    "project_vectors": {"ttl": 7 * 24 * 3600},  # 7天
    "quality_scores": {"ttl": 24 * 3600},        # 1天
    "grouping_results": {"ttl": 30 * 24 * 3600} # 30天
}
```

---

## 核心代码结构

### GroupingAgent (优化后)

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
        self.vector_cache = VectorCache()  # 新增：向量缓存
        self.quality_cache = QualityCache() # 新增：质量缓存
        self.cluster = ProjectCluster(self.embedder, cluster_algorithm)
        self.optimizer = GroupOptimizer()
        self.quality_assessor = QualityAssessor(self.llm)
    
    async def group_projects(
        self,
        projects: List[Project],
        group_count: int = None,
        max_per_group: int = 30,
        strategy: str = "balanced"
    ) -> GroupingResult:
        """执行项目分组"""
        
        # 1. 项目向量化（带缓存）
        vectors = await self._get_project_vectors(projects)
        
        # 2. 计算分组数
        if group_count is None:
            group_count = self._calculate_optimal_groups(
                len(projects), max_per_group
            )
        
        # 3. 聚类分组
        cluster_labels = self.cluster.fit_predict(vectors, group_count)
        
        # 4. 质量评估（抽样+批量）
        quality_scores = await self._assess_quality_sampled(
            projects, cluster_labels, group_count
        )
        
        # 5. 分组优化
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

## 相关文档

- [服务概述 →](01-overview.md)
- [专家匹配子服务 →](03-matching.md)
- [数据模型 →](04-models.md)
- [API 接口 →](05-api.md)
