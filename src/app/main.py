"""FastAPI 应用入口"""
import os
from dotenv import load_dotenv
from fastapi import FastAPI

# 加载 .env 配置
load_dotenv()

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


# 启动时读取配置
if __name__ == "__main__":
    import uvicorn
    host = os.getenv("APP_HOST", "0.0.0.0")
    port = int(os.getenv("APP_PORT", "8000"))
    uvicorn.run(app, host=host, port=port)
