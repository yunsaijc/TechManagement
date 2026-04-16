# 70 政策动作与 Scenario Contract

## 一、目的

本文件定义沙盘推演中的政策输入范式。

核心原则：

- 不能再用 `funding_boost` 这类玩具参数当作正式政策
- 一次推演输入必须是一份可审计的 `Scenario Contract`

## 二、什么才算政策动作

满足以下条件的，才算政策动作：

- 有明确行政主体
- 有明确管理抓手
- 有明确作用对象
- 有明确生效时间
- 有明确约束
- 有明确可观测结果

反之，下面这些只是引擎参数，不是政策：

- `intensity`
- `spillover_strength`
- `min_similarity`
- 各种风险惩罚权重

它们只能作为内部计算配置，不应暴露给领导作为政策输入。

## 三、Scenario Contract 结构

一次完整推演必须至少包含 6 块：

1. `intent`
   领导原话、决策问题、政策意图
2. `baseline_scope`
   时间窗、主题范围、统计口径
3. `actions`
   政策动作清单
4. `constraints`
   预算、保底、风险、合规边界
5. `evaluation`
   方案成功标准
6. `validation`
   观测/代理/不支持声明

## 四、政策动作分类

最终政策动作分五类：

### 1. 入口侧政策

- 准入门槛
- 申报条件
- 指南收紧/放宽
- 主体资格限制

### 2. 分配侧政策

- 预算增减
- 主题配额
- 立项份额
- 优先级调整

### 3. 评审侧政策

- 评审阈值
- 排序规则
- 权重偏好
- 保底机制

### 4. 能力侧政策

- 协作激励
- 人才支持
- 联合申报
- 组织能力扶持

### 5. 治理侧政策

- 过程监管
- 阶段门槛
- 风险红线
- 执行约束

## 五、当前数据条件下的动作支持等级

### 1. 强支持

基于当前项目库和图谱，可直接进入第一版主流程：

- `budget_reallocate`
- `budget_cap / budget_floor`
- `quota_adjustment`
- `priority_shift`

### 2. 中支持

可以做，但必须标注部分依赖代理或规则假设：

- `review_threshold_shift`
- `score_band_gate`
- `requested_to_award_control`

### 3. 弱支持

结构上可表达，但缺少稳定历史识别或核心事实表：

- `collaboration_incentive`
- `spillover_guidance`
- `eligibility_gate_tighten`

### 4. 当前不支持

当前数据下不应作为领导级硬推演输入：

- `talent_support` 的真实人才供给结果
- `acceptance_rule_change`
- `conversion_incentive`
- `region_targeted_policy`
- `organization_targeted_policy`
- 外部舆情/产业冲击

## 六、领导语言到结构化动作的映射

领导自然语言不能直接进入引擎，必须经过结构化映射。

映射流程：

1. 识别要素
   - 动词：收紧、放宽、倾斜、保底、限制、联合
   - 对象：主题、指南、专项、主体群体
   - 时间：明年、未来两年、本轮指南
   - 约束：预算不增、风险可控、重点保底
   - 目标：提质、降风险、压缩低效扩张

2. 归入动作模板
   - “收紧” 可能映射为：
     - `budget_cap`
     - `quota_reduce`
     - `review_threshold_raise`
     - `eligibility_gate_tighten`

3. 识别不可落地部分
   - 如“转化率极低”“人才断层”
   - 若当前数据不支持，必须进入 `validation.unsupported_claims`

## 七、验证声明

每个动作与核心指标都必须标注：

- `observed`
- `proxy`
- `structural_assumption`
- `unsupported`

如果某方案的核心目标本身属于 `unsupported`，系统必须明确输出：

- `无法严格推演`
或
- `只能按代理口径近似推演`

## 八、设计原则

后续所有 simulation 设计都必须遵守：

- 先写 `Scenario Contract`
- 再落具体动作
- 再定义约束
- 再定义评估目标
- 最后才进入引擎实现
