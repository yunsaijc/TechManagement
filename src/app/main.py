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
from src.app.routes import grouping
from src.app.routes import plagiarism
from src.app.routes import perfcheck
from src.app.routes import evaluation
from src.app.routes import sandbox
# from src.app.routes import logicon

app = FastAPI(
    title="科技管理系统 API",
    description="形式审查、项目评审、奖励评审、正文评审等服务",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8006",
        "http://127.0.0.1:8006",
        "http://localhost:8005",
        "http://127.0.0.1:8005",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_no_cache_for_frontend_html(request, call_next):
    response = await call_next(request)
    path = request.url.path
    if path.startswith("/frontend") and (path == "/frontend" or path.endswith(".html")):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

FRONTEND_DIR = Path(__file__).parent.parent.parent / "frontend"
FRONTEND_DIST_DIR = FRONTEND_DIR / "dist"
DEBUG_EVAL_DIR = Path(__file__).parent.parent.parent / "debug_eval"

# 注册路由
app.include_router(review.router, prefix="/api/v1/review", tags=["形式审查"])
app.include_router(grouping.router, prefix="/api/v1/grouping", tags=["智能分组"])
app.include_router(plagiarism.router, prefix="/api/v1/plagiarism", tags=["查重"])
app.include_router(perfcheck.router, prefix="/api/v1/perfcheck", tags=["绩效核验"])
app.include_router(evaluation.router, prefix="/api/v1/evaluation", tags=["正文评审"])
app.include_router(sandbox.router, prefix="/api/v1/sandbox", tags=["Sandbox研判"])
# app.include_router(logicon.router, prefix="/api/v1/logicon", tags=["逻辑自洽"])

SERVE_FRONTEND_DIR = FRONTEND_DIST_DIR if FRONTEND_DIST_DIR.exists() else FRONTEND_DIR

if SERVE_FRONTEND_DIR.exists():
    app.mount("/frontend", StaticFiles(directory=SERVE_FRONTEND_DIR, html=True), name="frontend")

if DEBUG_EVAL_DIR.exists():
    app.mount("/debug-eval", StaticFiles(directory=DEBUG_EVAL_DIR, html=True), name="debug-eval")


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
