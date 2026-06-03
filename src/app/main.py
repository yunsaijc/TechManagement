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
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(grouping.router, prefix="/api/v1/grouping", tags=["智能分组"])
app.include_router(plagiarism.router, prefix="/api/v1/plagiarism", tags=["查重"])
app.include_router(plagiarism_image.router, prefix="/api/v1/plagiarism/image", tags=["图片查重"])
app.include_router(perfcheck.router, prefix="/api/v1/perfcheck", tags=["绩效核验"])
app.include_router(evaluation.router, prefix="/api/v1/evaluation", tags=["正文评审"])
app.mount("/debug-review", StaticFiles(directory=DEBUG_REVIEW_DIR), name="debug-review")


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
