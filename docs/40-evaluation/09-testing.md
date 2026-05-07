# 🧪 测试文档

## 测试目标

验证融合后的正文评审服务在以下方面稳定可用：

1. 九维评审结果正确  
2. 划重点/指南贴合/技术摸底可并行执行  
3. 聊天问答可返回页码证据  
4. 搜索工具不可用时可降级并标记 `partial/errors`
5. 不同类型申报书可按画像应用不同评审口径
6. 正式 HTML 审阅工作台可稳定完成“右侧证据 -> 左侧正文”联动
7. 已优化的聊天低时延、流式体验与谨慎回答能力不被后续方案回归破坏

## 测试分层

1. 单元测试：解析器、检查器、评分器、工具网关适配层  
2. 单元测试：项目画像识别与维度覆盖规则  
3. 单元测试：`rubric` 选择与 `evidence pack` 构建
4. 集成测试：`EvaluationAgent` 并发编排与结果合并  
5. API 测试：`/evaluate`、`/evaluate/file`、`/chat/ask`、`/chat/ask-stream`  
6. 前端报告测试：左右布局、正文跳转、高亮联动  
7. 回归测试：与历史评审结果字段兼容

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
- 用例：封面/填报说明/附件目录/绩效表头混入正文  
- 断言：不会被误归类为 `研究目标/进度安排/预期成果` 等业务章节

### D. Rubric 与 Evidence Pack

- 用例：基础研究类项目进入标准研发口径
- 断言：`feasibility/innovation` 维度仍要求技术方案、验证或研究路径证据
- 用例：平台建设类项目缺少独立“技术路线”章节
- 断言：可由“建设目标/建设内容/实施方案”进入替代评估，而不是直接判缺失
- 用例：某维度只命中封面、目录或噪声页
- 断言：该维度 `evidence pack` 不应视为充分证据
- 用例：摘要、评分、总评同时消费同一证据包
- 断言：关键页码引用保持一致，不出现互相矛盾的证据来源

### E. 聊天问答

- 用例：`/chat/ask` 提问“验证数据有吗？”  
- 断言：返回 `answer + citations[]`
- 断言：每条 citation 包含 `file/page/snippet`
- 用例：`/chat/citation-highlight` 请求单条引用  
- 断言：返回 `packet_page/highlight_rects`，允许 `highlight_rects=[]` 但仍应支持页级跳转
- 断言：无证据时不输出“确定性结论”
- 断言：LLM 异常时，`ask()` 仍返回降级回答和 citations，而不是抛出内部错误
- 断言：研究目标问题不会优先命中附件或纯表格噪声页
- 断言：研究目标问题不会被泛化的“项目/研究/合作研究目的”字样带偏
- 断言：进展问题不会优先命中封面、预算页或纯职责分工页
- 断言：预期效益问题能命中效益相关章节并抽取社会/经济/效益类信息
- 断言：量产可能性问题在证据不足时保持谨慎，不直接输出“可以量产”
- 断言：问答首字延迟与流式增量体验不因评审主链路调整而明显退化
- 断言：聊天增强仅限问题路由/证据整理，不改变现有 API 结构

### F. 审阅工作台

- 用例：正式 HTML 报告加载
- 断言：页面采用左正文、右结果的双栏结构
- 用例：点击评分/划重点/问答中的证据
- 断言：左侧正文阅读区至少完成页级跳转
- 断言：若 `snippet` 在正文中可匹配，则命中块出现高亮态
- 用例：正文联动时遇到无法精确匹配的证据
- 断言：仍能定位到对应页，而不是跳转失败
- 用例：移动端宽度
- 断言：页面退化为上下布局，信息仍可完整访问

### G. 兼容与回归

- 用例：科普实施类项目缺少独立 `技术路线` 章节
- 断言：`feasibility / schedule / risk_control` 不直接退化为默认 5 分缺失结论
- 用例：科普实施类项目未单列成果/社会效益/经济效益章节
- 断言：可按绩效指标、推广范围、模式复制等内容替代评估
- 用例：平台建设类项目使用“建设目标/核心建设内容”等标题
- 断言：可被识别为替代章节
- 用例：同一 `EvaluationAgent` 连续评审不同项目
- 断言：前一次 `project_profile` 不会污染后一次评审口径

- 用例：不开启新增开关执行旧请求  
- 断言：老字段结构不变，旧调用方可直接使用
- 用例：历史结果读取  
- 断言：缺失新增字段时可平滑反序列化

## 验收标准（最小发布门槛）

1. 主流程接口成功率 >= 99%（集成测试场景）  
2. 并发任务失败不导致整体 500（除输入非法）  
3. 聊天回答引用命中率 >= 95%（测试集）  
4. 所有降级路径均能返回明确 `partial/errors`  
5. 审阅工作台中任一证据点击后，页级跳转成功率 = 100%  
6. 新增能力关闭时，评分结果与旧版偏差在可控范围内
7. 聊天接口协议、流式事件和低时延体验不因 rubric/evidence 主线改造而回归

## 测试数据要求

- 不创建模拟业务数据目录  
- 使用真实项目数据或接口上传文件测试  
- 若使用 mock，仅用于单元测试隔离外部依赖

## 执行建议

1. PR 前：单元 + 集成测试全量通过  
2. 合并前：API 回归 + 关键问答用例  
3. 发布前：抽样真实项目做端到端校验（含页码引用核验）

## 当前已落地的最小自动化测试

当前仓库已补充以下评审主链路最小测试：

- `tests/services/evaluation/test_chat_indexer.py`
  - 研究目标问题优先命中目标/简介章节
  - 量产/推广问题优先命中效益或推广章节
  - 研究目标问题不会被泛化研究噪声带偏
  - 进展问题不会优先命中封面信息
- `tests/services/evaluation/test_chat_agent.py`
  - 开启 `enable_chat_index` 后，`ask()` 可返回 citations
  - `ask_stream()` 可返回 `delta/done` 流式事件
  - LLM 异常时，`ask()` 走降级回答
  - 未构建聊天索引时返回明确错误
  - 未构建索引时可自动重建并完成回答
  - `验证数据` 问答保持谨慎
  - `预期效益` 问答能抽取效益信息
- `tests/services/evaluation/test_benchmark.py`
  - `BenchmarkRetriever` 可将 `tech_search` 结果映射为标准 `BenchmarkReference`
  - `BenchmarkAnalyzer` 在有外部检索结果时可生成结论与证据
  - 未配置 `tech_search` 时，`EvaluationAgent` 返回 `partial=true`、`TOOL_UNAVAILABLE` 和降级 `benchmark`
- `tests/services/evaluation/test_industry_fit.py`
  - `IndustryFitAnalyzer` 在有 `guide_search` 结果时可生成 `matched/gaps/suggestions/evidence`
  - 未配置 `guide_search` 时，`EvaluationAgent` 返回 `partial=true`、`TOOL_UNAVAILABLE` 和降级 `industry_fit`
- `tests/services/evaluation/test_agent_orchestration.py`
  - 同时开启 `highlight/industry_fit/benchmark/chat_index` 时，结果可被正确合并到同一 `EvaluationResult`
  - 合并后保留 `highlights/industry_fit/benchmark/evidence/chat_ready`
- `tests/services/evaluation/test_project_profiler.py`
  - 科普实施类/平台建设类/技术研发类画像可被识别
  - 画像证据不足时回退到 `generic`
- `tests/services/evaluation/test_profile_adaptation.py`
  - 科普实施类项目缺少独立技术路线时，相关维度走放宽口径
  - 科普实施类项目未单列成果/效益章节时，成果与效益维度走放宽口径
  - 同一 agent 连续评审时，画像状态不会串用
- 后续新增：
  - `tests/services/evaluation/test_rubric_manager.py`
    - 不同 `project_profile` 输出不同必要项与缺失容忍规则
  - `tests/services/evaluation/test_evidence_pack.py`
    - 维度级 `evidence pack` 可过滤噪声页、保持页码一致性、供摘要/评分/总评复用
- `tests/services/evaluation/test_api_evaluation.py`
  - `evaluate/file` 路由可解析表单参数并调用评审 Agent
  - `chat/ask` 路由可返回 `answer + citations`
  - `chat/ask-stream` 路由可返回 SSE 事件流
  - `chat/ask` 会把“评审记录不存在”映射为 `404`
  - `chat/ask` 会把“未构建聊天索引”映射为 `422`
- `tests/services/evaluation/test_report_generator.py`
  - 正式报告 HTML 内包含交互式聊天面板与 `/chat/ask-stream` 优先调用脚本
  - 聊天面板包含进度时间线、流式骨架和结构化回答卡脚本
  - debug 报告不包含交互式聊天面板
  - `chat_ready=false` 时仍允许首问（由后端自动建索引）
  - 正式报告采用左正文、右结果布局
  - 证据项与 citation 带有统一的正文跳转标记
- `tests/app/test_main.py`
  - 应用层为本地 HTML 报告开放 CORS，允许 `file://` 场景调用正文评审 API

## 调试产物

- 评审完成后应同步输出调试产物到 `debug_eval/`
- 至少包含：
  - `EVAL_{project_id}.json`：完整评审结果与章节调试信息
  - `EVAL_{project_id}.html`：专家阅览版正式报告，包含专家关注问答
  - `EVAL_{project_id}.debug.html`：开发调试版报告，保留章节预览等排障信息
  - `index.html`：调试报告索引页
