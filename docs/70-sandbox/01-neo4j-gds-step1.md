# Neo4j GDS 第一步（Sandbox）

## 一、服务定位

本阶段目标是完成 Neo4j + GDS 的基础可用性验证，为后续“热点迁移、转化率预警、人才断层分析”提供可执行的图算法底座。

## 二、业务流程图

```text
读取 .env 配置
	-> Neo4j 连通性检查
	-> GDS 版本与过程检查
	-> 小规模图投影
	-> PageRank 烟囱测试
	-> 清理临时图并输出结果
```

## 三、核心技术选型

- 图数据库：Neo4j
- 图算法库：GDS
- 实现语言：Python
- 查询语言：Cypher

## 四、核心代码结构

- 实现代码: src/services/sandbox/neo4j_gds_preflight.py
- 兼容入口: scripts/neo4j_gds_preflight.py

## 五、运行示例

建议在项目虚拟环境执行：

```bash
python scripts/neo4j_gds_preflight.py
```

或直接执行模块：

```bash
python -m src.services.sandbox.neo4j_gds_preflight
```

## 六、配置要求

请在项目 .env 中配置：

```env
NEO4J_URI=neo4j://192.168.0.198:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=你的密码
NEO4J_DATABASE=neo4j
NEO4J_GDS_GRAPH=gds_preflight_graph
GDS_SAMPLE_NODE_LIMIT=20000
GDS_SAMPLE_REL_LIMIT=50000
```

## 七、检查项

脚本会依次做以下检查：

1. Neo4j 连通性
2. Neo4j 组件信息
3. GDS 版本可读性（兼容多版本返回字段）
4. GDS 过程列表与关键算法可用性
5. 小规模图投影与 PageRank 烟囱测试
6. 清理临时投影图

## 八、成功标准

出现以下关键输出即可进入第二步：

- [OK] Neo4j 连通性通过
- [OK] GDS 可用，版本: ...
- [OK] 样本图投影成功: nodes=..., relationships=...
- [OK] PageRank 烟囱测试通过
- [SUCCESS] 第一步完成：Neo4j + GDS 环境已可用于后续图算法研发

## 九、上下游依赖关系

- 上游依赖：`.env` 中 Neo4j 连接信息。
- 下游输出：作为 Step2（热点迁移）的执行前置校验。

## 十、常见问题

1. gds.version 失败
- 处理：确认 plugins 中已安装 GDS 且 neo4j.conf 放行 gds.*。

2. graph.project.cypher 报端点不在节点集合
- 当前实现已通过“同一 ID 范围诱导子图 + validateRelationships: false”规避。

3. 本机 python 命令不存在
- 处理：使用 python3，或直接使用项目虚拟环境解释器。
