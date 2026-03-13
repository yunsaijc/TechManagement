"""FastAPI 应用入口"""
from fastapi import FastAPI

from src.app.routes import review

app = FastAPI(
    title="科技管理系统 API",
    description="形式审查、项目评审、奖励评审等服务",
    version="1.0.0",
)

# 注册路由
app.include_router(review.router, prefix="/api/v1/review", tags=["形式审查"])


@app.get("/health")
async def health_check():
    """健康检查"""
    return {"status": "healthy"}
