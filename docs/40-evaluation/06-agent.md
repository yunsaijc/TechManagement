# 🤖 EvaluationAgent 设计

## 角色定位

`EvaluationAgent` 是正文评审服务的统一编排器（Orchestrator），负责把原有九维评审与新增能力融合到一次执行中，输出单一 `EvaluationResult`。

## 核心职责

1. 输入归一化：解析 `project_id` / 上传文件、维度、权重、功能开关  
2. 文档准备：调用解析器完成章节提取与页码索引准备  
3. 并发调度：并行执行九维检查、划重点、指南贴合、技术摸底  
4. 结果合并：统一评分、总结、证据去重、异常归并  
5. 持久化：写入评审结果与证据链

## 编排流程

```
Step 1 读取项目与文档
Step 2 解析正文并建立页码索引
Step 3 并行执行
  - 9D Checkers
  - Highlight Extractor
  - Industry Fit Analyzer
  - Benchmark Analyzer
Step 4 汇总评分与建议
Step 5 写入 storage 并返回结果
```

## 并发策略

- 使用 `asyncio.gather` 并行任务  
- 通过 `Semaphore` 控制并发上限  
- 子任务级超时与重试  
- 单任务失败不阻断主流程，返回 `partial=true` 与 `errors[]`

## 与工具调用的关系

`EvaluationAgent` 不依赖模型“自动工具调用”。  
涉及检索时走服务端 `ToolGateway`：

- `doc_search`：申报书页码检索
- `guide_search`：产业指南检索
- `tech_search`：文献/专利检索

Agent 只接收结构化检索结果并完成分析与合并。

## 结果合并规则

合并后主结果包含：

- `dimension_scores`、`overall_score`、`grade`
- `highlights`
- `industry_fit`
- `benchmark`
- `evidence`（`file/page/snippet/source`）
- `chat_ready`
- `partial`、`errors`

## 异常与降级

- 无项目文档：提示改用 `/api/v1/evaluation/evaluate/file`
- 外部检索失败：关闭对应模块并标记 `partial`
- 解析失败：返回可定位错误信息，保留已完成模块输出

## 代码锚点

- 编排入口：`src/services/evaluation/agent.py`
- 维度检查：`src/services/evaluation/checkers/`
- 解析能力：`src/services/evaluation/parsers/`
- 存储：`src/services/evaluation/storage/`
