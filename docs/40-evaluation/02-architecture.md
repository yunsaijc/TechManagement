# 🏗️ 正文评审服务架构

## 架构目标

在现有评审服务内“融合”新能力，而不是外挂新服务：

- 保留九维评审主链路
- 同次请求内完成划重点、指南贴合、技术摸底
- 支持评审后专家问答（带页码证据）
- 输出一份统一 `EvaluationResult`

## 整体架构

```
┌──────────────────────────────────────────────────────────────────┐
│ API Layer (FastAPI)                                              │
│ /evaluate  /evaluate/file  /batch  /chat/ask                     │
└───────────────────────────────┬──────────────────────────────────┘
                                │
┌───────────────────────────────▼──────────────────────────────────┐
│ EvaluationAgent (Orchestrator)                                   │
│  1) 输入归一化  2) 并行调度  3) 结果合并  4) 存储落盘            │
└───────┬──────────────┬──────────────┬──────────────┬─────────────┘
        │              │              │              │
        ▼              ▼              ▼              ▼
  Doc Indexer      Highlight      Industry Fit     9D Checkers
  (页码切片/索引)   (目标/创新/路线) (指南匹配/缺口)  (原有维度评审)
        │
        ▼
   Chat QA Runtime  <---- Benchmark (文献/专利检索 + 对比)
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
- 划重点：`src/services/evaluation/highlight/`
- 指南贴合：`src/services/evaluation/highlight/industry_fit.py`
- 技术摸底：`src/services/evaluation/benchmark/`
- 问答能力：`src/services/evaluation/chat/`

### Layer 4: 工具网关层

- 组件：`src/services/evaluation/tools/gateway.py`
- 职责：
  - 统一调用 `doc_search / guide_search / tech_search`
  - 统一返回结构化证据，避免各模块各自接工具

### Layer 5: 基础设施层

- 组件：`src/common/` 与 `src/services/evaluation/storage/`
- 职责：LLM、文档解析、数据库访问、结果持久化

## 并行执行模型

### 阶段划分

1. 阶段 A（关键路径）：文档解析与页码索引
2. 阶段 B（并行）：九维评审、划重点、指南贴合、技术摸底
3. 阶段 C（合并）：统一打分、总结、证据去重与落盘

### 并发策略

- 使用 `asyncio.gather` + `Semaphore`
- 每个子任务单独超时
- 单任务失败不阻断总流程，结果标记 `partial=true`

## 工具调用策略（关键说明）

当前模型 API 调用不会自动执行搜索工具。  
搜索能力通过服务端编排实现：

1. 模块请求 ToolGateway
2. ToolGateway 执行检索或外部 API 调用
3. 将结构化检索结果回注给模型生成结论

## 统一结果模型（融合输出）

主结果保持 `EvaluationResult`，扩展字段：

- `highlights`
- `industry_fit`
- `benchmark`
- `evidence`
- `chat_ready`
- `partial`
- `errors`

## 存储与追溯

- 结果落盘仍用 `src/services/evaluation/storage/storage.py`
- 每次评审保存：
  - 评分结果
  - 结构化摘要
  - 指南匹配与摸底结论
  - 证据链（`file/page/snippet/source`）

## 降级策略

- 外部搜索不可用：禁用 `benchmark` 的在线检索，保留本地评审结果
- 指南库不可用：返回“待核验”并降低相关置信度
- 解析失败：返回可定位错误信息与可恢复建议

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
    └── gateway.py
```
