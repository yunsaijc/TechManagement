"""FastAPI 应用入口"""
import os
from pathlib import Path
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

# 加载 .env 配置（从项目根目录）
load_dotenv(Path(__file__).parent.parent.parent / ".env")

from src.app.routes import review
from src.app.routes import project_review
from src.app.routes import grouping
from src.app.routes import plagiarism
from src.app.routes import plagiarism_image
from src.app.routes import perfcheck
from src.app.routes import evaluation
from src.app.routes import sandbox
from src.app.routes import expert_debug
from src.app.routes import logicon
from src.app.routes import accept

app = FastAPI(
    title="科技管理系统 API",
    description="形式审查、项目评审、奖励评审、正文评审等服务",
    version="1.0.0",
)

cors_allow_origin_regex = os.getenv(
    "APP_CORS_ALLOW_ORIGIN_REGEX",
    r"^https?://(localhost|127\.0\.0\.1|192\.168\.\d{1,3}\.\d{1,3})(:\d+)?$",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8006",
        "http://127.0.0.1:8006",
        "http://localhost:8005",
        "http://127.0.0.1:8005",
        "http://192.168.0.200:8005",
    ],
=======


@app.middleware("http")
async def add_no_cache_for_frontend_html(request, call_next):
    response = await call_next(request)
    path = request.url.path
    if (
        path.startswith("/frontend")
        or path.startswith("/debug-sandbox")
    ) and (path in {"/frontend", "/debug-sandbox"} or path.endswith(".html")):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

FRONTEND_DIR = Path(__file__).parent.parent.parent / "frontend"
FRONTEND_DIST_DIR = FRONTEND_DIR / "dist"
DEBUG_EVAL_DIR = Path(__file__).parent.parent.parent / "debug_eval"
DEBUG_SANDBOX_DIR = Path(__file__).parent.parent.parent / "debug_sandbox"
DEBUG_REVIEW_DIR = Path(__file__).parent.parent.parent / "debug_review"
DEBUG_PLAGIARISM_DIR = Path(__file__).parent.parent.parent / "debug_plagiarism"
DEBUG_EXPERT_DIR = Path(__file__).parent.parent.parent / "debug_expert"
DEBUG_PERFCHECK_DIR = Path(__file__).parent.parent.parent / "debug_perfcheck"
DEBUG_GROUPING_DIR = Path(__file__).parent.parent.parent / "debug_grouping"
DEBUG_ACCEPT_DIR = Path(__file__).parent.parent.parent / "debug_accept"

# 注册路由
app.include_router(grouping.router, prefix="/api/v1/grouping", tags=["智能分组"])
app.include_router(plagiarism.router, prefix="/api/v1/plagiarism", tags=["查重"])
app.include_router(plagiarism_image.router, prefix="/api/v1/plagiarism/image", tags=["图片查重"])
app.include_router(perfcheck.router, prefix="/api/v1/perfcheck", tags=["绩效核验"])
app.include_router(evaluation.router, prefix="/api/v1/evaluation", tags=["正文评审"])
app.include_router(sandbox.router, prefix="/api/v1/sandbox", tags=["Sandbox研判"])
app.include_router(expert_debug.router, prefix="/api/v1/expert-debug", tags=["专家匹配调试"])
app.include_router(logicon.router, prefix="/api/v1/logicon", tags=["逻辑自洽"])
app.include_router(accept.router, prefix="/api/v1/accept", tags=["结题验收"])

SERVE_FRONTEND_DIR = FRONTEND_DIST_DIR if FRONTEND_DIST_DIR.exists() else FRONTEND_DIR

if SERVE_FRONTEND_DIR.exists():
    app.mount("/frontend", StaticFiles(directory=SERVE_FRONTEND_DIR, html=True), name="frontend")

if DEBUG_EVAL_DIR.exists():
    app.mount("/debug-eval", StaticFiles(directory=DEBUG_EVAL_DIR, html=True), name="debug-eval")

if DEBUG_REVIEW_DIR.exists():
    app.mount("/debug-review", StaticFiles(directory=DEBUG_REVIEW_DIR, html=True), name="debug-review")

if DEBUG_PLAGIARISM_DIR.exists():
    app.mount("/debug-plagiarism", StaticFiles(directory=DEBUG_PLAGIARISM_DIR, html=True), name="debug-plagiarism")

if DEBUG_LOGICON_DIR.exists():
    app.mount("/debug-logicon", StaticFiles(directory=DEBUG_LOGICON_DIR, html=True), name="debug-logicon")

if DEBUG_EXPERT_DIR.exists():
    app.mount("/debug-expert", StaticFiles(directory=DEBUG_EXPERT_DIR, html=True), name="debug-expert")

if DEBUG_PERFCHECK_DIR.exists():
    app.mount("/debug-perfcheck", StaticFiles(directory=DEBUG_PERFCHECK_DIR, html=True), name="debug-perfcheck")

if DEBUG_GROUPING_DIR.exists():
    app.mount("/debug-grouping", StaticFiles(directory=DEBUG_GROUPING_DIR, html=True), name="debug-grouping")

if DEBUG_ACCEPT_DIR.exists():
    app.mount("/debug-accept", StaticFiles(directory=DEBUG_ACCEPT_DIR, html=True), name="debug-accept")

DEBUG_SANDBOX_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/debug-sandbox", StaticFiles(directory=DEBUG_SANDBOX_DIR, html=True), name="debug-sandbox")


@app.get("/", include_in_schema=False)
async def frontend_home():
    """首页跳转到前端控制台。"""
    if SERVE_FRONTEND_DIR.exists():
        return RedirectResponse(url="/frontend")
    return {"message": "frontend not found"}


@app.get("/health")
async def health_check():
    """健康检查"""
    return {"status": "healthy"}


@app.get("/demo/perfcheck")
async def perfcheck_demo_page():
    """绩效核验前端演示页。"""
    page = Path(__file__).parent / "web" / "perfcheck_demo.html"
    return FileResponse(page)


# 启动时读取配置
if __name__ == "__main__":
    import uvicorn
    host = os.getenv("APP_HOST", "0.0.0.0")
    port = int(os.getenv("APP_PORT", "8000"))
    uvicorn.run(app, host=host, port=port)
