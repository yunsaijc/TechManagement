# 第三步：通用宏观研判引擎

## 一、服务定位

目标是把“固态电池低转化”“量子人才断层”这类样例抽象成通用规则，对多个主题自动输出风险发现。

## 二、业务流程图

```text
按时间窗提取主题指标
	-> 计算增长/转化/人才结构特征
	-> 规则引擎逐条匹配
	-> 输出 findings 与 briefing
	-> 提供 Step4/Step5 继续消费
```

## 三、核心技术选型

- 图数据访问：Neo4j + Cypher
- 逻辑层：规则引擎（代码规则库）
- 输出：结构化 JSON（findings / grouped findings / briefing）

## 四、核心代码结构

- 服务实现: src/services/sandbox/macro_insight_step3.py
- 运行入口: scripts/sandbox_macro_insight_step3.py

## 五、设计思路

1. 增长-转化风险检测（通用）
- 当主题申报量显著增长且转化率偏低时，自动生成高风险 finding。

2. 人才结构断层检测（通用）
- 基于人员规模、骨干占比、协作强度，检测“结构偏弱”主题。

3. 规则库化扩展（当前阶段）
- 已从最初 2 条样板规则扩展到 15+ 条（当前 17 条）可运行规则，覆盖：
- 高增长低转化
- 申报激增预警
- 申报明显回落
- 高热度零产出
- 转化率下滑
- 新兴高转化机会
- 高增长高转化示范
- 人才结构断层
- 高层次人才不足
- 中坚骨干缺失
- 协作网络偏弱

4. 结构化输出
- 输出 findings JSON（证据 + 建议），并额外生成 briefing（headline / keyPoints / actions），可直接用于前端卡片和自动简报。

## 六、环境变量

第三步现在以代码默认值为主，不要求把规则阈值全部写进 `.env`。

可选覆盖项仅保留在代码中定义的字段，主要用于临时实验或特殊部署场景：

- `INSIGHT_TOPIC_EXPR`
- `INSIGHT_OUTPUT_PATH`
- `INSIGHT_YEAR_A_START` / `INSIGHT_YEAR_A_END`
- `INSIGHT_YEAR_B_START` / `INSIGHT_YEAR_B_END`
- `INSIGHT_BRIEF_MAX_FINDINGS`

快速模式相关（默认开启，用于避免超时并优先稳定产出 JSON）：

- `INSIGHT_FAST_MODE`（默认 `true`）
- `INSIGHT_FAST_PROJECT_LIMIT`（默认 `30000`）
- `INSIGHT_FAST_FOCUS_TOPICS`（默认 `80`）
- `INSIGHT_FAST_ENABLE_COLLAB`（默认 `false`，快速模式下默认关闭协作重查询）

默认规则与阈值已直接写入 [src/services/sandbox/macro_insight_step3.py](src/services/sandbox/macro_insight_step3.py)，因此即使不额外配置也能运行。

## 七、运行示例

```bash
python scripts/sandbox_macro_insight_step3.py
```

一键串行跑通 Step3 + Step4：

```bash
python scripts/sandbox_run_step3_step4.py
```

## 八、输出结构

- `meta`: 时间窗、主题表达式、阈值
- `summary`: 发现总数与风险等级统计
- `briefing`: 面向领导阅读的简报摘要、重点条目和建议动作
- `findings`: 规则命中条目（type / severity / topic / evidence / suggestion）
- `findingsGrouped`: 按 `risk / opportunity / talent / conversion` 分组后的命中条目
- `data`: 各主题窗口指标和人才指标原始数据

## 九、上下游依赖关系

- 上游依赖：Step2 的热点迁移数据和 Neo4j 主题指标。
- 下游输出：Step4 简报编排、Step5 GraphRAG 上下文增强。

## 十、可扩展点

1. 新增规则类型
- 在 `build_findings()` 中新增规则分支即可。

2. 规则治理建议
- 下一阶段可将规则拆分到独立规则目录（rule catalog），并支持启停与阈值分组。

3. 替换主题表达式
- 通过 `INSIGHT_TOPIC_EXPR` 切换到任何主题维度，不改代码。

4. 接入 LLM 研判文案
- 现在已经有可直接消费的 briefing 结构，后续只需把它交给模板系统或 LLM 重写即可。
