# 🔄 执行流程与接口草案

## 执行流程

项目级形式审查建议采用以下执行顺序。

### 第一步：接收批次输入

接收：

- `zxmc`

然后执行数据库查询，拿到项目索引结果：

- `sbxx.id`
- `sbxx.year`
- `sbxx.xmmc`
- `zn.name`

### 第二步：扫描材料目录

根据 `year + project_id` 扫描：

- `/mnt/remote_corpus/{year}/sbs/{project_id}`
- `/mnt/remote_corpus/{year}/sbsfj/{project_id}`

说明：

- 当前不默认把申报书作为形式审查主对象
- 当前主审对象是项目级字段和附件集合
- 申报书目录主要用于项目材料存在性和后续扩展，不作为第一阶段主审入口

### 第三步：组装项目上下文

结合数据库项目记录、目录扫描结果和外部校验结果，组装 `ProjectReviewContext`。

### 第四步：材料齐套性预检查

根据 `project_type` 和 `PROJECT_CONFIG`，先判断：

- 必填项目字段是否缺失
- 必需附件类型是否缺失
- 条件满足时是否缺少条件性附件

这一阶段不依赖 OCR 和 LLM，可以快速发现明显问题。

但要注意：

- 若附件类型识别不可靠，不应直接判定“缺少某类附件”
- 这类情况应先降级为待人工复核

### 第五步：附件分发审查

对已上传附件按 `doc_kind` 进行分发，并映射到附件级 `document_type`。

每个附件调用一次现有 `ReviewAgent.process(...)`，产出 `ReviewResult`。

这一阶段直接复用当前已实现的：

- `src/app/routes/review.py`
- `src/services/review/agent.py`
- `src/services/review/rules/config.py`

这一阶段只处理：

- 类型可识别的附件
- 或外部明确指定类型的附件

### 第六步：项目级规则执行

汇总：

- 项目基础字段
- 附件清单
- 附件级审查结果
- 外部校验结果

再执行项目级规则，生成项目级 `CheckResult` 列表。

### 第七步：结果聚合

输出 `ProjectReviewResult`，其中包含：

- 总体结论
- 项目级规则结果
- 缺失附件列表
- 附件级审查结果
- 建议和待人工复核项

## 参考流程图

```text
zxmc
  -> query project index rows
  -> scan sbs/sbsfj directories
  -> build ProjectReviewContext
  -> validate required fields
  -> classify attachments when possible
  -> review identifiable attachments
  -> run project rules
  -> build ProjectReviewResult
```

## 与现有接口的关系

### 当前已实现接口

当前已实现的附件级接口为：

- `POST /api/v1/review`
- `GET /api/v1/review/{review_id}`
- `GET /api/v1/review/document-types`
- `GET /api/v1/review/check-items`

这些接口继续保留，用于：

- 单附件调试
- 附件级能力复用
- 项目级编排内部调用

### 新增项目级接口建议

建议新增独立项目级入口，例如：

```text
POST /api/v1/review/batches
GET  /api/v1/review/batches/{batch_review_id}
GET  /api/v1/review/project-types
```

说明：

- `POST /api/v1/review` 继续表示附件级入口
- `POST /api/v1/review/batches` 表示批次级项目形式审查入口
- 这样更符合真实业务输入

## 请求体草案

建议批次级接口使用 `application/json`。

```json
{
  "zxmc": "db832d940a2843e6b3c33970336d0e9e"
}
```

## 响应体草案

```json
{
  "status": "success",
  "data": {
    "id": "project_review_001",
    "zxmc": "db832d940a2843e6b3c33970336d0e9e",
    "project_count": 12,
    "project_results": [],
    "summary": "批次形式审查完成",
    "processing_time": 12.3
  }
}
```

## 模块建议

为尽量复用现有代码，建议新增项目级模块而不是改写附件级模块。

推荐新增：

- `src/services/review/batch_agent.py`
- `src/services/review/project_index_repo.py`
- `src/services/review/project_context_builder.py`
- `src/services/review/project_rules/`
- `src/app/routes/project_review.py`

其中：

- `batch_agent.py` 负责批次级编排
- `project_index_repo.py` 负责根据 `zxmc` 查询项目列表
- `project_context_builder.py` 负责根据 `year + project_id` 扫描目录并构造上下文
- `project_rules/` 负责项目级规则
- `project_review.py` 提供项目级 API

现有 `src/services/review/agent.py` 保持附件级职责。

## 最小改造原则

项目级形态的第一阶段实现应遵循以下原则：

- 不修改现有附件级接口语义
- 不把项目级逻辑塞进现有 `ReviewAgent`
- 项目级结果复用现有 `CheckResult`
- 附件级结果直接复用现有 `ReviewResult`
- 附件文件名乱码时优先降级到人工复核，而不是武断判失败
- 不默认把申报书作为当前主审对象

这样可以在最小风险下完成能力扩展，并保持文档和实现一致。
