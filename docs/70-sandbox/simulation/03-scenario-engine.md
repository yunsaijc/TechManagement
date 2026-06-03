# 反事实场景引擎

## 一、引擎目标

场景引擎的职责不是“把参数改一下再画图”，而是：

`在同一 baseline 上，沿治理流程逐环节传导政策场景，生成可比较、可解释、可追溯的 counterfactual world`

引擎只回答条件性问题：

- 在给定政策包、约束和假设下，治理链路将如何变化
- 相比 baseline，哪些主题、项目群和结构结果发生变化

引擎不回答无条件预测，更不直接声称强因果。

## 二、统一传导链

所有场景都必须通过同一条治理传导链：

`申报响应 -> 评审选择 -> 立项/合同配置 -> 结构外溢`

这是 simulation 的硬约束。

### 1. 申报响应

场景首先改变申报端状态：

- 项目数
- 申报专项经费
- 进入申报池的主题结构
- 新进入机构或人员的占比

输入主要来自：

- `Sb_Jbxx`
- `Sb_Sbzt`
- `Sb_Jfgs`

### 2. 评审选择

在申报池变化后，再计算评审边界、入围和挤出：

- 评分分布与分位
- 阶段通过情况
- 入选项目数
- 主题间的竞争和替代

输入主要来自：

- `PS_XMPSXX`

### 3. 立项/合同配置

对评审入选结果施加预算、配额和合同配置规则：

- 立项数量
- 合同专项经费
- 平均资助强度
- 主题预算占比

输入主要来自：

- `Ht_XMLXXX`
- `Ht_Jbxx`
- `Ht_Jfgs`

### 4. 结构外溢

最后再从项目组合变化映射到组合结构变化：

- 协作密度
- 主题中心性
- 主题迁移强度
- 机构集中度与分散度

输入主要来自：

- 图谱关系数据
- 前三步生成的项目与主题组合变化

这一层是二阶结构结果，默认属于代理推演，不得倒过来直接主导前面三层。

## 三、引擎分层

建议将引擎拆为五层，而不是把所有逻辑混成单次脚本。

### 1. baseline assembly

从真实数据组装 baseline world，形成推演起点：

- 项目生命周期事实
- 主题年度状态
- 图谱结构状态
- 约束边界

### 2. scenario compilation

把 `Scenario Contract` 编译成可执行规则：

- 动作归类到治理阶段
- 目标对象标准化
- 规则冲突检测
- 约束检查

### 3. stage transition

按治理流程依次更新状态：

- application response module
- review selection module
- award and contract module
- structural spillover module

### 4. comparison and attribution

对比 baseline 与 scenario：

- 绝对变化
- 相对变化
- 挤出效应
- 主要变化来源

### 5. explanation and disclosure

输出证据链和边界说明：

- 哪些是观测推断
- 哪些是代理推断
- 哪些结论受结构假设驱动

## 四、各阶段可计算内容

## 1. 申报响应模块

可计算：

- `application_count`
- `requested_special_funding`
- 主题申报份额变化
- 新进入主体占比变化

当前做法应基于历史 `topic × year` 或更细粒度群组状态，结合场景中的资格、额度、优先级规则，得到反事实申报池。

不能直接说：

- 某政策一定会让全省真实创新意愿上升
- 某领域人才一定会因此大量流入

## 2. 评审选择模块

可计算：

- 评审阈值变化下的入围边界
- 不同主题的挤入与挤出
- 分数段竞争压力变化
- 立项概率代理变化

当前应依赖 `PS_XMPSXX` 的评分、排序、阶段进入信息。

这一步可以形成“选择压力”与“入选边界”的代理判断，但不能把它包装成完整因果识别。

## 3. 立项/合同配置模块

可计算：

- `funded_count`
- `contract_funding_amount`
- `avg_award_size`
- 预算占比变化

这里必须显式执行预算与配额约束，不能先算出结果再回头硬凑预算平衡。

## 4. 结构外溢模块

可计算或可代理计算：

- `collaboration_density`
- `topic_centrality`
- `migration_strength`
- `organization_concentration`

这些指标只表示组合结构可能如何变化，不表示真实验收、真实转化或真实产业回报。

## 五、引擎的硬性原则

### 1. 不允许跨层直接改结果

例如：

- 不能因为“想收紧某主题”就直接把 `funded_count` 减掉
- 不能因为“鼓励协作”就直接把 `collaboration_density` 加上去

必须沿治理流程把变化传导过去。

### 2. 不允许缺阶段硬算

如果某场景动作主要作用于评审环节，但当前样本无法构造稳定的评审边界，则引擎应：

- 降级为弱推演
或
- 明确拒绝输出该类硬结论

### 3. 不允许把代理结果说成真实结果

例如：

- 图谱迁移强度变化 != 真实产业迁移
- 协作密度变化 != 真实协同创新产出

## 六、引擎输入与输出关系

输入：

- `baseline_snapshot`
- `scenario_contract`
- `engine_config`

输出：

- `stage_results`
- `topic_results`
- `portfolio_results`
- `evidence_chain`
- `limitations`

其中 `engine_config` 只用于内部参数控制，不应对领导暴露为政策选项。

## 七、推荐的执行顺序

```text
真实项目链路与图谱
  -> baseline snapshot
  -> scenario contract compile
  -> application response
  -> review selection
  -> award / contract allocation
  -> structural spillover
  -> baseline vs scenario compare
  -> evidence-backed explanation
```

## 八、结果可信度分层

场景引擎对每个输出都必须附带可信度标签：

- `observed-grounded`
  主要由真实业务事实聚合得到
- `proxy-grounded`
  主要由评分、图谱或结构代理得到
- `assumption-heavy`
  主要由规则假设推动
- `unsupported`
  当前数据无法支撑

没有这层标签，领导看到的只是看起来很完整的图，而不是可审计的推演结果。
