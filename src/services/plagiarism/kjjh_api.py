"""Independent KJJH plagiarism endpoints."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Form, HTTPException

from src.common.models import ApiResponse
from src.services.plagiarism.kjjh_checker import run_kjjh_plagiarism

router = APIRouter()


@router.post("/by-file")
async def check_kjjh_plagiarism_by_file(
    xmbh: str = Form(...),
    word_path: Optional[str] = Form(None),
    threshold: float = Form(0.5),
    threshold_high: float = Form(0.8),
    threshold_medium: float = Form(0.5),
    doc_type: str = Form("default"),
    section_config: Optional[str] = Form(None),
    debug: bool = Form(False),
    include_report: bool = Form(True),
) -> ApiResponse[dict]:
    if not str(xmbh).strip():
        raise HTTPException(status_code=400, detail="xmbh 不能为空")
    try:
        payload = await run_kjjh_plagiarism(
            xmbh=xmbh,
            word_path=word_path,
            threshold=threshold,
            threshold_high=threshold_high,
            threshold_medium=threshold_medium,
            doc_type=doc_type,
            section_config_json=section_config,
            debug=debug,
            include_report=include_report,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"执行 kjjh 查重失败: {exc}") from exc

    return ApiResponse(status="success", data=payload)


@router.post("/by-path")
async def check_kjjh_plagiarism_by_path(
    word_path: str = Form(...),
    xmbh: Optional[str] = Form(None),
    threshold: float = Form(0.5),
    threshold_high: float = Form(0.8),
    threshold_medium: float = Form(0.5),
    doc_type: str = Form("default"),
    section_config: Optional[str] = Form(None),
    debug: bool = Form(False),
    include_report: bool = Form(True),
) -> ApiResponse[dict]:
    try:
        payload = await run_kjjh_plagiarism(
            xmbh=xmbh,
            word_path=word_path,
            threshold=threshold,
            threshold_high=threshold_high,
            threshold_medium=threshold_medium,
            doc_type=doc_type,
            section_config_json=section_config,
            debug=debug,
            include_report=include_report,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"执行 kjjh 上传文件查重失败: {exc}") from exc

    return ApiResponse(status="success", data=payload)
