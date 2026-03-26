"""形式审查 API 路由"""
from typing import List, Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from src.common.models import ApiResponse, ReviewResult
from src.services.review.agent import ReviewAgent
from src.services.review.rules.config import DOCUMENT_CONFIG

router = APIRouter()

# 存储审查结果（生产环境应使用数据库）
_review_results: dict[str, ReviewResult] = {}


class ReviewRequest(BaseModel):
    """审查请求"""
    document_type: str
    check_items: Optional[List[str]] = None
    enable_llm_analysis: bool = False  # 是否启用 LLM 深度分析


class DocumentTypeInfo(BaseModel):
    """文档类型信息"""
    value: str
    label: str
    check_items: List[str]


class CheckItemInfo(BaseModel):
    """检查项信息"""
    value: str
    label: str
    description: str


@router.post("")
async def submit_review(
    file: UploadFile = File(...),
    document_type: str = Form(...),
    check_items: Optional[str] = Form(None),
    enable_llm_analysis: bool = Form(False),
    metadata: Optional[str] = Form(None),
) -> ApiResponse[ReviewResult]:
    """提交文件进行形式审查

    Args:
        file: 上传的文件
        document_type: 文档类型（必填，由调用方指定）
        check_items: 检查项，逗号分隔（可选）
        enable_llm_analysis: 是否启用 LLM 深度分析（可选）
        metadata: 元数据 JSON 字符串（可选）

    Returns:
        审查结果
    """
    import json

    # 解析检查项
    items = None
    if check_items:
        items = [i.strip() for i in check_items.split(",")]

    # 解析元数据
    meta_dict = {}
    if metadata:
        try:
            meta_dict = json.loads(metadata)
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="metadata 必须是有效的 JSON 字符串")

    # 读取文件内容
    file_data = await file.read()

    # 创建 Agent 并执行审查
    agent = ReviewAgent()

    try:
        result = await agent.process(
            file_data=file_data,
            file_type=file.filename.split(".")[-1] if "." in file.filename else "pdf",
            document_type=document_type,
            check_items=items,
            enable_llm_analysis=enable_llm_analysis,
            metadata=meta_dict,
        )

        # 存储结果
        _review_results[result.id] = result

        return ApiResponse(
            status="success",
            data=result,
            message="审查完成",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{review_id}")
async def get_review(review_id: str) -> ApiResponse[ReviewResult]:
    """根据 ID 查询审查结果

    Args:
        review_id: 审查 ID

    Returns:
        审查结果
    """
    result = _review_results.get(review_id)
    if not result:
        raise HTTPException(status_code=404, detail="审查结果不存在")

    return ApiResponse(
        status="success",
        data=result,
    )


@router.get("/document-types")
async def get_document_types() -> ApiResponse[List[DocumentTypeInfo]]:
    """获取支持的文档类型列表

    Returns:
        文档类型列表
    """
    types: List[DocumentTypeInfo] = []
    for doc_type, config in DOCUMENT_CONFIG.items():
        labels = config.get("labels", [])
        rules = config.get("rules", [])
        llm_rules = config.get("llm_rules", [])
        # 展示优先中文首标签；无标签则回退到 code
        label = labels[0] if labels else doc_type
        # 对外统一返回该类型可用检查项（规则引擎 + llm规则）
        check_items = [*rules, *llm_rules]
        types.append(
            DocumentTypeInfo(
                value=doc_type,
                label=label,
                check_items=check_items,
            )
        )

    return ApiResponse(
        status="success",
        data=types,
    )


@router.get("/check-items")
async def get_check_items() -> ApiResponse[List[CheckItemInfo]]:
    """获取所有可用的检查项

    Returns:
        检查项列表
    """
    items = [
        CheckItemInfo(
            value="signature",
            label="签字检查",
            description="检查文档中是否存在签字",
        ),
        CheckItemInfo(
            value="stamp",
            label="盖章检查",
            description="检查文档中是否存在印章",
        ),
        CheckItemInfo(
            value="prerequisite",
            label="前置条件",
            description="检查前置条件文档是否上传",
        ),
        CheckItemInfo(
            value="consistency",
            label="一致性检查",
            description="检查填写信息与证书是否一致",
        ),
        CheckItemInfo(
            value="completeness",
            label="完整性检查",
            description="检查文档是否完整",
        ),
    ]

    return ApiResponse(
        status="success",
        data=items,
    )
