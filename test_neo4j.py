# from neo4j import GraphDatabase

# uri = "bolt://192.168.0.198:7687"
# username = "neo4j"
# password = "11223322"   # ⚠️ 用你在198上设置的

# driver = GraphDatabase.driver(uri, auth=(username, password))

# def test():
#     with driver.session() as session:
#         result = session.run("RETURN 1 as num")
#         print(result.single()["num"])

# if __name__ == "__main__":
#     test()

from neo4j import GraphDatabase
import json


class Neo4jSchemaExtractor:
    def __init__(self, uri, username, password):
        self.driver = GraphDatabase.driver(uri, auth=(username, password))

    def close(self):
        self.driver.close()

    def _quote_identifier(self, identifier):
        """转义 Cypher 标识符，支持包含 / 等特殊字符的标签名。"""
        return str(identifier).replace("`", "``")

    # 获取所有节点类型
    def get_labels(self):
        with self.driver.session() as session:
            result = session.run("CALL db.labels()")
            return [r[0] for r in result]

    # 获取所有关系类型
    def get_relationship_types(self):
        with self.driver.session() as session:
            result = session.run("CALL db.relationshipTypes()")
            return [r[0] for r in result]

    # 获取某个节点的属性
    def get_node_properties(self, label):
        safe_label = self._quote_identifier(label)
        with self.driver.session() as session:
            result = session.run(f"""
            MATCH (n:`{safe_label}`)
            UNWIND keys(n) AS key
            RETURN DISTINCT key
            """)
            return [r["key"] for r in result]

    # 获取关系结构（起点-关系-终点）
    def get_relationship_patterns(self):
        with self.driver.session() as session:
            result = session.run("""
            MATCH (a)-[r]->(b)
            RETURN DISTINCT labels(a) AS from_labels,
                            type(r) AS rel_type,
                            labels(b) AS to_labels
            """)
            patterns = []
            for r in result:
                patterns.append({
                    "from": r["from_labels"],
                    "relation": r["rel_type"],
                    "to": r["to_labels"]
                })
            return patterns

    # 主函数：构建完整schema
    def extract_schema(self):
        schema = {}

        labels = self.get_labels()
        rels = self.get_relationship_types()

        schema["nodes"] = {}
        for label in labels:
            try:
                schema["nodes"][label] = {
                    "properties": self.get_node_properties(label)
                }
            except Exception as e:
                schema["nodes"][label] = {
                    "properties": [],
                    "error": str(e),
                }

        schema["relationships"] = {
            "types": rels,
            "patterns": self.get_relationship_patterns()
        }

        return schema


if __name__ == "__main__":
    uri = "bolt://192.168.0.198:7687"
    username = "neo4j"
    password = "11223322"  # 改成你的密码

    extractor = Neo4jSchemaExtractor(uri, username, password)

    schema = extractor.extract_schema()

    # ===== 控制台打印 =====
    print("\n========== 知识图谱结构 ==========\n")

    print("【节点类型】")
    for node, info in schema["nodes"].items():
        print(f"- {node}: {info['properties']}")

    print("\n【关系类型】")
    for rel in schema["relationships"]["types"]:
        print(f"- {rel}")

    print("\n【关系结构】")
    for p in schema["relationships"]["patterns"]:
        print(f"{p['from']} -[{p['relation']}]-> {p['to']}")

    # ===== 保存为JSON =====
    with open("schema.json", "w", encoding="utf-8") as f:
        json.dump(schema, f, ensure_ascii=False, indent=4)

    print("\n✅ 已导出 schema.json")