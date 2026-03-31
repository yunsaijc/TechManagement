"""聊天索引测试"""
import pytest

from src.services.evaluation.chat.indexer import ChatIndexer


@pytest.fixture
def indexer() -> ChatIndexer:
    """索引器夹具"""
    return ChatIndexer()


def test_chat_indexer_prefers_goal_sections(indexer: ChatIndexer):
    """研究目标问题应优先命中目标/简介章节，而不是附件噪声"""
    payload = {
        "evaluation_id": "EVAL_TEST",
        "chunks": [
            {
                "id": 1,
                "file": "demo.pdf",
                "page": 18,
                "section": "附件",
                "text": "[表格行1] 拟使用数量 | 国际合作 | 拟使用种类",
                "tokens": indexer._tokenize("[表格行1] 拟使用数量 国际合作 拟使用种类"),
            },
            {
                "id": 2,
                "file": "demo.pdf",
                "page": 4,
                "section": "项目简介",
                "text": "项目简介\n建设目标\n1、活动创新：开展线上线下结合的科普活动。\n2、技术赋能：开发 AI 智能问答。",
                "tokens": indexer._tokenize("项目简介 建设目标 活动创新 技术赋能 开展线上线下结合的科普活动 开发 AI 智能问答"),
            },
            {
                "id": 3,
                "file": "demo.pdf",
                "page": 5,
                "section": "项目目的和意义",
                "text": "目的：解决现有科普载体单一问题，建设智能化科普咨询平台。",
                "tokens": indexer._tokenize("目的 解决现有科普载体单一问题 建设智能化科普咨询平台"),
            },
        ],
    }

    hits = indexer.search(payload, "这个项目的研究目标是什么？", top_k=3)

    assert hits
    assert hits[0]["section"] in {"项目简介", "项目目的和意义"}
    assert all(hit["section"] != "附件" for hit in hits[:2])


def test_chat_indexer_prefers_benefit_sections_for_mass_production_query(indexer: ChatIndexer):
    """量产/推广问题应优先命中效益或应用推广相关章节"""
    payload = {
        "evaluation_id": "EVAL_TEST",
        "chunks": [
            {
                "id": 1,
                "file": "demo.pdf",
                "page": 1,
                "section": "概述",
                "text": "项目名称：某科普平台建设项目",
                "tokens": indexer._tokenize("项目名称 某科普平台建设项目"),
            },
            {
                "id": 2,
                "file": "demo.pdf",
                "page": 7,
                "section": "合作网络构建",
                "text": "项目效益：社会效益明显，经济效益体现在品牌建设与推广应用，可形成示范案例。",
                "tokens": indexer._tokenize("项目效益 社会效益 经济效益 品牌建设 推广应用 示范案例"),
            },
            {
                "id": 3,
                "file": "demo.pdf",
                "page": 9,
                "section": "普及前景",
                "text": "模式可复制与推广，可为其他机构提供示范。",
                "tokens": indexer._tokenize("模式可复制与推广 可为其他机构提供示范"),
            },
        ],
    }

    hits = indexer.search(payload, "这项工作有可能量产吗？", top_k=2)

    assert hits
    assert hits[0]["section"] in {"合作网络构建", "普及前景"}

