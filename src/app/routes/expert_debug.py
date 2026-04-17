"""专家匹配调试：写死读取固定 JSON/HTML（与 match_report 版式对应）。"""

import json
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from src.common.models import ApiResponse, ResponseStatus

router = APIRouter()
logger = logging.getLogger(__name__)

# 与前端展示一致，固定为该次匹配产物
MATCH_RESULT_JSON = Path("/home/tdkx/ljh/Tech/debug_expert/match_result_20260415_115915.json")
MATCH_REPORT_HTML = Path("/home/tdkx/ljh/Tech/debug_expert/match_report_20260415_115915.html")
FIXED_RUN_ID = "20260415_115915"


@router.get("/latest")
async def get_latest_match_json() -> ApiResponse[dict]:
    """返回固定 match_result_20260415_115915.json 全文。"""
    if not MATCH_RESULT_JSON.is_file():
        return ApiResponse(
            status=ResponseStatus.SUCCESS,
            data={
                "run_id": FIXED_RUN_ID,
                "json_filename": MATCH_RESULT_JSON.name,
                "report_html_available": MATCH_REPORT_HTML.is_file(),
                "summary": {},
                "run_config": {},
                "results": [],
            },
        )
    try:
        with open(MATCH_RESULT_JSON, encoding="utf-8") as f:
            payload = json.load(f)
    except Exception as e:
        logger.exception("read expert match json failed: %s", MATCH_RESULT_JSON)
        raise HTTPException(status_code=500, detail=str(e)) from e
    if not isinstance(payload, dict):
        payload = {}
    payload["run_id"] = FIXED_RUN_ID
    payload["json_filename"] = MATCH_RESULT_JSON.name
    payload["report_html_available"] = MATCH_REPORT_HTML.is_file()
    return ApiResponse(status=ResponseStatus.SUCCESS, data=payload)


@router.get("/latest-report")
async def get_latest_match_report_html() -> FileResponse:
    """返回固定 match_report_20260415_115915.html。"""
    if not MATCH_REPORT_HTML.is_file():
        raise HTTPException(status_code=404, detail="未找到 match_report_20260415_115915.html")
    return FileResponse(
        MATCH_REPORT_HTML,
        media_type="text/html; charset=utf-8",
        filename=MATCH_REPORT_HTML.name,
    )
