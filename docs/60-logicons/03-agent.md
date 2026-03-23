# 🤖 逻辑自洽 Agent 设计

## 概述

ConsistencyAgent 是逻辑自洽服务的核心编排组件，负责串联文档解析、实体抽取、图谱构建、规则校验与冲突解释生成。

## Agent 设计思路

1. **全局视角**：将整份文档纳入同一上下文处理。
2. **混合推理**：规则引擎负责确定性判断，LLM 负责语义冲突解释。
3. **可复核输出**：冲突结论必须带证据链，便于人工复核。

---

## 流程编排

```
┌────────────────────────────────────────────────────────────┐
│                    ConsistencyAgent                        │
└────────────────────────────────────────────────────────────┘
             │
             ▼
  1) parse_document(file)       -> sections/tables
  2) extract_entities(parsed)   -> entities
  3) build_graph(entities)      -> temporary graph
  4) run_rules(graph)           -> deterministic conflicts
  5) explain_conflicts()        -> semantic explanations
  6) aggregate_report()         -> final report
```

---

## 核心代码结构

```python
from typing import Dict, Any, List


class ConsistencyAgent:
    """逻辑自洽校验 Agent"""

    def __init__(self, parser, extractor, graph_builder, rule_engine, llm):
        self.parser = parser
        self.extractor = extractor
        self.graph_builder = graph_builder
        self.rule_engine = rule_engine
        self.llm = llm

    async def run(self, file_data: bytes, file_type: str) -> Dict[str, Any]:
        parsed = await self.parser.parse(file_data=file_data, file_type=file_type)
        entities = await self.extractor.extract(parsed)
        graph = self.graph_builder.build(entities=entities)

        deterministic_conflicts = self.rule_engine.check(graph)
        explained_conflicts = await self._explain(deterministic_conflicts, graph)

        return {
            "conflicts": explained_conflicts,
            "summary": self._summary(explained_conflicts),
            "graph_stats": {
                "entity_count": len(graph.get("entities", [])),
                "relation_count": len(graph.get("relations", [])),
            },
        }

    async def _explain(self, conflicts: List[Dict[str, Any]], graph: Dict[str, Any]) -> List[Dict[str, Any]]:
        """调用 LLM 生成冲突解释与修正建议"""
        if not conflicts:
            return []
        return conflicts

    def _summary(self, conflicts: List[Dict[str, Any]]) -> Dict[str, int]:
        return {
            "high": sum(1 for c in conflicts if c.get("severity") == "high"),
            "medium": sum(1 for c in conflicts if c.get("severity") == "medium"),
            "low": sum(1 for c in conflicts if c.get("severity") == "low"),
        }
```

---

## 使用示例

```python
agent = ConsistencyAgent(
    parser=section_parser,
    extractor=entity_extractor,
    graph_builder=kg_builder,
    rule_engine=consistency_rule_engine,
    llm=default_llm,
)

result = await agent.run(file_data=doc_bytes, file_type="docx")
print(result["summary"])
```

---

## 输出结构约定

| 字段 | 类型 | 说明 |
|------|------|------|
| `conflicts` | List | 冲突列表（含规则编码、证据、建议） |
| `summary` | Object | 按严重等级聚合统计 |
| `graph_stats` | Object | 实体和关系规模 |
