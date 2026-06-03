#!/usr/bin/env python3
"""第五步：GraphRAG 最小闭环实现。

能力：
1. 从自然语言问题中提取检索关键词。
2. 在 Neo4j 中检索种子节点并扩展 k-hop 子图。
3. 将子图序列化为上下文，交给 LangChain + LLM 生成结论。
4. 输出结构化 JSON（含可追溯子图证据）。
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    from dotenv import load_dotenv
except ModuleNotFoundError:
    def load_dotenv(*args: Any, **kwargs: Any) -> bool:
        return False

try:
    from src.common.llm.config import llm_config
    from src.common.llm.factory import get_llm_client
except ModuleNotFoundError:
    llm_config = None  # type: ignore[assignment]
    get_llm_client = None  # type: ignore[assignment]

try:
    from langchain_core.prompts import ChatPromptTemplate
except ModuleNotFoundError:
    ChatPromptTemplate = None  # type: ignore[assignment]

from neo4j import GraphDatabase
from neo4j.exceptions import Neo4jError


load_dotenv(Path(__file__).resolve().parents[3] / ".env")


DEFAULT_QUESTION = "请研判 2024 年我省基金项目中，哪些主题存在高增长低转化风险，并给出治理建议。"
DEFAULT_OUTPUT_PATH = "debug_sandbox/graph_rag_answer_step5.json"
DEFAULT_MAX_HOPS = 2
DEFAULT_SEED_LIMIT = 24
DEFAULT_SUBGRAPH_NODE_LIMIT = 220
DEFAULT_SUBGRAPH_REL_LIMIT = 500
DEFAULT_TOP_KEYWORDS = 8

MGMT_LABELS = {
    "Person",
    "Organization",
    "Org",
    "Project",
    "Output",
    "Paper",
    "Venue",
    "Fund/Program",
}

SCI_LABELS = {
    "Concept",
    "Dataset",
    "DisciplineL1",
    "DisciplineL2",
    "DisciplineL3",
    "Method",
    "Policy",
    "SciEntity",
    "Theory",
    "Entity",
}

MGMT_REL_TYPES = {
    "works_for",
    "undertakes",
    "produces",
    "authored_by",
    "funded_by",
    "published_in",
    "collaborates_with",
    "reviews",
}

SCI_REL_TYPES = {
    "RELATES_TO_DISCIPLINE",
    "SUB_OF",
    "WD_FIELD_OF_WORK",
    "WD_INSTANCE_OF",
    "WD_MAIN_SUBJECT",
    "WD_PART_OF",
    "WD_RELEVANT_TOPIC",
    "WD_STUDIES",
    "WD_SUBCLASS_OF",
    "WD_TOPIC_MAIN_CATEGORY",
}

BRIDGE_REL_TYPES = {"involves_concept"}

DISPLAY_FIELDS = [
    "guideName",
    "projectName",
    "name",
    "title",
    "department",
    "office",
    "keyword",
    "keywords",
    "subject",
    "label",
    "display_name_zh",
    "label_zh",
    "theme",
    "topic",
    "period",
    "基金名称",
]

DOMAIN_HINTS = [
    "基金",
    "项目",
    "主题",
    "指南",
    "转化",
    "风险",
    "增长",
    "申报",
    "立项",
    "验收",
    "专利",
    "成果",
    "青年",
    "面上",
]

STOPWORDS = {
    "请",
    "我们",
    "你们",
    "这个",
    "那个",
    "什么",
    "哪些",
    "如何",
    "以及",
    "进行",
    "分析",
    "研判",
    "建议",
    "项目",
    "领域",
    "情况",
    "问题",
    "风险",
}


@dataclass
class GraphRAGConfig:
    uri: str
    user: str
    password: str
    database: str
    question: str
    output_path: str
    max_hops: int
    seed_limit: int
    subgraph_node_limit: int
    subgraph_rel_limit: int
    top_keywords: int


def getenv_required(name: str, default: str | None = None) -> str:
    value = os.getenv(name, default)
    if not value:
        raise ValueError(f"缺少环境变量: {name}")
    return value


def build_config() -> GraphRAGConfig:
    return GraphRAGConfig(
        uri=getenv_required("NEO4J_URI", "neo4j://192.168.0.198:7687"),
        user=getenv_required("NEO4J_USER", "neo4j"),
        password=getenv_required("NEO4J_PASSWORD"),
        database=getenv_required("NEO4J_DATABASE", "neo4j"),
        question=os.getenv("GRAPHRAG_QUESTION", DEFAULT_QUESTION),
        output_path=os.getenv("GRAPHRAG_OUTPUT_PATH", DEFAULT_OUTPUT_PATH),
        max_hops=max(1, min(3, int(os.getenv("GRAPHRAG_MAX_HOPS", str(DEFAULT_MAX_HOPS))))),
        seed_limit=max(5, int(os.getenv("GRAPHRAG_SEED_LIMIT", str(DEFAULT_SEED_LIMIT)))),
        subgraph_node_limit=max(50, int(os.getenv("GRAPHRAG_SUBGRAPH_NODE_LIMIT", str(DEFAULT_SUBGRAPH_NODE_LIMIT)))),
        subgraph_rel_limit=max(100, int(os.getenv("GRAPHRAG_SUBGRAPH_REL_LIMIT", str(DEFAULT_SUBGRAPH_REL_LIMIT)))),
        top_keywords=max(3, int(os.getenv("GRAPHRAG_TOP_KEYWORDS", str(DEFAULT_TOP_KEYWORDS)))),
    )


def ensure_output_dir(path: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)


def extract_keywords(question: str, top_k: int) -> list[str]:
    tokens = re.findall(r"20\d{2}|[\u4e00-\u9fff]{2,10}|[A-Za-z][A-Za-z0-9_-]{2,}", question)
    normalized: list[str] = []
    seen: set[str] = set()

    # 优先收录领域关键词，避免中文长短语导致检索失焦。
    for hint in DOMAIN_HINTS:
        if hint in question:
            seen.add(hint)
            normalized.append(hint)
            if len(normalized) >= top_k:
                return normalized

    for token in tokens:
        key = token.strip()
        if not key or key in STOPWORDS:
            continue
        if re.fullmatch(r"[\u4e00-\u9fff]{6,10}", key):
            # 对较长中文短语做 2-4 字切片，增强命中率。
            for size in (4, 3, 2):
                for idx in range(0, len(key) - size + 1):
                    part = key[idx : idx + size]
                    if part in STOPWORDS:
                        continue
                    low = part.lower()
                    if low in seen:
                        continue
                    seen.add(low)
                    normalized.append(part)
                    if len(normalized) >= top_k:
                        return normalized
            continue
        lower_key = key.lower()
        if lower_key in seen:
            continue
        seen.add(lower_key)
        normalized.append(key)
        if len(normalized) >= top_k:
            break

    if not normalized:
        return ["基金", "项目", "主题"][:top_k]
    return normalized


def _pick_label(props: dict[str, Any], labels: list[str], node_id: int) -> str:
    for field in DISPLAY_FIELDS:
        if field in props and props[field] not in (None, ""):
            return str(props[field])
    if labels:
        return f"{labels[0]}#{node_id}"
    return str(node_id)


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    return str(value)


def fetch_seed_nodes(session: Any, keywords: list[str], seed_limit: int) -> list[dict[str, Any]]:
    if not keywords:
        return []

    query = """
    UNWIND $keywords AS kw
    MATCH (n)
    WHERE any(lbl IN labels(n) WHERE lbl IN ['Project', 'Person', 'Fund/Program', 'Topic'])
      AND any(k IN keys(n)
              WHERE k IN $display_fields
                AND toLower(toString(n[k])) CONTAINS toLower(kw))
    RETURN DISTINCT id(n) AS id, labels(n) AS labels, properties(n) AS props
    LIMIT $seed_limit
    """

    rows = session.run(
        query,
        {
            "keywords": keywords,
            "display_fields": DISPLAY_FIELDS,
            "seed_limit": seed_limit,
        },
    )

    seeds: list[dict[str, Any]] = []
    for row in rows:
        node_id = int(row["id"])
        labels = [str(x) for x in row["labels"]]
        props = _json_safe(dict(row["props"] or {}))
        seeds.append(
            {
                "id": node_id,
                "labels": labels,
                "label": _pick_label(props, labels, node_id),
                "props": props,
            }
        )
    return seeds


def fetch_subgraph(session: Any, seed_ids: list[int], max_hops: int, node_limit: int, rel_limit: int) -> dict[str, list[dict[str, Any]]]:
    if not seed_ids:
        return {"nodes": [], "relationships": []}

    node_query = f"""
    MATCH (s)
    WHERE id(s) IN $seed_ids
    MATCH p=(s)-[*1..{max_hops}]-(n)
    UNWIND nodes(p) AS x
    RETURN DISTINCT id(x) AS id, labels(x) AS labels, properties(x) AS props
    LIMIT $node_limit
    """

    rel_query = f"""
    MATCH (s)
    WHERE id(s) IN $seed_ids
    MATCH p=(s)-[*1..{max_hops}]-(n)
    UNWIND relationships(p) AS r
    RETURN DISTINCT id(startNode(r)) AS source,
                    type(r) AS rel_type,
                    id(endNode(r)) AS target,
                    properties(r) AS props
    LIMIT $rel_limit
    """

    node_rows = session.run(node_query, {"seed_ids": seed_ids, "node_limit": node_limit})
    rel_rows = session.run(rel_query, {"seed_ids": seed_ids, "rel_limit": rel_limit})

    nodes: list[dict[str, Any]] = []
    for row in node_rows:
        node_id = int(row["id"])
        labels = [str(x) for x in row["labels"]]
        props = _json_safe(dict(row["props"] or {}))
        nodes.append(
            {
                "id": node_id,
                "labels": labels,
                "label": _pick_label(props, labels, node_id),
                "props": props,
            }
        )

    rels: list[dict[str, Any]] = []
    for row in rel_rows:
        rels.append(
            {
                "source": int(row["source"]),
                "target": int(row["target"]),
                "type": str(row["rel_type"]),
                "props": _json_safe(dict(row["props"] or {})),
            }
        )

    return {"nodes": nodes, "relationships": rels}


def serialize_subgraph(subgraph: dict[str, list[dict[str, Any]]], max_nodes: int = 60, max_rels: int = 120) -> str:
    nodes = subgraph.get("nodes", [])[:max_nodes]
    rels = subgraph.get("relationships", [])[:max_rels]

    node_lines = [f"{n['id']} | {','.join(n['labels'])} | {n['label']}" for n in nodes]
    rel_lines = [f"{r['source']} -[{r['type']}]-> {r['target']}" for r in rels]

    return (
        "[NODES]\n"
        + "\n".join(node_lines)
        + "\n\n[RELATIONSHIPS]\n"
        + "\n".join(rel_lines)
    )


def split_subgraph_layers(subgraph: dict[str, list[dict[str, Any]]]) -> dict[str, dict[str, list[dict[str, Any]]]]:
    nodes = subgraph.get("nodes", [])
    rels = subgraph.get("relationships", [])

    layers = {
        "management": {"nodes": [], "relationships": []},
        "scientific": {"nodes": [], "relationships": []},
        "bridge": {"nodes": [], "relationships": []},
        "other": {"nodes": [], "relationships": []},
    }

    node_layer_by_id: dict[int, str] = {}
    for node in nodes:
        node_id = int(node.get("id", -1))
        labels = set([str(x) for x in (node.get("labels") or [])])
        if labels & MGMT_LABELS:
            layer = "management"
        elif labels & SCI_LABELS:
            layer = "scientific"
        else:
            layer = "other"
        node_layer_by_id[node_id] = layer
        layers[layer]["nodes"].append(node)

    for rel in rels:
        rel_type = str(rel.get("type", ""))
        source = int(rel.get("source", -1))
        target = int(rel.get("target", -1))
        s_layer = node_layer_by_id.get(source, "other")
        t_layer = node_layer_by_id.get(target, "other")

        if rel_type in BRIDGE_REL_TYPES or {s_layer, t_layer} == {"management", "scientific"}:
            layer = "bridge"
        elif rel_type in MGMT_REL_TYPES or (s_layer == "management" and t_layer == "management"):
            layer = "management"
        elif rel_type in SCI_REL_TYPES or (s_layer == "scientific" and t_layer == "scientific"):
            layer = "scientific"
        else:
            layer = "other"

        layers[layer]["relationships"].append(rel)

    return layers


def _layer_lines(nodes: list[dict[str, Any]], rels: list[dict[str, Any]], max_nodes: int, max_rels: int) -> str:
    node_lines = [
        f"{int(n.get('id', -1))} | {','.join([str(x) for x in (n.get('labels') or [])])} | {str(n.get('label', ''))}"
        for n in nodes[:max_nodes]
    ]
    rel_lines = [
        f"{int(r.get('source', -1))} -[{str(r.get('type', ''))}]-> {int(r.get('target', -1))}"
        for r in rels[:max_rels]
    ]
    return "[NODES]\n" + "\n".join(node_lines) + "\n[RELATIONSHIPS]\n" + "\n".join(rel_lines)


def serialize_subgraph_dual_layer(subgraph: dict[str, list[dict[str, Any]]], max_nodes: int = 40, max_rels: int = 80) -> tuple[str, dict[str, Any]]:
    layers = split_subgraph_layers(subgraph)
    text = (
        "[MANAGEMENT_LAYER]\n"
        + _layer_lines(layers["management"]["nodes"], layers["management"]["relationships"], max_nodes, max_rels)
        + "\n\n[SCIENTIFIC_LAYER]\n"
        + _layer_lines(layers["scientific"]["nodes"], layers["scientific"]["relationships"], max_nodes, max_rels)
        + "\n\n[BRIDGE_LAYER]\n"
        + _layer_lines(layers["bridge"]["nodes"], layers["bridge"]["relationships"], max_nodes, max_rels)
    )
    stats = {
        "management": {
            "nodes": len(layers["management"]["nodes"]),
            "relationships": len(layers["management"]["relationships"]),
        },
        "scientific": {
            "nodes": len(layers["scientific"]["nodes"]),
            "relationships": len(layers["scientific"]["relationships"]),
        },
        "bridge": {
            "nodes": len(layers["bridge"]["nodes"]),
            "relationships": len(layers["bridge"]["relationships"]),
        },
        "other": {
            "nodes": len(layers["other"]["nodes"]),
            "relationships": len(layers["other"]["relationships"]),
        },
    }
    return text, stats


def _build_llm() -> Any | None:
    if llm_config is None or get_llm_client is None:
        return None

    if not llm_config.provider or not llm_config.api_key:
        return None

    try:
        return get_llm_client(
            provider=llm_config.provider,
            model=llm_config.model,
            api_key=llm_config.api_key,
            base_url=llm_config.base_url,
            temperature=float(llm_config.temperature),
            max_tokens=int(llm_config.max_tokens),
            timeout=float(llm_config.timeout),
            max_retries=int(llm_config.max_retries),
        )
    except Exception as exc:
        print(f"[WARN] Step5 初始化 LLM 客户端失败: {exc}")
        return None


def answer_with_graphrag(question: str, context_text: str) -> dict[str, Any]:
    if ChatPromptTemplate is None:
        return {
            "answer": "当前环境未安装 LangChain Prompt 组件，已返回检索上下文供人工研判。",
            "keyFindings": [],
            "actions": [],
            "confidence": 0.2,
        }

    llm = _build_llm()
    if llm is None:
        return {
            "answer": "当前 LLM 未配置或不可用，已返回图检索上下文供规则引擎或人工继续处理。",
            "keyFindings": [],
            "actions": [],
            "confidence": 0.2,
        }

    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                "你是科技管理 GraphRAG 研判助手。必须严格基于给定图上下文回答，"
                "禁止编造。上下文已按管理层、知识层、桥接层分段，请先分层归纳再给综合结论。"
                "输出严格 JSON: answer, keyFindings, actions, confidence。",
            ),
            (
                "human",
                "问题: {question}\n\n图上下文: {context_text}\n\n"
                "要求: 给出结论、3条以内关键发现、3条以内建议动作；关键发现要体现管理层与知识层证据来源。",
            ),
        ]
    )

    chain = prompt | llm
    response = chain.invoke({"question": question, "context_text": context_text})
    content = getattr(response, "content", "")
    if isinstance(content, list):
        content = "\n".join(str(x) for x in content)

    text = str(content).strip()
    left = text.find("{")
    right = text.rfind("}")
    if left >= 0 and right > left:
        try:
            data = json.loads(text[left : right + 1])
            return {
                "answer": str(data.get("answer", "")),
                "keyFindings": data.get("keyFindings", []),
                "actions": data.get("actions", []),
                "confidence": float(data.get("confidence", 0.6)),
            }
        except Exception as exc:
            print(f"[WARN] Step5 LLM 输出 JSON 解析失败: {exc}")

    return {
        "answer": text,
        "keyFindings": [],
        "actions": [],
        "confidence": 0.5,
    }


def run(cfg: GraphRAGConfig) -> dict[str, Any]:
    keywords = extract_keywords(cfg.question, cfg.top_keywords)

    driver = GraphDatabase.driver(cfg.uri, auth=(cfg.user, cfg.password))
    try:
        with driver.session(database=cfg.database) as session:
            seeds = fetch_seed_nodes(session, keywords, cfg.seed_limit)
            seed_ids = [int(item["id"]) for item in seeds]
            subgraph = fetch_subgraph(
                session,
                seed_ids,
                cfg.max_hops,
                cfg.subgraph_node_limit,
                cfg.subgraph_rel_limit,
            )

        context_text, layer_stats = serialize_subgraph_dual_layer(subgraph)
        answer = answer_with_graphrag(cfg.question, context_text)

        return {
            "meta": {
                "database": cfg.database,
                "question": cfg.question,
                "keywords": keywords,
                "maxHops": cfg.max_hops,
                "seedLimit": cfg.seed_limit,
                "subgraphNodeLimit": cfg.subgraph_node_limit,
                "subgraphRelLimit": cfg.subgraph_rel_limit,
                "retrievedSeeds": len(seeds),
                "retrievedNodes": len(subgraph.get("nodes", [])),
                "retrievedRelationships": len(subgraph.get("relationships", [])),
                "layerStats": layer_stats,
            },
            "retrieval": {
                "seeds": seeds,
                "subgraph": subgraph,
                "contextPreview": context_text[:4000],
                "layeredContextPreview": context_text[:6000],
            },
            "generation": answer,
        }
    finally:
        driver.close()


def main() -> int:
    try:
        cfg = build_config()
    except Exception as exc:
        print(f"[ERROR] 配置错误: {exc}")
        return 2

    try:
        result = run(cfg)
        ensure_output_dir(cfg.output_path)
        with open(cfg.output_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        print("[SUCCESS] Step5 GraphRAG 运行完成")
        print(f"[OUTPUT] {cfg.output_path}")
        print(
            "[SUMMARY] "
            f"seeds={result['meta']['retrievedSeeds']} "
            f"nodes={result['meta']['retrievedNodes']} "
            f"rels={result['meta']['retrievedRelationships']}"
        )
        print(f"[ANSWER] {result['generation'].get('answer', '')[:120]}")
        return 0
    except Neo4jError as exc:
        print(f"[ERROR] Neo4j 执行失败: {exc}")
        return 1
    except Exception as exc:
        print(f"[ERROR] 运行失败: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
