# 第四步：简报编排层（Python/LangChain）

## 一、服务定位

目标是将第二步（热点迁移）与第三步（宏观研判）合并为可直接给领导阅读的统一简报输出。

## 二、业务流程图

```text
读取 Step2 与 Step3 输出
	-> 规则层拼装 headline/keyMessages/riskSnapshot
	-> (可选) LLM 增强改写管理语言
	-> 写入 leadership_brief_step4.json
```

## 三、核心技术选型

- 编排层：Python 规则模板
- 增强层：LangChain + LLM（可选）
- 输出层：结构化 JSON，供 API 和前端直接消费

## 四、核心代码结构

- 服务实现: src/services/sandbox/briefing_orchestrator_step4.py
- 运行入口: scripts/sandbox_briefing_step4.py
- 联动入口: scripts/sandbox_run_step3_step4.py

## 五、设计思路

1. 规则编排（无 LLM 也可跑）
- 汇总热点迁移主路径（top movements）
- 汇总高风险和中风险主题数量与重点主题
- 生成 headline、keyMessages、riskSnapshot

2. LLM 增强（可选）
- 若 `.env` 中配置可用 `LLM_*`（如 qwen/openai/anthropic 等），自动把规则简报改写为更自然的管理话术。
- 若未配置 API Key 或调用失败，自动回退规则简报，并在输出标记 `llmEnhanced=false`。

## 六、环境变量

- BRIEFING_STEP2_PATH
- BRIEFING_STEP3_PATH
- BRIEFING_OUTPUT_PATH
- BRIEFING_TOP_MOVEMENTS

LLM 相关统一使用项目全局 `.env`：

- LLM_PROVIDER
- LLM_MODEL
- LLM_API_KEY
- LLM_BASE_URL
- LLM_TEMPERATURE
- LLM_MAX_TOKENS
- LLM_TIMEOUT
- LLM_MAX_RETRIES

说明：
- 不配置这些变量也可运行（使用代码内默认值）。

## 七、运行示例

```bash
python scripts/sandbox_briefing_step4.py
```

```bash
python scripts/sandbox_run_step3_step4.py
```

## 八、输出结构

- meta: 输入文件、LLM 信息、是否启用 LLM 增强
- brief: 最终对外简报（LLM 可用则为增强版，否则为规则版）
- ruleBrief: 规则版简报（始终保留，便于审计）
- step2: 第二步关键信息摘录
- step3: 第三步关键信息摘录

## 九、上下游依赖关系

- 上游依赖：Step2 热点迁移结果、Step3 结构化规则发现。
- 下游输出：前端简报卡片、批处理结果、Step5 问答上下文补充。

## 十、与技术路径对应

- 第一步（GDS）: Step2 已完成热点迁移图算法。
- 第二步（Python/LangChain 中间层）: 本步骤实现跨模块编排和可选 LLM 增强。
- 第三步（业务逻辑对齐）: Step3 规则 findings 已被纳入并可直接映射到管理动作。
