# 📦 项目级形式审查概述

## 定位

项目级形式审查位于现有单文档审查能力之上，负责按**项目类型**组织材料、汇总附件检查结果，并执行项目级规则。

当前代码中的 `POST /api/v1/review` 适合作为**附件级形式审查**能力，不适合作为完整的项目级审查入口。项目级形式审查应复用现有 `review` 服务，而不是替代它。

详细设计：

- [输入输出模型 →](02-models.md)
- [规则与配置设计 →](03-rules.md)
- [执行流程与接口草案 →](04-flow-and-api.md)

## 设计目标

项目级形式审查负责回答以下问题：

- 该项目类型应提交哪些附件
- 实际上传了哪些附件，缺少哪些附件
- 已上传附件中，能够识别类型的附件是否通过签字、盖章、完整性等检查
- 项目级条件是否满足，例如执行期、资金比例、合作单位要求、推荐函要求
- 是否存在需要外部系统校验的问题，例如失信、重复申报、单位注册信息

根据 `2026年度中央引导地方形式审查要点`，当前审查重点是**项目级条件**和**附件齐套性**，不是默认对申报书本身做签字、盖章式形式审查。

## 分层模型

### 1. 附件级形式审查

复用现有 `review` 服务，输入为单个附件，输出为单附件审查结果。

职责：

- 签字检查
- 盖章检查
- 完整性检查
- 单附件字段提取
- 少量单附件一致性检查

该能力仅在**能够明确识别附件类型**时参与项目级形式审查，不作为项目级主引擎。

当前可直接复用的实现包括：

- `src/app/routes/review.py`
- `src/services/review/agent.py`
- `src/services/review/extractor.py`
- `src/services/review/rules/checkers/`
- `src/common/models/review.py`

### 2. 项目级形式审查

新增编排层，输入为批次标识和项目上下文，输出为项目级审查结果。

职责：

- 按 `project_type` 加载项目规则
- 判断项目目录下是否存在申报书和附件材料
- 在可识别附件类型时判断材料齐套性
- 调用附件级审查能力检查可识别的已上传材料
- 汇总附件审查结果
- 执行项目级规则

## 核心概念

### `project_type`

表示项目类别，例如：

- `regional_innovation`
- `innovation_base`
- `achievement_transformation`
- `basic_research`

项目级规则以 `project_type` 为主维度。

### `doc_kind`

表示附件业务类型，例如：

- `commitment_letter`
- `ethics_approval`
- `industry_permit`
- `biosafety_commitment`
- `cooperation_agreement`
- `recommendation_letter`
- `retrieval_report`
- `contributor_form`

附件级检查和材料齐套性判断以 `doc_kind` 为主维度。

当前需要注意：

- 如果附件文件名可读，`doc_kind` 可以由文件名或元数据归类
- 如果附件文件名乱码且暂无附件元数据表，`doc_kind` 识别不可靠
- 在这种情况下，项目级系统应降级为“附件存在性 + 待人工复核”，而不应直接武断判定“缺少某类附件”

### `document_type`

表示单文档审查时使用的文档类型，属于现有 `review` 服务的输入概念。它服务于附件级检查，不应直接承担项目级规则配置职责。

## 输入模型

项目级形式审查建议以批次查询结果和目录扫描结果组装上下文，而不是要求调用方手工传完整附件明细。

当前更贴近真实实现的输入来源有三类：

### 1. 批次入口

- `zxmc`

系统通过数据库查询项目列表：

- `sbxx.id`
- `sbxx.year`
- `sbxx.xmmc`
- `zn.name`

### 2. 文件系统材料目录

- 申报书目录：`/mnt/remote_corpus/{year}/sbs/{project_id}`
- 附件目录：`/mnt/remote_corpus/{year}/sbsfj/{project_id}`

### 3. 项目上下文

在数据库结果和目录扫描结果基础上，再组装以下四类信息：

### `project_info`

项目基础信息，例如：

- `project_id`
- `project_type`
- `project_name`
- `applicant_unit`
- `applicant_unit_type`
- `registered_date`
- `execution_period_years`
- `fiscal_funding`
- `self_funding`
- `has_clinical_research`
- `has_special_industry_requirement`
- `has_biosafety_activity`
- `has_cooperation_unit`

### `cooperation_info`

合作单位信息，例如：

- `cooperation_units`
- `cooperation_regions`
- `has_formal_cooperation_agreement`
- `has_management_recommendation_letter`

### `attachments`

附件列表。每个附件至少应包含：

- `attachment_id`
- `doc_kind` 或 `unknown_attachment`
- `file_name`
- `file_ref`

### `external_checks`

外部校验结果，例如：

- `integrity_status`
- `social_credit_status`
- `duplicate_submission_status`
- `applicant_region`

## 执行流程

```text
zxmc
  -> 查询项目列表 (id, year, xmmc, guide_name)
  -> 扫描 sbs / sbsfj 目录
  -> 构建 ProjectReviewContext
  -> 按 project_type 执行项目级规则
  -> 对可识别附件按 doc_kind 分发到 review 服务
  -> 汇总可识别附件的单附件审查结果
  -> 执行项目级规则
  -> 输出 ProjectReviewResult
```

## 规则模型

项目级形式审查需要两类规则并行存在：

### 附件级规则

沿用当前 `review` 服务中的规则体系，继续负责：

- `signature`
- `stamp`
- `retrieval_report_completeness`
- `work_unit_consistency`

这些规则只对**可明确识别的附件**生效。

### 项目级规则

新增项目级规则，负责：

- 批次项目装配
- 材料存在性
- 条件性附件要求
- 执行期上限
- 资金比例
- 合作单位要求
- 推荐函要求
- 申报单位类型要求
- 外部校验结果
- 附件无法识别时的待人工复核

## 配置建议

保留现有 `DOCUMENT_CONFIG`，新增 `PROJECT_CONFIG`。

- `DOCUMENT_CONFIG` 继续描述单附件检查策略
- `PROJECT_CONFIG` 负责描述项目类型对应的材料要求和项目级规则

推荐将 `PROJECT_CONFIG` 至少拆为以下部分：

- 必填项目字段
- 必需附件类型
- 条件性附件规则
- 项目级规则列表
- 执行期上限
- 特殊地域或单位类型要求

同时建议补充：

- `guide_name -> project_type` 映射
- 目录扫描策略
- 附件识别置信度不足时的降级规则

## 结果模型

建议保留现有 `ReviewResult` 作为单附件结果模型，新增 `ProjectReviewResult` 作为项目级结果模型。

`ProjectReviewResult` 应至少包含：

- 项目总体结论
- 项目级规则结果
- 缺失附件列表
- 附件级审查结果列表
- 待人工复核项

如果附件文件名乱码且无元数据，`缺失附件列表` 应谨慎使用，更适合优先输出 `待人工复核项`。

## 报告交付形态

批次级项目形式审查的调试报告，不再建议继续使用“单页大表格 + 连续展开”的方式。

更适合当前业务的是 `三栏审阅工作台`：

- 左栏：项目导航栏
- 中栏：当前项目的审查结果流
- 右栏：证据查看器

### 左栏：项目导航栏

左栏只负责在批次内切换项目，不承载详细规则内容。

建议展示：

- 项目名称
- 项目 ID
- 项目类型
- 失败项数量
- 需人工处理数量

建议支持：

- 按项目名称或项目 ID 搜索
- 按状态筛选，例如 `全部 / 有失败 / 需人工处理 / 已通过`
- 当前项目高亮

### 中栏：审查结果流

中栏是当前项目的主工作区，负责组织审查点和结论。

建议按分组展示：

- 失败项
- 需人工处理项
- 通过项
- 系统已限制 / 不适用项

每条规则卡片建议只保留以下信息：

- 审查点名称
- 审查要求
- 当前状态
- 证据摘要
- `查看原文/附件` 操作入口

中栏的职责是“组织审查任务”，不是直接承担文档查看。

### 右栏：证据查看器

右栏负责展示中栏当前选中规则所对应的证据。

建议支持：

- 打开申报书主文档或附件
- 跳转到对应页
- 展示命中片段或截图
- 切换同一规则下的多个命中点
- 在新标签打开原文件

右栏的职责是“证据定位”，不是简单附件列表。

### 交互原则

报告交互建议遵循以下规则：

- 左栏点击项目，只切换当前项目上下文
- 中栏点击某条规则，右栏跳到最相关证据
- 右栏切换命中点时，不改变左栏当前项目和中栏当前规则
- 不使用 hover 自动跳转，必须显式点击触发

### 设计原则

该形态应遵循以下基本原则：

- 导航、结果、证据三类信息分区，不混排
- 一次只聚焦一个项目和一条规则
- 跳转动作必须可预期、可回退
- 对移动端降级为上下堆叠布局，但信息结构保持一致

### 与当前实现的关系

当前 `debug_review/{batch_id}/index.html` 仍可作为第一阶段载体，不要求立即引入独立前端工程。

推荐演进路径：

- 第一阶段：保留静态 HTML 输出，改造成三栏工作台
- 第二阶段：补齐页级证据定位和高亮
- 第三阶段：再评估是否引入更完整的文档查看组件

## 与现有实现的关系

该方案不是重写现有 `review` 服务，而是在其上增加项目级编排层。

当前代码可直接复用的部分：

- 单附件上传与审查入口
- 签字与盖章提取能力
- 现有 checker 与结果模型
- OCR 与多模态提取流程

需要新增的部分：

- 基于 `zxmc` 的批次查询入口
- 数据库项目列表查询
- 基于 `year + project_id` 的目录扫描
- 附件识别与降级策略
- 项目级规则上下文
- 项目级规则配置
- 项目级结果模型
