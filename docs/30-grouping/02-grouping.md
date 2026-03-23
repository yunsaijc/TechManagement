# 📋 分组子服务设计

## 概述

分组子服务负责将申报项目按"项目在做什么"进行分组。当前实现采用**关键词Embedding主导 + 学科代码辅助**的策略：以项目关键词（`gjc` 字段）为主要信息计算Embedding进行语义聚类，学科代码作为辅助参考信息。

分组的基本原则是：
- **关键词是分组的核心依据**，决定项目主题相似性
- **Embedding捕捉关键词语义关系**，进行全局层次聚类
- **学科代码作为辅助信息**，帮助理解分组结果
- 关键词差异大的项目应分到不同组，即使学科代码相同
- 组内主题必须能被人类评审解释
- 过大组（>max_per_group）必须拆分，过小组（<min_per_group）必须合并

---

## 核心逻辑

### 分组目标

1. 基于项目关键词计算全局Embedding，建立语义空间
2. 基于Embedding相似度进行全局层次聚类，形成初始组
3. 根据容量约束对过小组和过大组进行再平衡
4. 最终输出可解释、可回放的分组结果

### 关键词的主导地位

项目关键词（`gjc` 字段）是分组的核心依据：
- **文本构造**：关键词重复3次 + "主题：" + 关键词 + "项目名称：" + 项目名
- 通过重复和结构化确保关键词在Embedding中占主导地位
- 项目名作为补充信息，权重较低
- **无关键词Fallback**：从项目名提取2-8字中文词组，过滤停用词

### Embedding计算

基于构造文本计算项目Embedding：
- 使用统一的Embedding模型（如text-embedding-3-small）
- 所有项目先计算Embedding，保存在全局vector_map中
- 基于余弦相似度进行层次聚类

### 学科代码的辅助作用

学科代码作为辅助参考信息：
- 帮助理解分组结果的学科分布
- 用于生成组标题时提供学科上下文
- 不再作为硬性分组边界

---

## 推荐流程

```
1. 获取项目列表（含学科代码、关键词、项目名称字段）
2. 构造文本（关键词重复3次 + 项目名）
3. 计算全局Embedding，建立vector_map
4. 基于Embedding相似度进行全局层次聚类
5. 对超过 max_per_group 的组基于Embedding重新聚类拆分
6. 对小于 min_per_group 的组找Embedding最相似的组合并
7. 按需生成组标题、理由和复核标记
8. 输出分组结果 + 理由 + 复核标记
```

---

## 详细策略（关键词Embedding主导分组）

### 1. 文本构造

构造用于Embedding的文本，确保关键词权重最高：

**构造格式**：
```
{关键词}。研究主题：{关键词}。核心内容：{关键词}。项目名称：{项目名}
```

**示例**：
- 关键词：`"深度学习；图像识别；神经网络"`
- 项目名：`"基于CNN的医学影像诊断系统"`
- 构造文本：`"深度学习；图像识别；神经网络。研究主题：深度学习；图像识别；神经网络。核心内容：深度学习；图像识别；神经网络。项目名称：基于CNN的医学影像诊断系统"`

**关键词Fallback**（当`gjc`为空时）：
- 从项目名提取2-8字中文词组
- 过滤停用词：`{"项目", "研究", "技术", "系统", "方法", "应用", "开发", "平台", "基于", "及其"}`
- 若提取失败，使用项目名本身

### 2. 全局Embedding计算

基于构造文本计算所有项目的Embedding：
- 使用统一的Embedding模型
- 建立全局vector_map：`{project_id: embedding_vector}`
- 基于余弦相似度计算项目间相似度

### 3. 层次聚类

基于Embedding相似度进行全局层次聚类：
- 初始状态：每个项目为一个簇
- 迭代合并：Embedding相似度最高的两个簇合并
- 停止条件：相似度低于阈值或达到组大小约束
- 最终形成初始分组

### 4. 同主题识别

Embedding相似度高的项目聚在一组，即使学科代码不同：

示例：
- 项目A（代码F0202）：关键词`深度学习；图像识别` → 分到"深度学习应用组"
- 项目B（代码B0103）：关键词`深度学习；医学影像` → 同组（主题相似）
- 项目C（代码F0202）：关键词`网络安全；加密算法` → 分到"网络安全组"（主题不同）

### 5. 过大组拆分

对于超过 `max_per_group` 的组：
- 基于Embedding重新进行层次聚类
- 优先按语义切分成多个子主题
- 每个子主题保持内部Embedding相似度高

### 6. 过小组合并

对于小于 `min_per_group` 的组：
- 在全局找Embedding最相似的组
- 合并后不超过`max_per_group`
- 优先合并主题相似的组

---

## 结果要求

每个组至少输出：
- `group_name`
- `group_reason`
- `count`
- `needs_review`
- 组内每个项目的 `project_reason`
- 每个项目的 `confidence`

最终结果要能支持：
- 人工查看
- 追溯为什么这样分
- 重新运行时结果稳定

---

## 伪代码（关键词Embedding主导分组）

```python
projects = load_fixed_grouping_test_projects()

# 1. 构造文本并计算全局Embedding
vector_map = {}
for project in projects:
    text = construct_text(project)  # 关键词重复3次 + 项目名
    vector_map[project.id] = compute_embedding(text)

# 2. 基于Embedding相似度进行全局层次聚类
similarity_matrix = compute_cosine_similarity(vector_map)
clusters = hierarchical_cluster(projects, similarity_matrix, threshold=0.7)

# 3. 处理过大组（基于Embedding重新聚类拆分）
clusters = split_large_groups(clusters, max_per_group, vector_map)

# 4. 处理过小组合并到最相似的组
clusters = merge_small_groups(clusters, min_per_group, vector_map)

return export_result(clusters)
```

---

## 约束参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `min_per_group` | 3 | 小组下限，低于则合并 |
| `max_per_group` | 15 | 每组上限，超过则拆分 |
| `embedding_threshold` | 0.7 | Embedding相似度阈值（低于不聚类） |
| `top_k_candidates` | 3 | 每个项目保留的候选组数 |
| `confidence_threshold` | 0.65 | 低于该值标记复核 |
| `enable_embedding` | true | 启用Embedding计算（关键词主导） |
| `enable_llm` | false | 是否启用LLM（当前用规则生成标题） |

---

## 运行建议

- **核心依据**：项目关键词（`gjc` 字段）主导Embedding计算
- 构造文本时关键词重复3次确保权重最高
- 所有项目先计算全局Embedding，建立语义空间
- 基于Embedding相似度进行全局层次聚类
- 关键词为空时从项目名提取作为fallback
- 组标题优先用高频关键词+学科名称规则生成
- 所有低置信度项目都要保留复核信息

---

## 相关文档

- [智能分组与专家匹配服务概述](01-overview.md)
- [数据模型](04-models.md)
- [API 接口文档](05-api.md)
