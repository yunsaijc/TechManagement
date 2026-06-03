"""结题验收 KPI 履约核验 API 路由"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from src.common.models import ApiResponse, ResponseStatus
from src.services.accept import get_accept_service
from src.services.accept.debug_workflow import (
    build_acceptance_project_payload,
    infer_year_from_path,
    load_existing_results,
    persist_acceptance_project_payload,
    refresh_acceptance_project_payload,
    resolve_accept_debug_root,
    run_acceptance_project_pipeline,
)
from src.services.accept.models import AcceptanceCheckResult, ParsedAcceptanceDocument
from src.services.accept.service import (
    AcceptanceAttachmentInput,
    AcceptanceAttachmentTextInput,
)


router = APIRouter()
logger = logging.getLogger(__name__)


class AcceptanceTextAttachmentRequest(BaseModel):
    file_name: str
    text: str
    file_type: str = "text"


class AcceptanceTextCheckRequest(BaseModel):
    project_id: str = "accept_demo"
    taskbook_text: str
    taskbook_file_name: str = "taskbook.txt"
    attachments: list[AcceptanceTextAttachmentRequest] = Field(default_factory=list)


class AcceptancePathCheckRequest(BaseModel):
    project_id: str = "accept_demo"
    taskbook_path: str
    acceptance_application_path: str
    acceptance_attachment_dir: str


class AcceptanceMaterialBlock(BaseModel):
    block_id: str
    text: str
    page: int = 0
    line_index_start: int = 0
    line_index_end: int = 0
    bbox: dict = Field(default_factory=dict)


class AcceptanceMaterialDocument(BaseModel):
    role: str
    file_name: str
    file_path: str = ""
    file_type: str
    text: str
    lines: list[str] = Field(default_factory=list)
    line_count: int = 0
    page_count: int = 0
    blocks: list[AcceptanceMaterialBlock] = Field(default_factory=list)


class AcceptanceWorkbenchResult(BaseModel):
    project_id: str
    result: AcceptanceCheckResult
    materials: list[AcceptanceMaterialDocument] = Field(default_factory=list)


def _detect_file_type(upload: UploadFile) -> str:
    file_name = upload.filename or ""
    if "." in file_name:
        return file_name.rsplit(".", 1)[-1].lower()
    return "txt"


def _normalize_project_id(project_id: Optional[str], fallback_name: str) -> str:
    value = (project_id or "").strip()
    if value:
        return value
    fallback = (fallback_name or "").strip()
    if fallback:
        return fallback.rsplit(".", 1)[0]
    return "accept_demo"


def _normalize_processing_error(exc: Exception) -> HTTPException:
    message = str(exc).strip() or f"{type(exc).__name__}"
    if isinstance(exc, ValueError):
        return HTTPException(status_code=422, detail=message)
    if "No module named 'fitz'" in message:
        return HTTPException(
            status_code=500,
            detail="PDF 解析依赖缺失：当前环境未安装 PyMuPDF(fitz)。可先调用 /api/v1/accept/check-text，或补装 PyMuPDF 后再走文件上传接口。",
        )
    return HTTPException(status_code=500, detail=f"验收核验失败: {message}")


def _detect_file_type_from_name(file_name: str) -> str:
    name = (file_name or "").strip()
    if "." in name:
        return name.rsplit(".", 1)[-1].lower()
    return "txt"


def _build_attachment_input(file_name: str, file_data: bytes) -> AcceptanceAttachmentInput:
    return AcceptanceAttachmentInput(
        file_name=file_name,
        file_type=_detect_file_type_from_name(file_name),
        file_data=file_data,
    )


def _load_attachments_from_dir(dir_path: str) -> list[AcceptanceAttachmentInput]:
    path = Path(dir_path).expanduser().resolve()
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"验收申请附件目录不存在: {path}")
    if not path.is_dir():
        raise HTTPException(status_code=422, detail=f"验收申请附件路径不是目录: {path}")

    attachments: list[AcceptanceAttachmentInput] = []
    for file_path in sorted(path.rglob("*")):
        if not file_path.is_file():
            continue
        attachments.append(_build_attachment_input(file_path.name, file_path.read_bytes()))
    return attachments


async def _parse_material_document(
    *,
    role: str,
    file_path: Path,
) -> tuple[ParsedAcceptanceDocument, AcceptanceMaterialDocument]:
    service = get_accept_service()
    payload = file_path.read_bytes()
    parsed = await service.parser.parse_bytes(
        file_data=payload,
        file_type=_detect_file_type_from_name(file_path.name),
        file_name=file_path.name,
    )
    material = AcceptanceMaterialDocument(
        role=role,
        file_name=parsed.file_name,
        file_path=str(file_path),
        file_type=parsed.file_type,
        text=parsed.text,
        lines=parsed.lines,
        line_count=len(parsed.lines),
        page_count=int(parsed.metadata.get("pages") or 0),
        blocks=[
            AcceptanceMaterialBlock(
                block_id=block.block_id,
                text=block.text,
                page=block.page,
                line_index_start=block.line_index_start,
                line_index_end=block.line_index_end,
                bbox=block.bbox.model_dump() if block.bbox else {},
            )
            for block in parsed.blocks
        ],
    )
    return parsed, material


async def _persist_full_project_payload_background(
    *,
    input_dir: Path,
    artifacts,
    service,
) -> None:
    try:
        enriched = await refresh_acceptance_project_payload(
            artifacts=artifacts,
            service=service,
            include_viewer_assets=True,
            include_target_enrichment=True,
        )
        results_path = input_dir / "acceptance_results.json"
        existing_results = load_existing_results(results_path)
        existing_project = next(
            (item for item in existing_results if str(item.get("project_no") or "") == str(artifacts.result.project_id)),
            None,
        )
        refreshed = dict(enriched)
        refreshed["project_name"] = (
            str(existing_project.get("project_name") or artifacts.result.project_id)
            if existing_project
            else artifacts.result.project_id
        )
        await persist_acceptance_project_payload(
            input_dir=input_dir,
            payload=refreshed,
            existing_results=existing_results,
            existing_project=existing_project,
        )
    except Exception:
        logger.exception("acceptance background payload refresh failed")


@router.post("/check", response_model=ApiResponse[AcceptanceCheckResult])
async def check_acceptance_files(
    taskbook_file: UploadFile = File(...),
    acceptance_application_file: UploadFile = File(...),
    attachments: Optional[List[UploadFile]] = File(None),
    project_id: Optional[str] = Form(None),
) -> ApiResponse[AcceptanceCheckResult]:
    """上传任务书、验收申请与附件文件，执行结题验收 KPI 履约核验。"""
    service = get_accept_service()
    try:
        taskbook_bytes = await taskbook_file.read()
        if not taskbook_bytes:
            raise HTTPException(status_code=400, detail="任务书文件不能为空")
        acceptance_application_bytes = await acceptance_application_file.read()
        if not acceptance_application_bytes:
            raise HTTPException(status_code=400, detail="验收申请文件不能为空")

        normalized_project_id = _normalize_project_id(project_id, taskbook_file.filename or "")
        parsed_attachments: list[AcceptanceAttachmentInput] = [
            _build_attachment_input(
                acceptance_application_file.filename or "acceptance_application",
                acceptance_application_bytes,
            )
        ]
        for attachment in attachments or []:
            payload = await attachment.read()
            if not payload:
                continue
            parsed_attachments.append(_build_attachment_input(attachment.filename or "attachment", payload))

        result = await service.check_from_files(
            project_id=normalized_project_id,
            taskbook_file=taskbook_bytes,
            taskbook_file_type=_detect_file_type(taskbook_file),
            attachments=parsed_attachments,
            taskbook_file_name=taskbook_file.filename or "taskbook",
        )
        return ApiResponse(
            status=ResponseStatus.SUCCESS,
            data=result,
            message="验收核验完成",
            code=200,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("acceptance check failed")
        raise _normalize_processing_error(exc)


@router.post("/check-paths", response_model=ApiResponse[AcceptanceWorkbenchResult])
async def check_acceptance_paths(
    request: AcceptancePathCheckRequest,
    background_tasks: BackgroundTasks,
) -> ApiResponse[AcceptanceWorkbenchResult]:
    """直接提交服务端文件路径：返回核查结果、原文材料，并同步刷新调试工作台产物。"""
    service = get_accept_service()
    try:
        taskbook_path = Path(request.taskbook_path).expanduser().resolve()
        acceptance_application_path = Path(request.acceptance_application_path).expanduser().resolve()
        attachment_dir_path = Path(request.acceptance_attachment_dir).expanduser().resolve()

        if not taskbook_path.exists() or not taskbook_path.is_file():
            raise HTTPException(status_code=404, detail=f"任务书文件不存在: {taskbook_path}")
        if not acceptance_application_path.exists() or not acceptance_application_path.is_file():
            raise HTTPException(status_code=404, detail=f"验收申请文件不存在: {acceptance_application_path}")
        if not attachment_dir_path.exists() or not attachment_dir_path.is_dir():
            raise HTTPException(status_code=404, detail=f"验收申请附件目录不存在: {attachment_dir_path}")

        taskbook_pair, acceptance_application_pair = await asyncio.gather(
            _parse_material_document(role="taskbook", file_path=taskbook_path),
            _parse_material_document(role="acceptance_application", file_path=acceptance_application_path),
        )
        taskbook_doc, taskbook_material = taskbook_pair
        acceptance_application_doc, acceptance_application_material = acceptance_application_pair
        attachment_files = [file_path for file_path in sorted(attachment_dir_path.rglob("*")) if file_path.is_file()]
        attachment_pairs = await asyncio.gather(
            *(_parse_material_document(role="attachment", file_path=file_path) for file_path in attachment_files)
        )
        attachment_materials = [material for _, material in attachment_pairs]
        artifacts = await run_acceptance_project_pipeline(
            input_dir=resolve_accept_debug_root(taskbook_path, acceptance_application_path, attachment_dir_path) or Path("/tmp"),
            year=infer_year_from_path(taskbook_path),
            project_no=_normalize_project_id(request.project_id, taskbook_path.name),
            taskbook_path=taskbook_path,
            yssq_path=acceptance_application_path,
            attachment_dir=attachment_dir_path,
            project_name=_normalize_project_id(request.project_id, taskbook_path.name),
            service=service,
            include_viewer_assets=False,
            include_target_enrichment=False,
        )
        result = artifacts.result
        input_dir = resolve_accept_debug_root(taskbook_path, acceptance_application_path, attachment_dir_path)
        if input_dir is not None:
            fast_existing_results = load_existing_results(input_dir / "acceptance_results.json")
            fast_existing_project = next(
                (item for item in fast_existing_results if str(item.get("project_no") or "") == result.project_id),
                None,
            )
            fast_payload = dict(artifacts.project_payload)
            fast_payload["project_name"] = (
                str(fast_existing_project.get("project_name") or result.project_id)
                if fast_existing_project
                else result.project_id
            )
            await persist_acceptance_project_payload(
                input_dir=input_dir,
                payload=fast_payload,
                existing_results=fast_existing_results,
                existing_project=fast_existing_project,
            )
            background_tasks.add_task(
                _persist_full_project_payload_background,
                input_dir=input_dir,
                artifacts=artifacts,
                service=service,
            )
        payload = AcceptanceWorkbenchResult(
            project_id=result.project_id,
            result=result,
            materials=[taskbook_material, acceptance_application_material, *attachment_materials],
        )
        return ApiResponse(
            status=ResponseStatus.SUCCESS,
            data=payload,
            message="验收核验完成",
            code=200,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("acceptance path check failed")
        raise _normalize_processing_error(exc)


@router.post("/workbench/check-paths", response_model=ApiResponse[AcceptanceWorkbenchResult])
async def check_acceptance_workbench_paths(
    request: AcceptancePathCheckRequest,
) -> ApiResponse[AcceptanceWorkbenchResult]:
    """兼容旧工作台路由，内部复用 check-paths。"""
    return await check_acceptance_paths(request)


@router.post("/check-text", response_model=ApiResponse[AcceptanceCheckResult])
async def check_acceptance_text(
    request: AcceptanceTextCheckRequest,
) -> ApiResponse[AcceptanceCheckResult]:
    """直接提交任务书文本与附件文本，执行结题验收 KPI 履约核验。"""
    service = get_accept_service()
    try:
        attachments = [
            AcceptanceAttachmentTextInput(
                file_name=item.file_name,
                text=item.text,
                file_type=item.file_type,
            )
            for item in request.attachments
        ]
        result = await service.check_from_text(
            project_id=_normalize_project_id(request.project_id, request.taskbook_file_name),
            taskbook_text=request.taskbook_text,
            attachments=attachments,
            taskbook_file_name=request.taskbook_file_name,
        )
        return ApiResponse(
            status=ResponseStatus.SUCCESS,
            data=result,
            message="验收核验完成",
            code=200,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("acceptance text check failed")
        raise _normalize_processing_error(exc)
