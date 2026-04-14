# 趋势预判对象与指标

## 一、核心对象

趋势预判层建议统一以下对象：

- `Topic`
- `Project`
- `Program`
- `TalentPool`
- `Output`
- `Conversion`
- `TimeWindow`

## 二、对象说明

### 1. Topic

用于承载分析的主题单位，可以是：

- 指南方向
- 学科方向
- 技术方向
- 部门口径下的业务主题

关键属性建议包括：

- `topic_id`
- `topic_name`
- `topic_type`
- `parent_topic_id`
- `active_window`

### 2. Project

关键属性建议包括：

- `project_id`
- `topic_id`
- `year`
- `status`
- `funding`
- `organization`

### 3. TalentPool

关键属性建议包括：

- `headcount`
- `senior_ratio`
- `backbone_ratio`
- `collaboration_density`
- `cross_topic_mobility`

### 4. Output / Conversion

关键属性建议包括：

- `output_count`
- `high_value_output_count`
- `acceptance_rate`
- `conversion_rate`
- `conversion_lag`

## 三、指标层

趋势预判建议统一三类指标：

1. 规模指标
2. 结构指标
3. 效率指标

### 1. 规模指标

- 申报数
- 立项数
- 在研数
- 产出数
- 经费规模

### 2. 结构指标

- 主题集中度
- 人才层级分布
- 协作网络密度
- 跨主题迁移强度

### 3. 效率指标

- 转化率
- 单位经费产出
- 立项到产出时滞
- 高热度低产出比

## 四、时间设计

趋势预判至少需要区分三类时间窗：

- `observation_window`
- `comparison_window`
- `forecast_window`

没有稳定的时间窗设计，就无法把“变化”与“预测”区分开。
