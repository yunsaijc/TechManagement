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

### 第八步：生成项目 packet

在 `ProjectReviewResult` 生成之后，为每个项目输出一个统一 `packet PDF`。

生成规则：

- 输入顺序固定为：`申报书 -> 附件目录中的文件顺序`
- 不插目录页，不插摘要页，不重排原文件
- 若材料本身是 `pdf`，直接按原页插入
- 若材料本身是图片，转成单页 PDF 后插入
- 若申报书同时存在 `pdf` 与 `docx`，packet 优先使用原始 `pdf`

同时输出 `page_map`，用于把规则证据映射到 packet 页码。

### 第九步：报告工作台组装

在 `ProjectReviewResult` 之上，继续组装面向调试页/报告页的展示模型。

建议生成三类结构：

- 左栏项目索引
- 中栏规则卡片流
- 右栏统一 packet 查看器

这一层不负责重新执行规则，只负责把已有结果组织成可浏览、可点击、可跳转的工作台数据。

### 第十步：生成三栏报告页

最终输出 `三栏审阅工作台`：

- 左栏：批次内项目列表
- 中栏：当前项目的审查结果流
- 右栏：当前项目的统一 packet 查看器

建议：

- 继续沿用 `debug_review/{batch_id}/index.html`
- 由同一个 HTML 文件完成项目切换和 packet 跳页
- 静态资源继续写入批次调试目录，避免引入额外部署链路

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
  -> build project packet + page map
  -> build report view model
  -> render review workspace html
```

## 报告页交互草案

### 左栏：项目切换

左栏负责批次内项目切换，建议展示：

- 项目名称
- 项目 ID
- 项目类型
- 失败项数量
- 需人工处理数量

点击项目后：

- 中栏刷新为该项目规则结果
- 右栏加载该项目唯一的 packet PDF

### 中栏：规则点击

中栏每条规则项都应具备一个或多个 `EvidenceTarget`。

点击规则后：

- 若存在证据目标，右栏跳到 packet 中的目标页
- 若存在多个命中点，仍然只在同一个 packet 内切页
- 若暂无精确定位，至少跳到对应原文件的起始页

### 右栏：证据查看

右栏建议支持：

- 单 packet 固定预览
- 页级跳转
- 打开原始文件
- 显示当前证据对应的原始文件名和页码范围

不建议使用 hover 自动跳转，必须显式点击触发。

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
- `src/services/review/report_view_builder.py`
- `src/app/routes/project_review.py`

其中：

- `batch_agent.py` 负责批次级编排
- `project_index_repo.py` 负责根据 `zxmc` 查询项目列表
- `project_context_builder.py` 负责根据 `year + project_id` 扫描目录并构造上下文
- `project_rules/` 负责项目级规则
- `report_view_builder.py` 负责把项目级结果转换为三栏报告所需结构
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
- 报告层与规则层分离，避免在 HTML 拼装阶段重新解释业务规则

这样可以在最小风险下完成能力扩展，并保持文档和实现一致。
