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


def test_chat_indexer_avoids_kpi_table_for_goal_query(indexer: ChatIndexer):
    """研究目标问题应压制绩效表和说明页，优先命中目标正文"""
    payload = {
        "evaluation_id": "EVAL_TEST",
        "chunks": [
            {
                "id": 1,
                "file": "demo.pdf",
                "page": 2,
                "section": "填报说明",
                "text": "填报说明\n项目申报书分为项目背景、研究内容、进度安排、项目绩效评价考核目标及指标等部分。",
                "tokens": indexer._tokenize("填报说明 项目申报书分为 项目背景 研究内容 进度安排 项目绩效评价考核目标及指标"),
            },
            {
                "id": 2,
                "file": "demo.pdf",
                "page": 9,
                "section": "项目绩效评价考核目标及指标",
                "text": "[表格行1] 总体目标 | 实施期目标 | 第一年度目标 | 第二年度目标\n[表格行2] 完成论文、专利、人才培养指标。",
                "tokens": indexer._tokenize("总体目标 实施期目标 第一年度目标 第二年度目标 完成论文 专利 人才培养 指标"),
            },
            {
                "id": 3,
                "file": "demo.pdf",
                "page": 5,
                "section": "项目目的和意义",
                "text": "目的：建设智能化科普咨询平台，整合碎片化科普资源，提升基层传播能力。",
                "tokens": indexer._tokenize("目的 建设智能化科普咨询平台 整合碎片化科普资源 提升基层传播能力"),
            },
        ],
    }

    hits = indexer.search(payload, "这个项目的研究目标是什么？", top_k=3)

    assert hits
    assert hits[0]["section"] == "项目目的和意义"
    assert all(hit["section"] != "填报说明" for hit in hits[:2])


def test_chat_indexer_prefers_schedule_section_for_progress_query(indexer: ChatIndexer):
    """进展问题应优先命中进度安排，而不是说明页或年度目标表"""
    payload = {
        "evaluation_id": "EVAL_TEST",
        "chunks": [
            {
                "id": 1,
                "file": "demo.pdf",
                "page": 2,
                "section": "填报说明",
                "text": "填报说明\n项目申报书分为研究内容、进度安排、风险分析等部分。",
                "tokens": indexer._tokenize("填报说明 项目申报书分为 研究内容 进度安排 风险分析"),
            },
            {
                "id": 2,
                "file": "demo.pdf",
                "page": 11,
                "section": "项目绩效评价考核目标及指标",
                "text": "[表格行1] 实施期目标 | 第一年度目标 | 第二年度目标\n[表格行2] 创作20篇科普内容，开展1次大型活动。",
                "tokens": indexer._tokenize("实施期目标 第一年度目标 第二年度目标 创作20篇科普内容 开展1次大型活动"),
            },
            {
                "id": 3,
                "file": "demo.pdf",
                "page": 14,
                "section": "进度安排",
                "text": "第二年（2026年）：优化系统并开展临床测试。第三年（2027年）：扩大试点并形成阶段成果。",
                "tokens": indexer._tokenize("第二年 2026年 优化系统 开展临床测试 第三年 2027年 扩大试点 形成阶段成果"),
            },
        ],
    }

    hits = indexer.search(payload, "这项工作目前进展到什么程度了？", top_k=3)

    assert hits
    assert hits[0]["section"] == "进度安排"


def test_chat_indexer_goal_query_filters_generic_research_noise(indexer: ChatIndexer):
    """研究目标问题不应被泛化的“项目/研究”字样带偏到资源保障或合作噪声"""
    payload = {
        "evaluation_id": "EVAL_TEST",
        "chunks": [
            {
                "id": 1,
                "file": "demo.pdf",
                "page": 7,
                "section": "资源支撑",
                "text": "合作单位拥有多个研究平台和实验设备，为项目研究和实施提供资源保障。",
                "tokens": indexer._tokenize("合作单位 拥有 多个 研究平台 实验设备 为 项目研究 和 实施 提供 资源保障"),
            },
            {
                "id": 2,
                "file": "demo.pdf",
                "page": 9,
                "section": "项目绩效评价考核目标及指标",
                "text": "总体目标：形成示范应用方案，完成专利和论文指标。",
                "tokens": indexer._tokenize("总体目标 形成示范应用方案 完成专利和论文指标"),
            },
        ],
    }

    hits = indexer.search(payload, "这个项目的研究目标是什么？", top_k=2)

    assert hits
    assert hits[0]["section"] == "项目绩效评价考核目标及指标"


def test_chat_indexer_progress_query_avoids_cover_page(indexer: ChatIndexer):
    """进展问题不应命中只有封面信息的基本信息页"""
    payload = {
        "evaluation_id": "EVAL_TEST",
        "chunks": [
            {
                "id": 1,
                "file": "demo.pdf",
                "page": 1,
                "section": "项目基本信息",
                "text": "河北省创新能力提升计划项目申报书 项目名称 生殖健康科普示范基地标准化建设与创新模式探索",
                "tokens": indexer._tokenize("河北省创新能力提升计划项目申报书 项目名称 生殖健康科普示范基地标准化建设与创新模式探索"),
            },
            {
                "id": 2,
                "file": "demo.pdf",
                "page": 10,
                "section": "现有工作基础及合作分工",
                "text": "基地现有科普团队和传播机制，已形成视频审核、活动实施和内容策划分工。",
                "tokens": indexer._tokenize("基地现有科普团队和传播机制 已形成视频审核 活动实施 和 内容策划分工"),
            },
        ],
    }

    hits = indexer.search(payload, "这项工作目前进展到什么程度了？", top_k=2)

    assert hits
    assert hits[0]["page"] == 10


def test_chat_indexer_build_splits_page_into_paragraph_chunks(indexer: ChatIndexer):
    """构建索引时应把整页文本拆成更细粒度的段落块"""
    payload = indexer.build(
        evaluation_id="EVAL_TEST",
        page_chunks=[
            {
                "id": 1,
                "file": "demo.pdf",
                "page": 4,
                "section": "项目简介",
                "text": (
                    "项目简介\n"
                    "背景与意义\n"
                    "为提升服务能力，项目拟进行设施升级。\n"
                    "建设目标\n"
                    "1、开展线上线下科普活动。\n"
                    "2、开发 AI 智能问答平台。\n"
                    "[表格行1] 指标 | 数值\n"
                    "[表格行2] 覆盖人数 | 10000"
                ),
            }
        ],
    )

    chunks = payload["chunks"]
    assert len(chunks) >= 3
    assert any(chunk["chunk_type"] == "paragraph" and "开发 AI 智能问答平台" in chunk["text"] for chunk in chunks)
    assert any(chunk["chunk_type"] == "table" for chunk in chunks)
