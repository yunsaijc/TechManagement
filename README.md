
## 运行环境

### 激活UV Python环境
source .venv/bin/activate

### 安装依赖
uv add xxx



启动后端（同时承载前端演示页）
python -m uvicorn src.app.main:app --host 0.0.0.0 --port 8005 --reload

打开页面验证
健康检查: http://127.0.0.1:8010/health
前端演示页: http://127.0.0.1:8005/demo/perfcheck
接口文档: http://127.0.0.1:8010/docs
