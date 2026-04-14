"""从图谱中按关键词检索专家。"""
from typing import Any, Dict, List

import requests
from requests.auth import HTTPBasicAuth


DEFAULT_URL = "http://192.168.0.198:7474/db/neo4j/query/v2"
DEFAULT_USER = "neo4j"
DEFAULT_PASSWORD = "11223322"


def search_experts(
    query_text: str,
    limit: int = 25,
    min_match_chars: int = 2,
    url: str = DEFAULT_URL,
    username: str = DEFAULT_USER,
    password: str = DEFAULT_PASSWORD,
    timeout: int = 10,
) -> List[Dict[str, Any]]:
    """根据 query_text 从 Neo4j 检索专家节点。"""
    statement = """
        MATCH (n:Person)
        WITH n,
             coalesce(n.`所学专业`, "") + " " + coalesce(n.`所学专业`, "") + " " + coalesce(n.`研究领域`, "") AS text,
             $query_text AS q
        WITH n, text, q,
             [i IN range(0, size(q) - 1)
              WHERE substring(q, i, 1) <> " "
                AND text CONTAINS substring(q, i, 1)] AS matched_chars
        WHERE n.`是否专家` = $is_expert
          AND size(matched_chars) >= $min_match_chars
        RETURN n, size(matched_chars) AS match_count
        ORDER BY match_count DESC
        LIMIT $limit
    """

    payload = {
        "statement": statement,
        "parameters": {
            "is_expert": "是",
            "query_text": query_text,
            "min_match_chars": int(min_match_chars),
            "limit": int(limit),
        },
    }

    resp = requests.post(
        url,
        json=payload,
        auth=HTTPBasicAuth(username, password),
        headers={"Content-Type": "application/json"},
        timeout=timeout,
    )
    resp.raise_for_status()
    data = resp.json()

    experts: List[Dict[str, Any]] = []
    for row in data.get("data", {}).get("values", []):
        node, match_count = row
        if isinstance(node, dict):
            node = dict(node)
            node["match_count"] = match_count
            experts.append(node)

    return experts


if __name__ == "__main__":
    query = "遥感地理分析"
    items = search_experts(query_text=query, limit=25)

    print("query_text:", query)
    print("expert_count:", len(items))
    for expert in items:
        print("match_count=", expert.get("match_count"), expert)
