# 🏗️ 正文评审服务架构

## 架构目标

在现有评审服务内“融合”新能力，而不是外挂新服务：

- 保留九维评审主链路
- 同次请求内完成划重点、技术摸底；指南贴合能力保留但默认不启用
- 支持评审后专家问答（带页码证据）
- 输出一份统一 `EvaluationResult`
- 保持现有聊天问答主链路稳定，只在其前后增加轻量增强层

## 整体架构

```
┌──────────────────────────────────────────────────────────────────┐
│ API Layer (FastAPI)                                              │
│ /evaluate  /evaluate/file  /batch  /chat/ask                     │
└───────────────────────────────┬──────────────────────────────────┘
                                │
┌───────────────────────────────▼──────────────────────────────────┐
│ EvaluationAgent (Orchestrator)                                   │
│  1) 输入归一化  2) 画像路由  3) 并行调度  4) 结果合并            │
└───────┬──────────────┬──────────────┬──────────────┬─────────────┘
        │              │              │              │
        ▼              ▼              ▼              ▼
  Doc Indexer     Rubric Manager  Evidence Builder   9D Checkers
  (页码切片/索引)  (类型口径/权重)  (维度证据包)      (基于证据判断)
        │              │              │              │
        └──────────────┴──────────────┴──────────────┘
                               │
                               ▼
                    Highlight / Benchmark
                               │
                               ▼
                         Chat QA Runtime
                               │
                               ▼
             ToolGateway (doc_search / guide_search / tech_search)
```

## 分层说明

### Layer 1: API 路由层

- 组件：`src/app/routes/evaluation.py`
- 职责：参数校验、错误码映射、返回统一响应模型

### Layer 2: 编排层（核心）

- 组件：`src/services/evaluation/agent.py`
- 职责：
  - 组织并发任务
  - 聚合多模块输出
  - 维护任务降级与超时策略

### Layer 3: 评审与增强能力层

- 九维检查器：`src/services/evaluation/checkers/`
- Rubric 管理：按 `project_profile` 输出维度解释口径、必要项、缺失容忍规则
- 证据包构建：为评分、摘要、总评、问答提供统一 `evidence pack`
- 划重点：`src/services/evaluation/highlight/`
- 技术摸底：`src/services/evaluation/benchmark/`
- 问答能力：`src/services/evaluation/chat/`

### Layer 4: 工具网关层

- 组件：`src/services/evaluation/tools/gateway.py`
- 职责：
  - 统一调用 `doc_search / guide_search / tech_search`
  - 统一返回结构化证据，避免各模块各自接工具
  - 当前真实检索接线优先启用 `tech_search -> OpenAlex`

### Layer 5: 基础设施层

- 组件：`src/common/` 与 `src/services/evaluation/storage/`
- 职责：LLM、文档解析、数据库访问、结果持久化

## 并行执行模型

### 阶段划分

1. 阶段 A（关键路径）：文档解析、页码索引、项目画像识别
2. 阶段 B（关键路径）：按画像生成 `rubric` 并构建维度级 `evidence pack`
3. 阶段 C（并行）：九维评审、划重点、技术摸底
4. 阶段 D（合并）：统一打分、总结、证据去重与落盘

### 并发策略

- 使用 `asyncio.gather` + `Semaphore`
- 每个子任务单独超时
- 单任务失败不阻断总流程，结果标记 `partial=true`
- 聊天链路不参与本次评审并行重构，保持独立运行时入口，避免影响现有时延与稳定性

## 工具调用策略（关键说明）

当前模型 API 调用不会自动执行搜索工具。  
搜索能力通过服务端编排实现：

1. 模块请求 ToolGateway
2. ToolGateway 执行检索或外部 API 调用
3. 将结构化检索结果回注给模型生成结论

## 统一结果模型（融合输出）

主结果保持 `EvaluationResult`，扩展字段：

- `highlights`
- `industry_fit`（保留字段，默认不启用）
- `benchmark`
- `evidence`
- `chat_ready`
- `partial`
- `errors`

其中结果生成原则为：

- 评分、摘要、总评优先消费统一 `evidence pack`
- 聊天继续消费 `page_chunks/chat index`，只允许增加轻量问题路由与证据整理，不替换主回答链

## 存储与追溯

- 结果落盘仍用 `src/services/evaluation/storage/storage.py`
- 每次评审保存：
  - 评分结果
  - 结构化摘要
  - 技术摸底结论
  - 指南匹配结果（若显式启用）
  - 证据链（`file/page/snippet/source`）

## 降级策略

- 外部搜索不可用：禁用 `benchmark` 的在线检索，保留本地评审结果
- 指南正文不可可靠映射：不启用 `industry_fit` 主能力展示
- 解析失败：返回可定位错误信息与可恢复建议
- 若 `rubric` 所需证据不足，不强行输出确定性高分结论，应转为保守评分或标记材料不足

## 目录规划（融合后）

```
src/services/evaluation/
├── agent.py
├── checkers/
├── parsers/
├── scorers/
├── storage/
├── highlight/
│   ├── extractor.py
│   └── industry_fit.py
├── benchmark/
│   ├── retrievers.py
│   └── analyzer.py
├── chat/
│   ├── indexer.py
│   └── qa_agent.py
└── tools/
    ├── gateway.py
    └── search_client.py
```
