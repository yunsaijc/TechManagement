# 🤖 EvaluationAgent 设计

## 角色定位

`EvaluationAgent` 是正文评审服务的统一编排器（Orchestrator），负责把原有九维评审与新增能力融合到一次执行中，输出单一 `EvaluationResult`。

## 核心职责

1. 输入归一化：解析 `project_id` / 上传文件、维度、权重、功能开关  
2. 文档准备：调用解析器完成章节提取与页码索引准备  
3. 项目画像识别：在九维检查前推断 `project_profile` 与维度覆盖规则  
4. Rubric 选择：按画像输出维度口径、缺失项容忍规则和必要证据要求  
5. 证据包构建：为评分、摘要、总评生成统一 `evidence pack`  
6. 并发调度：并行执行九维检查、划重点、技术摸底；指南贴合能力保留但默认不启用  
7. 结果合并：统一评分、总结、证据去重、异常归并  
8. 报告产物：输出正式审阅工作台 HTML 与 debug HTML  
9. 持久化：写入评审结果与证据链

## 编排流程

```
Step 1 读取项目与文档
Step 2 解析正文并建立页码索引
Step 3 推断 project_profile（规则式）
Step 4 生成 rubric 与维度级 evidence pack
Step 5 并行执行
  - 9D Checkers
  - Highlight Extractor
  - Industry Fit Analyzer
  - Benchmark Analyzer
  - Chat Index Builder（按开关启用）
Step 6 汇总评分与建议
Step 7 生成正式 HTML / debug HTML
Step 8 写入 storage 并返回结果
```

## 并发策略

- 使用 `asyncio.gather` 并行任务  
- 通过 `Semaphore` 控制并发上限  
- 子任务级超时控制  
- 单任务失败不阻断主流程，返回 `partial=true` 与 `errors[]`

## 与工具调用的关系

`EvaluationAgent` 不依赖模型“自动工具调用”。  
涉及检索时走服务端 `ToolGateway`：

- `doc_search`：申报书页码检索
- `tech_search`：文献/专利检索
- `guide_search`：产业指南检索（当前默认不启用）
- `tech_search`：当前先接 OpenAlex 公开论文检索，专利检索待补充

Agent 只接收结构化检索结果并完成分析与合并。

## 项目画像自适应

`EvaluationAgent` 在运行九维检查前，会调用 `ProjectProfiler` 做一次规则式画像识别，输出：

- `project_profile`
- `confidence`
- `evidence`
- `dimension_overrides`

当前设计约束：

- 画像推断只使用正文章节和关键词规则
- 画像是单次评审上下文，不做全局缓存
- checker 必须按本次画像实例化，不能复用带状态的共享实例
- 当前画像覆盖主要用于放宽章节口径；后续可进一步驱动 rubric 差异化，但仍不改变九维框架

## Rubric 与 Evidence Pack

`EvaluationAgent` 后续演进的主线不是重写聊天，而是把评审主流程改成：

1. 先按 `project_profile` 选择 `rubric`
2. 再为各维度构建 `evidence pack`
3. 最后基于证据做评分、摘要与总评

约束：

- `rubric` 负责定义“怎么看”，不是直接负责“怎么答”
- `evidence pack` 应被评分、摘要、总评复用，避免多处重复检索
- 若某维度证据不足，允许输出谨慎结论或材料不足提示，不强行拉满判断

## 与聊天能力的关系

聊天能力分两段执行：

1. 评审阶段：若 `enable_chat_index=true`，则根据解析器输出的 `page_chunks` 构建聊天索引并落盘  
2. 问答阶段：`/chat/ask` 与 `/chat/ask-stream` 共用同一套索引准备逻辑；先加载评审结果，再加载聊天索引；若索引缺失会尝试自动重建（优先 `debug_eval` 页切片，其次原始文档），然后执行页码检索与回答生成  
3. 证据联动阶段：正式 HTML 中点击聊天证据时，再调用 `/chat/citation-highlight` 懒加载 `packet_page/highlight_rects`

当前实现约束：

- 聊天主链路当前已满足低时延与稳定性要求，后续默认不做重构
- 聊天检索优先基于 `page_chunks`
- 引用结果必须返回 `file/page/snippet`
- 为降低响应时延，`/chat/ask` 不同步补齐 `highlight_rects`
- 正式 HTML 聊天面板优先调用 `/api/v1/evaluation/chat/ask-stream`，失败时回退 `/api/v1/evaluation/chat/ask`
- `ask-stream` 会额外输出阶段性 `status` 事件，供前端显示“正在准备索引 / 正在检索证据 / 正在生成回答”等动态进度
- 在 `qwen` 兼容接口场景下，聊天热路径优先直连模型接口，并显式关闭 `thinking` 以压低首字延迟；若直连失败再回退通用 LLM 链路
- 评审完成后会为正式 HTML 报告同步生成一组“专家关注问答”，用于直接展示典型问题与页码证据
- “专家关注问答”默认使用 LLM 生成，若模型不可用则降级为规则式回答
- 评审调试 JSON 会落 `page_chunks`，用于问答阶段自动重建索引
- 进程内对 `evaluation result / chat index / debug payload / packet assets` 做小规模缓存，降低重复提问与重复点证据时的磁盘 IO
- 正式 HTML 报告内嵌聊天前端，直接调用 `/api/v1/evaluation/chat/ask`
- 正式 HTML 中的聊天证据链接在点击时调用 `/api/v1/evaluation/chat/citation-highlight`
- 即使 `chat_ready=false`，前端也允许直接提问，首问触发后端自动建索引
- 正式 HTML 采用“左正文、右结果”的审阅工作台布局
- 右侧所有 `evidence/citation` 应复用统一跳转协议，驱动左侧正文定位
- 报告可能以本地文件形式打开，因此应用层需允许跨域访问正文评审 API
- 检索阶段会对问题做轻量意图识别，例如：
  - 研究目标
  - 预期效益
  - 验证数据
  - 进展程度
  - 量产可能性
- 检索排序会优先提升相关章节，抑制附件、表格噪声页

后续聊天增强范围只限于：

- 问题分类与检索路由
- 更稳定的证据整理
- 回答结构规范化

明确不做：

- 不把聊天改成多 reviewer agent 串并行编排
- 不替换现有流式协议与首字延迟优化链路
- 不为“最佳实践”牺牲当前可用性

## 聊天降级策略

当前聊天问答采用“两层降级”：

1. 无检索命中：直接返回“未检索到可支撑问题的正文证据”  
2. LLM 不可用或调用失败：退回规则式回答，并保留 citation

规则式回答要求：

- 仍然返回 `answer + citations`
- 若证据不足，必须明确说明“不足以形成确定性结论”
- 对“验证数据”“量产可能性”这类高风险问题，优先输出谨慎判断，而不是直接肯定

## 结果合并规则

合并后主结果包含：

- `dimension_scores`、`overall_score`、`grade`
- `highlights`
- `industry_fit`（保留字段，默认不启用）
- `benchmark`
- `evidence`（`file/page/snippet/source`）
- `chat_ready`
- `partial`、`errors`

报告产物包含：

- `EVAL_{project_id}.html`：正式审阅工作台
- `EVAL_{project_id}.debug.html`：调试报告
- `EVAL_{project_id}.json`：用于重建报告与正文联动的数据底座
- `projects/{project_id}/evaluation_packet.pdf`：统一材料包
- `projects/{project_id}/evaluation_packet.page_map.json`：原文件页码到 packet 页码映射
- `projects/{project_id}/packet_viewer.html`：左侧阅读 iframe 使用的 packet viewer

正式工作台最小要求：

- 左侧优先加载统一 `packet viewer`，把正文与附件合并到单一阅读面板
- 若 packet 资产缺失，再回退到基于 `page_chunks` 的按页正文渲染
- 右侧结果区展示评分、划重点、问答、证据
- 任一 `evidence/citation` 点击后都能把左侧正文定位到对应页
- 若 `snippet` 可匹配到 packet 或正文片段，则需对命中区域做临时高亮；匹配失败时至少完成页级跳转
- 证据卡以“跳转核验”为主，不以大段摘要展示为主

## 异常与降级

- 无项目文档：提示改用 `/api/v1/evaluation/evaluate/file`
- 外部检索失败：关闭对应模块并标记 `partial`
- 解析失败：返回可定位错误信息，保留已完成模块输出
- 聊天阶段索引不存在：先自动重建；重建失败时 `/chat/ask` 返回“该评审记录未构建聊天索引，且无法自动重建”
- 聊天阶段模型异常：不抛出内部异常，回退到规则式回答并保留引用

当前 `benchmark` 降级语义：

- 若 `tech_search` 未配置，则主流程不中断
- 返回 `partial=true`
- `errors[]` 追加一条 `code=TOOL_UNAVAILABLE, module=benchmark`
- `benchmark` 字段填充占位结论：
  - `novelty_level=unknown`
  - `literature_position=技术摸底工具不可用`
  - `patent_overlap=专利对比待接入`
  - `conclusion=当前仅基于申报书内容，外部对比结论待补充`

当前 `industry_fit` 降级语义：

- 若 `guide_search` 未配置，则主流程不中断
- 返回 `partial=true`
- `errors[]` 追加一条 `code=TOOL_UNAVAILABLE, module=industry_fit`
- `industry_fit` 字段填充占位结果：
  - `fit_score=0.0`
  - `matched=[]`
  - `gaps=["产业指南检索不可用，结果待核验"]`
  - `suggestions=["待检索工具恢复后补充指南映射"]`

当前能力约束补充：

- 由于暂无法在本地数据中可靠建立项目与指南正文的可核验关联，`industry_fit` 不作为正式报告主展示能力
- `benchmark` 当前优先消费公开论文检索结果，不把“未做专利检索”误写成“无专利重叠风险”

## 代码锚点

- 编排入口：`src/services/evaluation/agent.py`
- 项目画像：`src/services/evaluation/profile/`
- 维度检查：`src/services/evaluation/checkers/`
- 解析能力：`src/services/evaluation/parsers/`
- 存储：`src/services/evaluation/storage/`
