# 第二步：热点迁移最小闭环

## 一、服务定位

本步骤在第一步 GDS 预检通过后执行，目标是实现“两个时间窗的热点迁移检测”，并生成可用于前端桑基图的结果。

## 二、业务流程图

```text
选择可用投影策略
	-> 构建 A/B 两个时间窗图投影
	-> 运行社区发现算法
	-> 计算跨窗迁移链路
	-> 输出 sankey 与 insightDraft
```

## 三、核心技术选型

- 图算法：Leiden / Louvain（自动回退）
- 图查询：Cypher
- 输出：JSON（含 Sankey 节点与边）

## 四、核心代码结构

- 服务实现: src/services/sandbox/hotspot_migration_step2.py
- 运行入口: scripts/sandbox_hotspot_migration.py

## 五、默认逻辑

实现默认基于以下图谱建模假设：

- 主题节点: `Fund/Program`
- 项目节点: Project
- 关系: Project-[:funded_by]->`Fund/Program`
- 项目时间属性: `Project.period` 前 4 位年份

系统会自动在 `guideName / department / office / 兼容模板` 中择优选择可用策略。

## 六、关键配置来源

Step2 参数默认写在代码中（`hotspot_migration_step2.py`），不依赖 `HOTSPOT_*` 环境变量。

当前默认值：

- 时间窗: `2023-2023` → `2024-2024`
- 策略: `auto`
- 阈值: `minOverlap=1`, `minJaccard=0.01`
- 限流: `maxEdges=150000`, `topCommunities=8`
- 输出: `debug_sandbox/hotspot_migration_real_schema_2023_to_2024.json`

仅 Neo4j 连接信息继续来自 `.env`：

```env
NEO4J_URI=neo4j://192.168.0.198:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=你的密码
NEO4J_DATABASE=neo4j
```

说明：

- `maxEdges` 用于限制投影关系行数，保障大图在固定时间内完成。
- 当前默认限制为 `150000`，在线上建议保留该限制。

## 七、扩展方式（重点）

若后续需要改默认模板或阈值，请直接修改代码常量（`DEFAULT_*`）并回归运行 Step2。

## 八、运行示例

```bash
python scripts/sandbox_hotspot_migration.py
```

成功后会输出：

- debug_sandbox 下的 JSON 结果文件
- 控制台 insight 草稿（可直接作为大模型输入上下文）

## 九、输出结构

JSON 主要字段：

- meta: 时间窗与阈值信息
- projection: 两个窗口的投影规模
- communities: 每窗社区及关键词摘要
- sankey: 可直接给 ECharts Sankey 的 nodes/links
- insightDraft: 自动生成的研判草稿

## 十、上下游依赖关系

- 上游依赖：Step1 的 GDS 可用性、Neo4j 图谱数据。
- 下游输出：Step3 规则研判、Step4 领导简报、前端 Sankey 可视化。

## 十一、下一步建议

完成本步后进入“转化率预警”最小闭环：

1. 定义申报→立项→验收→转化路径查询模板
2. 计算路径通达率与低转化高热风险分
3. 输出规则触发证据，给 LLM 生成政策建议

## 十二、当前仓库已落地的真实 schema 模板

当前实现已升级为“自动选策略”模式，会优先在以下真实 schema 基底中择优：

- `Project.guideName` 共现
- `Project.department` 共现
- `Project.office` 共现
- 旧版 `Topic/HAS_TOPIC` 兼容模板

默认逻辑会在两个时间窗都成立的前提下，选择“节点数和边数都非零”的策略，避免出现空图或单点社区。

旧版固定模板仍保留为兼容配置，但已不再是主路径。

如果后续补充了真正的主题节点（如 Topic/SciEntity 与 Project 的直接映射），可以在策略目录中继续新增一个更强的主题投影模式，而不需要改主流程。
