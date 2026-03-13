# 📚 科技管理系统 - 文档目录

## 目录结构

```
docs/
├── index.md                          # 本文档 - 全局入口
│
├── 00-global/                        # 🌍 全局文档（所有服务共用）
│   ├── 01-environment.md            # 环境配置
│   ├── 02-doc-rules.md              # 文档维护规范
│   ├── 03-coding-rules.md           # 开发规范
│   ├── 04-architecture.md           # 系统架构总览
│   ├── 05-deployment.md             # 部署文档
│   └── 06-database.md               # 数据库配置
│
├── 10-common/                        # 🔧 通用组件层（所有服务共用）
│   ├── 01-overview.md               # 通用组件概述
│   ├── 02-models.md                 # 通用数据模型
│   ├── 03-llm.md                   # LLM 统一封装
│   ├── 04-file-handler.md          # 文件处理
│   ├── 05-vision.md                # 视觉能力
│   └── 06-tools.md                  # 工具函数
│
├── 15-data/                         # 📊 数据接入层
│   ├── 01-overview.md              # 数据接入概述
│   ├── 02-reward-db.md             # 奖励评审数据库
│   ├── 03-project-db.md            # 项目评审数据库（待接入）
│   └── 04-extension.md             # 扩展指南
│
├── 20-review/                        # 🔍 形式审查服务
│   ├── 01-overview.md              # 服务概述
│   ├── 02-rules.md                 # 规则引擎设计
│   ├── 03-agent.md                # Agent 设计
│   ├── 04-document-parser.md       # 文档解析方案
│   ├── 05-api.md                  # API 接口文档
│   └── 06-rules.md                # 规则系统
│
├── 30-project/                      # 📋 项目评审服务（未来）
│
├── 40-award/                        # 🏆 奖励评审服务（未来）
│
└── 50-expert/                       # 👤 专家匹配服务（未来）
```

## 层次关系

```
docs/
│
├── 00-global/          ← 环境、文档规范、开发规范、架构、部署
│   ├── 02-doc-rules.md      ← 文档维护规范
│   └── 04-architecture.md  ← 系统级架构图
│
├── 10-common/          ← 通用组件（数据模型、LLM、文件处理、视觉）
│   ├── 02-models.md
│   ├── 03-llm.md
│   ├── 04-file-handler.md
│   └── 05-vision.md
│
├── 20-review/          ← 形式审查服务（依赖 common）
│   ├── 01-overview.md
│   ├── 02-rules.md
│   ├── 03-agent.md
│   ├── 04-document-parser.md
│   ├── 05-api.md
│   └── 06-rules.md
│
├── 30-project/         ← 项目评审服务（未来，依赖 common）
├── 40-award/           ← 奖励评审服务（未来，依赖 common）
└── 50-expert/          ← 专家匹配服务（未来，依赖 common）
```

## 服务依赖关系

```
        ┌─────────────────────────────────────┐
        │           API Layer (FastAPI)        │
        └──────────────────┬──────────────────┘
                           │
        ┌──────────────────▼──────────────────┐
        │           Service Layer              │
        │   ┌──────────┐ ┌──────────┐        │
        │   │  review  │ │ project  │  ...   │
        │   └────┬─────┘ └────┬─────┘        │
        └────────┼────────────┼───────────────┘
                 │            │
        ┌────────▼────────────▼───────────────┐
        │         Common Layer                │
        │   models/ llm/ file/ vision/ tools  │
        └─────────────────────────────────────┘
```

## 快速导航

- [环境配置 →](00-global/01-environment.md)
- [文档维护规范 →](00-global/02-doc-rules.md)
- [开发规范 →](00-global/03-coding-rules.md)
- [系统架构 →](00-global/04-architecture.md)
- [数据库配置 →](00-global/06-database.md)
- [数据接入概述 →](15-data/01-overview.md)
- [奖励评审数据库 →](15-data/02-reward-db.md)
- [通用组件概述 →](10-common/01-overview.md)
- [形式审查服务 →](20-review/01-overview.md)
