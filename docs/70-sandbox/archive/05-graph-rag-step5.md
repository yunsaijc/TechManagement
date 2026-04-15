# 第五步：GraphRAG 最小闭环

## 一、服务定位

目标是在现有图算法与规则研判基础上，新增“问题驱动的子图检索 + LLM 生成”链路。

## 二、业务流程图

```text
用户问题输入
  -> 关键词抽取
  -> Neo4j 种子检索
  -> k-hop 子图扩展
  -> 子图上下文构建
  -> LLM 生成 answer/keyFindings/actions/confidence
```

## 三、核心技术选型

- 图检索：Neo4j + Cypher
- 编排层：Python 检索与序列化
- 生成层：LangChain + 统一 LLM 配置
- 输出层：结构化 JSON（检索证据 + 生成结果）

## 四、核心代码结构

- 服务实现: src/services/sandbox/graph_rag_step5.py
- 运行入口: scripts/sandbox_graph_rag_step5.py
- 联动入口: scripts/sandbox_run_step3_step4_step5.py

## 五、设计思路

1. 问题解析
- 从自然语言问题中抽取关键词（中文/英文 token）。

2. 图检索
- 基于关键词在 Neo4j 中检索种子节点（Project/Person/Fund/Program/Topic）。
- 从种子节点做 k-hop 子图扩展。

3. 上下文构建
- 将子图节点和关系序列化为上下文文本。

4. 生成回答
- 使用 LangChain + 统一 LLM 配置生成结构化回答（answer/keyFindings/actions/confidence）。

## 六、环境变量

Neo4j 连接继续使用 `.env`：

- NEO4J_URI
- NEO4J_USER
- NEO4J_PASSWORD
- NEO4J_DATABASE

GraphRAG 可选参数：

- GRAPHRAG_QUESTION
- GRAPHRAG_OUTPUT_PATH
- GRAPHRAG_MAX_HOPS
- GRAPHRAG_SEED_LIMIT
- GRAPHRAG_SUBGRAPH_NODE_LIMIT
- GRAPHRAG_SUBGRAPH_REL_LIMIT
- GRAPHRAG_TOP_KEYWORDS

默认输出：

- debug_sandbox/graph_rag_answer_step5.json

## 七、运行示例

```bash
python scripts/sandbox_graph_rag_step5.py
```

```bash
python scripts/sandbox_run_step3_step4_step5.py
```

## 八、输出结构

- meta: 检索参数与命中统计
- retrieval: seeds、subgraph（nodes/relationships）、contextPreview
- generation: answer、keyFindings、actions、confidence

## 九、上下游依赖关系

- 上游依赖：Step3 规则输出（用于辅助问答上下文）和 Step4 简报摘要。
- 下游输出：问答接口响应、调试分析页面、后续评测脚本。

## 十、下一步建议

1. 引入问题重写与实体对齐（提升检索召回）。
2. 增加关系路径打分（重要路径优先进入上下文）。
3. 增加 GraphRAG 评测集（答案事实一致性、证据命中率）。
