# 🚀 部署文档

## 开发环境

### 本地运行

```bash
# 1. 安装依赖
cd tech
uv sync

# 2. 配置环境变量
cp .env.example .env
# 编辑 .env 填入 API Key

# 3. 启动服务
uvicorn src.app.main:app --reload --port 8000

# 4. 访问文档
# OpenAPI: http://localhost:8000/docs
# LangServe: http://localhost:8000/review/
```

### Docker 本地开发

```bash
# 构建镜像
docker build -t tech-app .

# 运行
docker run -p 8000:8000 --env-file .env tech-app
```

## 生产环境

### Docker Compose 部署

```yaml
# docker-compose.yml
version: '3.8'

services:
  app:
    build: .
    ports:
      - "8000:8000"
    environment:
      - OPENAI_API_KEY=${OPENAI_API_KEY}
      - LOG_LEVEL=INFO
    volumes:
      - ./data:/data
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3
```

```bash
# 启动
docker-compose up -d

# 查看日志
docker-compose logs -f app

# 停止
docker-compose down
```

### Kubernetes 部署

```yaml
# k8s/deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: tech-app
  labels:
    app: tech
spec:
  replicas: 3
  selector:
    matchLabels:
      app: tech
  template:
    metadata:
      labels:
        app: tech
    spec:
      containers:
      - name: app
        image: tech-app:latest
        ports:
        - containerPort: 8000
        env:
        - name: OPENAI_API_KEY
          valueFrom:
            secretKeyRef:
              name: tech-secrets
              key: openai-api-key
        resources:
          limits:
            memory: "2Gi"
            cpu: "1000m"
          requests:
            memory: "1Gi"
            cpu: "500m"
        livenessProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 30
          periodSeconds: 10
        readinessProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 5
          periodSeconds: 5
---
apiVersion: v1
kind: Service
metadata:
  name: tech-app
spec:
  selector:
    app: tech
  ports:
  - port: 80
    targetPort: 8000
  type: ClusterIP
---
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: tech-app
spec:
  rules:
  - host: tech.example.com
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: tech-app
            port:
              number: 80
```

```bash
# 部署
kubectl apply -f k8s/

# 查看状态
kubectl get pods -l app=tech
kubectl get svc tech-app
```

## 配置文件

### 生产环境变量

```bash
# 生产环境 .env
OPENAI_API_KEY=sk-xxxxx
LOG_LEVEL=WARNING

# 文件存储
UPLOAD_DIR=/data/uploads
MAX_FILE_SIZE=10485760  # 10MB

# 性能优化
UVICORN_WORKERS=4
```

### 密钥管理

- 使用 Kubernetes Secret 或 Vault 管理敏感信息
- 定期轮换 API Key

## 监控与日志

### 健康检查

```python
# src/app/main.py
from fastapi import FastAPI

app = FastAPI()

@app.get("/health")
async def health_check():
    return {"status": "healthy"}
```

### 日志配置

```python
# src/core/logger.py
import logging
import sys

def setup_logger(name: str = "tech") -> logging.Logger:
    logger = logging.getLogger(name)
    
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
    )
    
    logger.addHandler(handler)
    logger.setLevel(os.getenv("LOG_LEVEL", "INFO"))
    
    return logger
```

### 指标监控

- 使用 Prometheus 采集指标
- 可选集成 LangSmith 进行 LLM 调用追踪

## 性能优化

### 并发处理

```python
# 使用异步处理提高并发
@app.post("/review")
async def review_document(file: UploadFile):
    # 异步处理
    result = await review_service.process(file)
    return result
```

### 文件处理

- 大文件使用流式处理
- 图片预处理减少 LLM 调用次数
- 缓存常用模型输出

### 资源限制

- 限制上传文件大小
- 设置请求超时
- 限制并发数

## 备份与恢复

### 数据备份

- 定期备份上传的文件
- 备份配置文件

### 灾难恢复

- 保留多个镜像版本
- 制定恢复流程文档
- 定期演练

## 安全建议

1. **网络安全**
   - 使用 HTTPS
   - 配置防火墙规则
   - 限制 IP 访问

2. **应用安全**
   - 验证上传文件类型
   - 限制文件大小
   - 防止路径遍历

3. **密钥安全**
   - 不提交密钥到代码仓库
   - 定期轮换密钥
   - 使用密钥管理服务
