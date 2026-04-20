# 70 Sandbox 共享数据层

## 一、定位

`sandbox` 已经不再允许 `trend` 和 `simulation` 各自直接从项目库拼 SQL、各自解释 topic 口径、各自定义项目生命周期。

两者必须先共享同一层：

`真实项目链路 + 正式政策文本 -> 统一对象映射 -> 共享聚合输入 -> trend / simulation`

这层当前已经在代码中落为：

- [__init__.py](/home/tdkx/workspace/tech/src/services/sandbox/data/__init__.py)
- [models.py](/home/tdkx/workspace/tech/src/services/sandbox/data/models.py)
- [project_repository.py](/home/tdkx/workspace/tech/src/services/sandbox/data/project_repository.py)
- [graph_repository.py](/home/tdkx/workspace/tech/src/services/sandbox/data/graph_repository.py)
- [mappers.py](/home/tdkx/workspace/tech/src/services/sandbox/data/mappers.py)
- [facade.py](/home/tdkx/workspace/tech/src/services/sandbox/data/facade.py)

它属于 `sandbox` 共享层，不属于 `simulation` 私有层，也不应该被塞回 `trend` 私有目录。

## 二、当前负责什么

当前共享数据层负责两件事：

1. 把项目库中的真实生命周期事实统一拉成可复用对象
2. 把图谱侧的公共 `topic/year` 口径与最小 topic 指标统一成可复用输入

但按新范式，下一步必须补入第三件事：

3. 把指南、政策、管理办法等正式文本统一拉成可审计的依据对象

当前覆盖的项目链路是：

`Sb_Jbxx -> Sb_Sbzt -> Sb_Jfgs -> PS_XMPSXX -> Ht_XMLXXX -> Ht_Jbxx -> Ht_Jfgs`

也就是说，它当前负责统一：

- 项目主键
- 申报年份
- topic 映射
- 申报经费
- 评审过程与评分代理
- 立项事实
- 合同事实与合同经费
- 承担单位与项目负责人最小映射
- 图谱侧 `Project -> topic/year` 统一表达式
- 图谱侧 `topic` 级公共指标
- 图谱侧窗口覆盖元信息

当前已经进入共享层的图谱公共指标包括：

- `collaboration_density`
- `topic_centrality`
- `migration_strength`

当前已经进入共享层的图谱关系输入包括：

- `topic_migration_edges`

当前已经进入共享层的图谱窗口信息包括：

- `graphYearsCovered`
- `graphCoverageRatio`
- `graphYearlyStats`

当前已经进入共享层的图谱就绪性接口包括：

- `inspect_graph_profile()`
- `verify_graph_readiness()`

它当前还不负责：

- topic 迁移边构建
- GDS 环境预检
- 热点迁移专用 strategy gate
- topic 到 concept 的知识桥接
- trend 预测逻辑
- simulation 状态转移逻辑

但这不等于正式文本层可以继续缺席。

如果没有统一的政策文本层，后续会持续出现三个问题：

- `simulation` 的 `policy_package` 无法追溯到正式指南或管理办法
- `constraints` 会退化成人工口头描述，缺少规则依据
- 领导页只能展示“系统怎么推”，却说不清“为什么可以这么推”

## 三、统一对象模型

当前共享层已经定义的核心对象如下：

### 1. Topic

代码对象：

- [TopicRef](/home/tdkx/workspace/tech/src/services/sandbox/data/models.py)

关键字段：

- `topic_id`
- `topic_name`
- `topic_level`
- `topic_source`
- `mapping_flags`

当前口径规则：

1. 首选 `Sb_Jbxx.zndm`
2. 回填 `sys_guide.name`
3. 再回退到专项名或专项编码
4. 最差情况下回退到项目级占位 topic

这意味着：

- `simulation` 和未来 `trend` 至少先共享同一套项目库 topic 口径
- 图谱侧公共查询也必须对齐到这里，而不是再单独发明一套

### 2. Project

代码对象：

- [ProjectFact](/home/tdkx/workspace/tech/src/services/sandbox/data/models.py)

关键字段：

- `project_id`
- `application_year`
- `project_name`
- `public_audit_passed`
- `topic`
- `institution`
- `principal`
- `review`
- `funding`
- `contract`
- `source_tables`

这里的 `project_id` 统一锚定 `Sb_Jbxx.id`。

### 3. Review

代码对象：

- [ReviewFact](/home/tdkx/workspace/tech/src/services/sandbox/data/models.py)

当前统一内容：

- 是否进入网评
- 是否进入复审
- 是否进入总评
- 网评分
- 复审分
- `score_proxy`
- 评审侧立项标记
- 评审侧立项编号与立项经费

当前 `score_proxy` 规则是：

- 优先 `review_score`
- 回退 `web_score`

### 4. Funding

代码对象：

- [FundingFact](/home/tdkx/workspace/tech/src/services/sandbox/data/models.py)

当前统一内容：

- `requested_special_funding`
- `requested_self_funding`
- `awarded_funding`
- `contract_special_funding`
- `contract_self_funding`

当前 `final_funding_amount` 规则在 [ProjectFact](/home/tdkx/workspace/tech/src/services/sandbox/data/models.py) 中体现：

1. 优先合同专项经费
2. 回退立项经费
3. 否则视为 0

### 5. Contract

代码对象：

- [ContractFact](/home/tdkx/workspace/tech/src/services/sandbox/data/models.py)

当前统一内容：

- `contract_id`
- `contract_project_no`
- `contract_project_name`

### 6. Institution / Person

代码对象：

- [InstitutionRef](/home/tdkx/workspace/tech/src/services/sandbox/data/models.py)
- [PersonRef](/home/tdkx/workspace/tech/src/services/sandbox/data/models.py)

当前只是最小可用版本：

- `Institution` 只统一承担单位
- `Person` 只统一项目负责人

这两个对象当前是为了先把项目事实链打通，不表示后续人员和机构建模已经完成。

### 7. 下一步必须补入的 PolicyDocument / PolicyBinding

这部分当前还未正式落库到共享层，但从范式上已经必须补入。

建议新增两个统一对象：

#### `PolicyDocument`

用于承接 `sys_article + sys_menu` 中的正式文本对象。

最小字段应包括：

- `document_id`
- `document_type`
- `title`
- `menu_name`
- `source`
- `publish_date`
- `content_kind`
- `content_text`
- `canonical_url`
- `raw_article_id`
- `raw_menu_id`

其中：

- `document_type` 至少区分 `guide / policy / management_rule / notice / interpretation`
- `content_kind` 至少区分 `html / external_url / pdf_embed / image_only`

#### `PolicyBinding`

用于把正式文本映射到 sandbox 对象与规则。

最小字段应包括：

- `document_id`
- `binding_type`
- `topic_id`
- `program_id`
- `guide_code_hint`
- `stage_scope`
- `constraint_scope`
- `confidence_label`
- `evidence_excerpt`

它的职责不是直接替代引擎计算，而是提供：

- `topic / program / guide code` 对齐线索
- `policy_package` 的来源依据
- `constraints` 的规则依据
- `assumptions` 的支持材料
- `validation` 的边界披露

## 四、当前公共接口

共享层对上游暴露两种消费方式。

### 1. 函数式接口

定义在：

- [facade.py](/home/tdkx/workspace/tech/src/services/sandbox/data/facade.py)

当前可直接用的函数：

- `load_project_facts(start_year, end_year)`
- `build_topic_aggregates(project_facts)`
- `build_topic_year_aggregates(project_facts)`
- `load_graph_topic_metrics(start_year, end_year)`
- `load_graph_window_metadata(start_year, end_year)`
- `load_topic_migration_edges(start_year, end_year)`
- `inspect_graph_profile()`
- `verify_graph_readiness(...)`

适用场景：

- 先把真实项目事实拉出来
- 再自行做 `trend` 或 `simulation` 上层逻辑

### 2. 类式接口

定义在：

- [SandboxDataService](/home/tdkx/workspace/tech/src/services/sandbox/data/facade.py)

当前可直接用的方法：

- `load_project_facts(...)`
- `build_topic_aggregates(...)`
- `build_topic_year_aggregates(...)`
- `load_graph_topic_metrics(...)`
- `load_graph_window_metadata(...)`
- `load_topic_migration_edges(...)`
- `inspect_graph_profile(...)`
- `verify_graph_readiness(...)`

适用场景：

- 后续逐步扩展成真正的 `sandbox` 数据服务
- 让 `trend`、`simulation`、debug 工具都从同一服务入口取数

## 五、当前已经接到哪里

这层已经接入：

- [baseline_service.py](/home/tdkx/workspace/tech/src/services/sandbox/simulation/baseline_service.py)

当前接入方式是：

- baseline 构建仍保留原有对外接口
- 但项目库 topic 聚合和 topic-year 聚合已经改为消费共享层
- 图谱窗口覆盖元信息也已改为消费共享层
- 图谱 topic 级公共指标也已改为消费共享层
- 图谱 topic 迁移边也已在共享层形成统一入口
- 图谱 readiness / profile 已在共享层形成统一入口

这意味着：

- `simulation baseline` 不再自己重复解释项目库生命周期
- `simulation baseline` 不再自己重复解释 Neo4j 的 `topic/year` 口径
- 未来 `trend` 可以直接消费同一套项目事实与年度聚合输入
- 未来 `trend` 可以直接消费同一套图谱 topic 指标与窗口覆盖输入
- 未来 `trend` 可以直接消费同一套真实 topic 迁移边，而不是重复从 `hotspot` 结果反推
- 后续任何模块如果要做图谱 readiness / profile，不必再去 `hotspot` 或 `preflight` 代码里各抄一套

## 六、给 trend 同事的使用约束

`trend` 同事当前不需要重写这层，也不应该绕过这层直接从项目库再拼一套。

应该遵守：

1. `trend` 如果需要项目事实，直接消费 `load_project_facts(...)`
2. `trend` 如果需要 `topic × year` 主分析输入，直接消费 `build_topic_year_aggregates(...)`
3. `trend` 如果需要图谱 topic 指标，直接消费 `load_graph_topic_metrics(...)`
4. `trend` 如果需要图谱覆盖信息，直接消费 `load_graph_window_metadata(...)`
5. `trend` 如果需要真实迁移边，直接消费 `load_topic_migration_edges(...)`
6. `trend` 如果需要图谱 readiness / profile，直接消费 `inspect_graph_profile()` 与 `verify_graph_readiness(...)`
7. `trend` 如果需要 topic 口径，直接沿用 `TopicRef`
8. `trend` 不得再在自己的代码里单独定义 `Sb_Jbxx -> PS_XMPSXX -> Ht_*` 的生命周期 join 规则
9. `trend` 不得再在自己的代码里单独定义 Neo4j `Project -> topic/year` 表达式

允许 `trend` 在这层之上做的事情：

- 加 `topic_migration_edges`
- 加 topic 到 concept 的知识桥接
- 加 baseline forecast

不允许 `trend` 在自己的代码里重新做的事情：

- 再定义一套 topic 主键
- 再定义一套 funded flag
- 再定义一套最终经费口径
- 再定义一套评分代理口径
- 再定义一套 Neo4j `topic/year` 口径
- 再定义一套协作密度、中心性、迁移强度的基础查询
- 再定义一套 topic 迁移边抽取查询
- 再定义一套图谱 readiness / profile 基础查询

## 七、必须补入的正式文本层

共享层下一步必须把正式文本层纳入统一底座，而不是继续让 `simulation` 在自己的目录里临时解析文章。

建议来源先按以下口径进入：

### 1. 指南文本

主来源：

- `sys_article`
- `sys_menu`

初始筛选口径可以从以下 SQL 起步：

- `SELECT * FROM sys_article WHERE title LIKE '%指南%'`

但进入共享层前必须做：

- 同文去重
- `guide / notice / interpretation` 分型
- HTML / URL / PDF / 图片内容分型
- 年份、专项、项目类型、指南代码抽取

### 2. 政策与管理办法文本

主来源：

- `sys_article`
- `sys_menu`

初始筛选口径可以从以下 SQL 起步：

- `sys_menu.name LIKE '%政策%'`
- `sys_menu.name LIKE '%管理办法%'`

但进入共享层前必须做：

- 同标题多栏目挂载去重
- `policy / management_rule / notice` 分型
- 规则条款抽取
- 适用阶段与约束类型抽取

### 3. 进入共享层后的职责

正式文本层进入共享层后，负责的不是“给 HTML 找素材”，而是：

- 统一 `Scenario Contract` 的依据对象
- 给 `policy_package` 提供可追溯来源
- 给 `constraints` 提供正式规则锚点
- 给 `assumptions` 和 `validation` 提供证据边界

### 4. 不应做的事

正式文本层不应直接做以下事情：

- 不应直接替代引擎改结果变量
- 不应把 raw 文本直接当成 scenario 输入
- 不应绕过 `topic / program / stage` 的统一映射
- 不应在领导页上把文本原文冒充成结构化结论

## 八、当前边界与缺口

共享层虽然已经立住，但仍然只是第一步。

当前明确缺的部分有：

### 1. 图谱共享层还不是完整关系层

现在已经统一了最小图谱 topic 指标、topic 迁移边、窗口元信息和 readiness / profile 入口，但还没有统一的：

- `Project-Topic`
- `Project-Institution`
- `Project-Person`
- `Topic-Topic`
- `Institution-Institution`

所以当前共享层已经不是“只有项目库事实统一层”，但仍然不是完整“事实层 + 关系层”。

### 2. Institution / Person 还只是最小映射

当前没有解决：

- 单位规范名去重
- 人员同名异人
- 多角色人员关系
- 参与人而非只有负责人

### 3. cohort 视角还没下沉

当前已经能按 `application_year` 取项目事实，但还没有沉出正式的：

- `project_cohort_outcome`

这一步后续应由共享层继续往下补，而不是交给单个业务模块临时拼。

## 九、后续扩展顺序

如果继续沿主线推进，推荐顺序是：

1. 在共享层补正式文本仓储、归一化与绑定层
2. 在共享层补关系仓储与 mapper
3. 下沉 topic 到 concept 的知识桥接
4. 让 `trend` 在这层之上做 baseline world forecast
5. 让 `simulation` 在这层之上做状态转移与反事实比较

顺序不能反过来。

如果没有共享层，后面一定会出现：

- `trend` 一套 topic
- `simulation` 一套 topic
- debug 页面再一套 topic

那系统会再次回到 toy。
