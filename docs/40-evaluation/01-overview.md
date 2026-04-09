# 🔍 正文评审服务概述

## 服务定位

正文评审服务面向申报书正文，统一输出一份可追溯的智能评审结果。  
在原有 9 维评分基础上，融合以下能力：

- 一键划重点：提取研究目标、创新点、技术路线
- 产业指南贴合度评估：判断项目与省级产业指南匹配程度
- 技术水平摸底：结合文献/专利检索生成对比结论
- 专家问答：专家可直接就申报书提问，答案附页码证据
- 报告可视化：评审完成后生成专家阅览版 HTML，并单独保留 debug HTML
- 交互式问答前端：正式报告页内嵌聊天面板，直接调用 `/api/v1/evaluation/chat/ask`
- 审阅工作台：正式报告采用“左正文、右结果”双栏布局，支持证据跳转与原文核验

## 与其他服务关系

```
形式审查(可选前置) ─┐
查重(可选前置)     ─┼─> 正文评审(evaluation) -> 统一评审结果
分组(可选前置)     ─┘
```

## 核心能力

### 1. 九维正文评审（保留）

继续覆盖技术可行性、创新性、团队能力、预期成果、社会效益、经济效益、风险控制、进度合理性、合规性。

### 2. 融合增强能力

- 划重点结构化摘要：`research_goals / innovations / technical_route`
- 指南贴合度：`matched / gaps / suggestions / fit_score`
- 技术摸底：`literature/patent` 对比分析与水平定位
- 对话问答：按 `evaluation_id` 查询，回答中返回 `file + page + snippet`
- HTML 报告：正式报告升级为审阅工作台，左侧展示正文，右侧展示摘要、维度结论、专家关注问答；调试信息单独输出到 debug 页面

### 3. 并行执行

同一次评审中，文档索引、九维检查、划重点、指南匹配、技术摸底采用并发任务执行，最后统一合并。

### 4. 项目画像自适应

- 在九维检查前，先基于正文章节做规则式 `project_profile` 推断
- 首批支持：`tech_rnd / platform / science_popularization / demonstration / generic`
- 画像只改变评审口径，不改变九维框架本身
- 当前优先解决“平台建设类/科普实施类项目不应因缺少独立技术路线而被机械低分”

### 5. 可追溯与可降级

- 关键结论都落到 `evidence` 结构
- 外部检索不可用时进入降级模式，仅基于申报书与本地规则输出，并标注 `partial`

### 6. 审阅工作台

- 正式 HTML 报告采用左右双栏：
  - 左侧：正文阅读区
  - 右侧：评审结果区
- 右侧任何 `evidence/citation` 都应支持跳转到左侧对应页
- 跳转后应尽量高亮对应 `snippet`，便于专家快速核验
- 第一阶段优先基于 `page_chunks` 构建正文阅读区
- 若后续接入 PDF 原文阅读器，应保持相同的证据跳转协议，不改变上层结果结构

## API 与工具调用说明

- 当前服务通过普通 LLM API 调用模型，不会“自动”调用工具。
- 若要使用搜索（文献/专利/指南），需由服务端 `ToolGateway` 执行工具并回注结果给模型。
- 因此“API 模式”可以做工具调用，但必须在后端编排，不是模型自行联网。

## 输入输出（主接口）

### 输入关键字段

- `project_id`、`zndm` 或上传文件
- `dimensions`、`weights`、`include_sections`
- `enable_highlight`
- `enable_industry_fit`
- `enable_benchmark`
- `enable_chat_index`

### 真实数据入口

- 支持按 `zndm` 查询真实已提交项目后批量评审
- 项目列表来源：`Sb_Jbxx + Sb_Sbzt + sys_guide`
- 正文路径固定为：`/mnt/remote_corpus/{year}/sbs/{id}/{id}.docx`

### 输出关键字段

- `overall_score`、`grade`、`dimension_scores`
- `highlights`
- `industry_fit`
- `benchmark`
- `evidence`
- `chat_ready`
- `partial`、`errors`

### 正文联动所需字段

- `page_chunks`
- `evidence[].page`
- `evidence[].snippet`
- `expert_qna[].citations[].page`
- `expert_qna[].citations[].snippet`

## 相关文档

- [架构设计 →](02-architecture.md)
- [评审维度详解 →](03-dimensions.md)
- [检查器设计 →](04-checkers.md)
- [评分器设计 →](05-scorer.md)
- [Agent 设计 →](06-agent.md)
- [正文解析器设计 →](07-parsers.md)
- [API 接口文档 →](08-api.md)
- [测试文档 →](09-testing.md)
