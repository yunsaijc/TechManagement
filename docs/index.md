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
│   ├── 06-rules.md                # 规则系统
│   ├── project-review/            # 📦 项目级形式审查
│   │   └── 01-overview.md         # 项目级方案概述
│   │   ├── 02-models.md           # 输入输出模型
│   │   ├── 03-rules.md            # 规则与配置设计
│   │   └── 04-flow-and-api.md     # 执行流程与接口草案
│   └── plagiarism/                 # 📝 查重服务
│       ├── 01-overview.md          # 服务概述
│       ├── 03-agent.md             # Agent 设计
│       ├── 04-corpus.md            # 比对库管理
│       └── 05-api.md               # API 接口文档
│
├── 30-grouping/                     # 🧠 智能分组与专家匹配服务
│   ├── 01-overview.md              # 服务概述
│   ├── 02-grouping.md              # 分组子服务设计
│   ├── 03-matching.md              # 专家匹配子服务设计
│   ├── 04-models.md                # 数据模型
│   └── 05-api.md                  # API 接口文档
│
├── 40-evaluation/                   # 📝 正文评审服务
│   ├── 01-overview.md              # 服务概述
│   ├── 02-architecture.md          # 架构设计
│   ├── 03-dimensions.md            # 评审维度详解
│   ├── 04-checkers.md              # 检查器设计
│   ├── 05-scorer.md                # 评分器设计
│   ├── 06-agent.md                 # Agent 设计
│   ├── 07-parsers.md               # 正文解析器设计
│   ├── 08-api.md                   # API 接口文档
│   └── 09-testing.md               # 测试文档
│
├── 50-perfcheck/                    # 📈 绩效核验服务
│   ├── 01-overview.md              # 服务概述
│   ├── 02-rules.md                 # 规则设计
│   ├── 03-agent.md                 # Agent 设计
│   ├── 04-document-parser.md       # 文档解析方案
│   └── 05-api.md                  # API 接口文档
│
├── 70-overview/                     # 🧭 研判与推演总览
│   ├── 01-overview.md              # 总体定位
│   ├── 02-scope.md                 # 范围与边界
│   ├── 03-terms.md                 # 核心术语
│   ├── 04-state-variables.md       # 状态变量清单
│   ├── 05-policy-actions.md        # 政策动作清单
│   ├── 06-outcomes.md              # 结果变量清单
│   └── 07-implementation-sequencing.md # 实施顺序
│
├── 70-trend/                        # 📡 趋势预判
│   ├── 01-overview.md              # 能力总览
│   ├── 02-entities-and-metrics.md  # 对象与指标
│   ├── 03-analysis-pipeline.md     # 分析链路
│   ├── 04-outputs-and-api.md       # 输出与接口
│   ├── 05-data-schema.md           # 数据 Schema
│   └── 06-topic-time-panel-design.md # 核心表设计
│
├── 70-simulation/                   # 🧪 沙盘推演
│   ├── 01-overview.md              # 能力总览
│   ├── 02-policy-model.md          # 政策模型
│   ├── 03-scenario-engine.md       # 场景引擎
│   ├── 04-outputs-and-api.md       # 输出与接口
│   ├── 05-data-schema.md           # 数据 Schema
│   └── 06-baseline-and-scenario-design.md # 基线与场景设计
│
├── 70-sandbox/                      # 🧱 旧原型探索
│   ├── 01-neo4j-gds-step1.md
│   ├── 02-hotspot-migration-step2.md
│   ├── 03-macro-insight-step3.md
│   ├── 04-briefing-orchestrator-step4.md
│   └── 05-graph-rag-step5.md

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
│   └── project-review/
│
├── 30-grouping/         ← 智能分组与专家匹配服务（依赖 common）
│   ├── 01-overview.md
│   ├── 02-grouping.md
│   ├── 03-matching.md
│   ├── 04-models.md
│   └── 05-api.md
│
├── 40-evaluation/       ← 正文评审服务（依赖 common）
│   ├── 01-overview.md
│   ├── 02-architecture.md
│   ├── 03-dimensions.md
│   ├── 04-checkers.md
│   ├── 05-scorer.md
│   ├── 06-agent.md
│   ├── 07-parsers.md
│   ├── 08-api.md
│   └── 09-testing.md
│
├── 50-perfcheck/        ← 绩效核验服务（依赖 common）
│   ├── 01-overview.md
│   ├── 02-rules.md
│   ├── 03-agent.md
│   ├── 04-document-parser.md
│   └── 05-api.md
│
├── 70-overview/         ← 研判与推演顶层设计
│   ├── 01-overview.md
│   ├── 02-scope.md
│   ├── 03-terms.md
│   ├── 04-state-variables.md
│   ├── 05-policy-actions.md
│   ├── 06-outcomes.md
│   └── 07-implementation-sequencing.md
│
├── 70-trend/            ← 趋势预判
│   ├── 01-overview.md
│   ├── 02-entities-and-metrics.md
│   ├── 03-analysis-pipeline.md
│   ├── 04-outputs-and-api.md
│   ├── 05-data-schema.md
│   └── 06-topic-time-panel-design.md
│
├── 70-simulation/       ← 沙盘推演
│   ├── 01-overview.md
│   ├── 02-policy-model.md
│   ├── 03-scenario-engine.md
│   ├── 04-outputs-and-api.md
│   ├── 05-data-schema.md
│   └── 06-baseline-and-scenario-design.md
│
├── 70-sandbox/          ← 历史原型材料
│   ├── 01-neo4j-gds-step1.md
│   ├── 02-hotspot-migration-step2.md
│   ├── 03-macro-insight-step3.md
│   ├── 04-briefing-orchestrator-step4.md
│   └── 05-graph-rag-step5.md
```

## 服务依赖关系

```
        ┌─────────────────────────────────────┐
        │           API Layer (FastAPI)        │
        └──────────────────┬──────────────────┘
                           │
        ┌──────────────────▼──────────────────┐
        │           Service Layer              │
        │   ┌──────────┐ ┌──────────┐ ┌────────────┐
        │   │  review  │ │ grouping │ │ perfcheck  │
        │   └────┬─────┘ └────┬─────┘ └─────┬──────┘
        └────────┼────────────┼──────────────┼──────────────┘
                 │            │              │
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
- [查重服务 →](20-review/plagiarism/01-overview.md)
- [智能分组与专家匹配服务 →](30-grouping/01-overview.md)
- [正文评审服务 →](40-evaluation/01-overview.md)
- [绩效核验服务 →](50-perfcheck/01-overview.md)
- [研判与推演总览 →](70-overview/01-overview.md)
- [状态变量清单 →](70-overview/04-state-variables.md)
- [政策动作清单 →](70-overview/05-policy-actions.md)
- [结果变量清单 →](70-overview/06-outcomes.md)
- [实施顺序 →](70-overview/07-implementation-sequencing.md)
- [趋势预判总览 →](70-trend/01-overview.md)
- [趋势预判数据 Schema →](70-trend/05-data-schema.md)
- [topic_time_panel 设计 →](70-trend/06-topic-time-panel-design.md)
- [沙盘推演总览 →](70-simulation/01-overview.md)
- [沙盘推演数据 Schema →](70-simulation/05-data-schema.md)
- [baseline 与 scenario 设计 →](70-simulation/06-baseline-and-scenario-design.md)
- [旧原型探索 →](70-sandbox/01-neo4j-gds-step1.md)
