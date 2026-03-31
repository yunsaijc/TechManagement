# 🧪 测试文档

## 测试目标

验证融合后的正文评审服务在以下方面稳定可用：

1. 九维评审结果正确  
2. 划重点/指南贴合/技术摸底可并行执行  
3. 聊天问答可返回页码证据  
4. 搜索工具不可用时可降级并标记 `partial/errors`

## 测试分层

1. 单元测试：解析器、检查器、评分器、工具网关适配层  
2. 集成测试：`EvaluationAgent` 并发编排与结果合并  
3. API 测试：`/evaluate`、`/evaluate/file`、`/chat/ask`  
4. 回归测试：与历史评审结果字段兼容

## 目录建议

```
tests/services/evaluation/
├── test_checkers/
├── test_parsers/
├── test_scorers/
├── test_tools/
│   └── test_gateway.py
├── test_highlight/
├── test_benchmark/
├── test_chat_indexer.py
├── test_chat_agent.py
├── test_agent_orchestration.py
├── test_api_evaluation.py
└── test_api_chat.py
```

## 核心测试矩阵

### A. 并发编排

- 用例：同时启用 `enable_highlight/enable_industry_fit/enable_benchmark`  
- 断言：所有子任务结果被合并到同一 `EvaluationResult`
- 断言：任一子任务超时时，主流程仍返回并设置 `partial=true`

### B. 工具网关与搜索

- 用例：`guide_search` 正常返回  
- 断言：`industry_fit` 含 `matched/gaps/suggestions`
- 用例：`tech_search` 失败  
- 断言：`benchmark` 降级，`errors` 包含 `TOOL_UNAVAILABLE`

### C. 文档解析与证据

- 用例：PDF 正常解析  
- 断言：存在 `page_chunks` 且页码递增
- 用例：DOCX 解析  
- 断言：支持近似分页并标记 `page_estimated=true`

### D. 聊天问答

- 用例：`/chat/ask` 提问“验证数据有吗？”  
- 断言：返回 `answer + citations[]`
- 断言：每条 citation 包含 `file/page/snippet`
- 断言：无证据时不输出“确定性结论”
- 断言：LLM 异常时，`ask()` 仍返回降级回答和 citations，而不是抛出内部错误
- 断言：研究目标问题不会优先命中附件或纯表格噪声页
- 断言：预期效益问题能命中效益相关章节并抽取社会/经济/效益类信息
- 断言：量产可能性问题在证据不足时保持谨慎，不直接输出“可以量产”

### E. 兼容与回归

- 用例：不开启新增开关执行旧请求  
- 断言：老字段结构不变，旧调用方可直接使用
- 用例：历史结果读取  
- 断言：缺失新增字段时可平滑反序列化

## 验收标准（最小发布门槛）

1. 主流程接口成功率 >= 99%（集成测试场景）  
2. 并发任务失败不导致整体 500（除输入非法）  
3. 聊天回答引用命中率 >= 95%（测试集）  
4. 所有降级路径均能返回明确 `partial/errors`  
5. 新增能力关闭时，评分结果与旧版偏差在可控范围内

## 测试数据要求

- 不创建模拟业务数据目录  
- 使用真实项目数据或接口上传文件测试  
- 若使用 mock，仅用于单元测试隔离外部依赖

## 执行建议

1. PR 前：单元 + 集成测试全量通过  
2. 合并前：API 回归 + 关键问答用例  
3. 发布前：抽样真实项目做端到端校验（含页码引用核验）

## 当前已落地的最小自动化测试

当前仓库已补充以下聊天能力最小测试：

- `tests/services/evaluation/test_chat_indexer.py`
  - 研究目标问题优先命中目标/简介章节
  - 量产/推广问题优先命中效益或推广章节
- `tests/services/evaluation/test_chat_agent.py`
  - 开启 `enable_chat_index` 后，`ask()` 可返回 citations
  - LLM 异常时，`ask()` 走降级回答
  - 未构建聊天索引时返回明确错误
  - `验证数据` 问答保持谨慎
  - `预期效益` 问答能抽取效益信息
- `tests/services/evaluation/test_benchmark.py`
  - `BenchmarkRetriever` 可将 `tech_search` 结果映射为标准 `BenchmarkReference`
  - `BenchmarkAnalyzer` 在有外部检索结果时可生成结论与证据
  - 未配置 `tech_search` 时，`EvaluationAgent` 返回 `partial=true`、`TOOL_UNAVAILABLE` 和降级 `benchmark`

## 调试产物

- 评审完成后应同步输出调试产物到 `debug_eval/`
- 至少包含：
  - `{evaluation_id}.json`：完整评审结果与章节调试信息
  - `{evaluation_id}.html`：可直接查看的评审可视化报告
  - `index.html`：调试报告索引页
