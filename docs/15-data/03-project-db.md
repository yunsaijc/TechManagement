# 📋 项目评审数据库

## 概述

包含项目申报、评审过程、专家评审等数据。

当前分组功能测试默认使用项目评审库中的**审核通过项目子集**。该子集基于申报基础信息表与申报状态表的关联结果生成，用于保证不同版本之间的分组结果可横向对比。

## 连接信息

> ⚠️ **注意**: 连接信息存储在配置文件中，请勿提交到版本控制

| 项目 | 值 |
|------|-----|
| 地址 | `{{PROJECT_DB_HOST}}` |
| 数据库 | `{{PROJECT_DB_NAME}}` |
| 用户名 | `{{PROJECT_DB_USER}}` |
| 密码 | `{{PROJECT_DB_PASSWORD}}` |

---

## 核心表清单

### 1. 项目信息

| 表名 | 用途 |
|------|------|
| Ht_Xmxx | 项目信息补充（投资、经费等） |
| Ht_Jbxx | 合同基本信息 |
| Ht_Jfgs | 合同经费概算 |
| Ht_XMLXXX | 立项信息 |
| Sb_Jbxx | 申报书基本信息 |
| Sb_Jfgs | 申报经费概算 |
| Sb_Sbzt | 申报状态、审核状态 |
| Sb_Jj | 项目简介（xmjj） |
| PS_XMPSXX | 项目评审信息 |

### 2. 学科分类

| 表名 | 用途 |
|------|------|
| sys_xkfl | 学科分类代码（用于项目分组） |

### 3. 评审流程

| 表名 | 用途 |
|------|------|
| PS_WLPS_ZJDL | 网评专家登录 |
| PS_ZHPS_ZJDF | 综合评审打分 |

### 3. 专家信息

| 表名 | 用途 |
|------|------|
| ZJK_ZJXX | 专家基本信息 |
| ZJK_DRPWQK | 专家担任评委情况 |

---

## 核心表结构

### Ht_Xmxx - 项目信息补充

| 字段 | 类型 | 说明 |
|------|------|------|
| id | int | 主键 |
| xmssly | varchar(32) | 项目所属领域 |
| cgjsly | varchar(64) | 成果技术来源 |
| cglydy | varchar(64) | 成果来源地域 |
| ztz | varchar(32) | 总投资 |
| xmjf | varchar(32) | 项目经费 |
| kjtpzdhz | varchar(255) | 科技特派团项目 |

### Sb_Jbxx - 申报书基本信息

| 字段 | 类型 | 说明 |
|------|------|------|
| id | varchar(64) | 主键 |
| xmmc | nvarchar(1000) | 项目名称 |
| zxmc | varchar(250) | 专项名称 |
| zndm | varchar(250) | 指南代码 |
| cddwMc | varchar(250) | 承担单位名称 |
| dwmc | varchar(250) | 单位名称（汉字） |
| cddwXydm | varchar(250) | 社会统一信用代码 |
| xmFzr | nvarchar(250) | 项目负责人 |
| cddwFzrsj | varchar(250) | 负责人手机 |
| cddwFzryx | varchar(250) | 负责人邮箱 |
| year | varchar(10) | 年度 |
| starttime | date | 开始日期 |
| endtime | date | 结束日期 |

### Sb_Sbzt - 申报状态信息

| 字段 | 类型 | 说明 |
|------|------|------|
| onlysign | varchar(64) | 与 `Sb_Jbxx.id` 关联 |
| gkAudit | varchar(10) | 公开/业务审核状态 |

> 说明：分组测试场景会使用 `Sb_Jbxx` 与 `Sb_Sbzt` 的关联结果，仅保留审核通过的数据记录。

### sys_xkfl - 学科分类

| 字段 | 类型 | 说明 |
|------|------|------|
| id | varchar(64) | 主键 |
| code | varchar(20) | 学科代码 (如 460, 46010, 4654030) |
| name | varchar(200) | 学科名称 |
| parent_id | varchar(64) | 父级ID |
| parent_ids | varchar(500) | 父级链 (如 0,1,460,) |

**学科层级**：
- 一级学科：3位 (如 460, 020)
- 二级学科：5位 (如 46010, 46540)  
- 三级学科：7位 (如 4654030)

### ZJK_ZJXX - 专家基本信息

| 字段 | 类型 | 说明 |
|------|------|------|
| ZJNO | varchar(32) | 专家编号 (主键) |
| XM | varchar(64) | 姓名 |
| XB | varchar(4) | 性别 |
| SXXK1 | varchar(32) | 熟悉学科1 |
| SXXK2 | varchar(32) | 熟悉学科2 |
| SXXK3 | varchar(32) | 熟悉学科3 |
| SXXK4 | varchar(32) | 熟悉学科4 |
| SXXK5 | varchar(32) | 熟悉学科5 |
| SXZY | varchar(256) | 擅长专业 |
| YJLY | varchar(1024) | 研究领域 |
| LWLZ | varchar(1024) | 论文论著 |
| GZDW | varchar(256) | 工作单位 |

**注意**：专家学科代码使用与项目相同的 `sys_xkfl` 分类体系。

### Sb_Jfgs - 申报经费概算

| 字段 | 类型 | 说明 |
|------|------|------|
| id | int | 主键 |
| yskmbh | int | 预算科目编号 |
| zxjf | float | 专项经费 |
| zcjf | float | 自筹经费 |
| ptjf | float | 配套经费 |
| onlysign | varchar(64) | 与 `Sb_Jbxx.id` 关联 |

### Ht_Jbxx - 合同基本信息

| 字段 | 类型 | 说明 |
|------|------|------|
| id | varchar(64) | 主键 |
| xmmc | nvarchar(1000) | 项目名称 |
| xmbh | varchar(64) | 项目编号 |
| onlysign | varchar(64) | 与 `Sb_Jbxx.id` 关联 |
| htxmlxid | varchar(64) | 立项信息表id |

### Ht_Jfgs - 合同经费概算

| 字段 | 类型 | 说明 |
|------|------|------|
| id | int | 主键 |
| yskmbh | int | 预算科目编号 |
| zxjf | numeric | 专项经费 |
| zcjf | numeric | 自筹经费 |
| ptjf | float | 配套经费 |
| onlysign | varchar(64) | 与 `Ht_Jbxx.id` 关联 |

### Ht_XMLXXX - 立项信息

| 字段 | 类型 | 说明 |
|------|------|------|
| id | int | 主键 |
| XMBH | varchar(64) | 项目ID |
| SFLX | int | 是否立项 |
| LXBH | varchar(50) | 立项项目编号 |
| LXJF | numeric | 立项经费 |
| jybkz | numeric | 总拨款 |
| ybk | numeric | 已拨款 |
| bk | numeric | 未拨款 |

### PS_XMPSXX - 项目评审信息

| 字段 | 类型 | 说明 |
|------|------|------|
| XMBH | varchar(64) | 项目编号 |
| ND | varchar(10) | 年度 |
| CSJG | varchar(64) | 初审结果 |
| CSYJ | varchar(4000) | 形审意见 |
| SFJRWP | varchar(5) | 是否进入网评 |
| WPZBH | varchar(64) | 网评组编号 |
| WPFS | decimal | 网评分数 |
| Wpfspm | varchar(50) | 网评组排名 |
| wpsftg | varchar(5) | 网评是否通过 |
| SFJRFS | varchar(5) | 是否进入复审 |
| FSFS | decimal | 复审分数 |
| SFJRZP | int | 是否进入总评 |
| L1_ZPPS1 | int | 总评一轮同意票数 |
| L2_ZPPS1 | int | 总评二轮同意票数 |
| ZPZZJG | int | 总评最终结果 |
| SFLX | int | 是否立项 |
| LXBH | varchar(50) | 立项项目编号 |
| LXJF | float | 立项经费 |

### PS_WLPS_ZJDL - 网评专家登录

| 字段 | 类型 | 说明 |
|------|------|------|
| PSZBH | varchar(100) | 评审组编号 |
| ZJBH | varchar(10) | 专家编号 |
| ZJXM | varchar(500) | 专家姓名 |
| PWSX | int | 评委顺序 |
| PSZXMS | int | 评审组项目数 |
| WCXMS | int | 完成项目数 |
| PSKSSJ | datetime | 评审开始时间 |
| PSJZSJ | datetime | 评审截止时间 |

### zjk_jbxx - 专家基本信息

| 字段 | 类型 | 说明 |
|------|------|------|
| sl1~sl16 | varchar(255) | （字段名无注释，需进一步探查） |

---

## 评审流程字段

```
申报 → 初审(CS) → 网评(WP) → 复审(FS) → 总评(ZP) → 立项(LX)

关键字段：
├── 初审阶段
│   ├── CSJG: 初审结果
│   └── CSYJ: 形审意见
│
├── 网评阶段
│   ├── SFJRWP: 是否进入网评
│   ├── WPFS: 网评分数
│   └── wpsftg: 网评是否通过
│
├── 复审阶段
│   ├── SFJRFS: 是否进入复审
│   └── FSFS: 复审分数
│
├── 总评阶段
│   ├── SFJRZP: 是否进入总评
│   ├── L1_ZPPS1: 一轮同意票数
│   └── ZPZZJG: 总评最终结果
│
└── 立项
    ├── SFLX: 是否立项
    ├── LXBH: 立项编号
    └── LXJF: 立项经费
```

---

## 数据关系

```
项目申报 (Sb_Jbxx)
        ├── 1:1 → 申报状态 (Sb_Sbzt)      [通过 Sb_Sbzt.onlysign = Sb_Jbxx.id]
        ├── 1:N → 申报经费概算 (Sb_Jfgs)  [通过 Sb_Jfgs.onlysign = Sb_Jbxx.id]
        ├── 1:1 → 评审信息 (PS_XMPSXX)   [通过 PS_XMPSXX.XMBH = Sb_Jbxx.id]
        ├── 1:1 → 立项信息 (Ht_XMLXXX)   [通过 Ht_XMLXXX.XMBH = Sb_Jbxx.id]
        └── 1:1 → 合同基本信息 (Ht_Jbxx) [通过 Ht_Jbxx.onlysign = Sb_Jbxx.id]
                 └── 1:N → 合同经费概算 (Ht_Jfgs) [通过 Ht_Jfgs.onlysign = Ht_Jbxx.id]
```

---

## 分组测试数据集说明

分组功能当前统一采用一份**固定、脱敏、可复现**的测试数据集：

- 来源：`Sb_Jbxx` 左关联 `Sb_Sbzt`
- 选取范围：某固定业务批次下的项目
- 过滤规则：仅保留审核通过记录
- 使用目的：
    - 分组算法调试
    - 回归测试
    - 不同策略效果对比

为避免敏感信息泄露：

- 文档中不记录真实批次编码
- 示例查询不展示完整生产条件
- 对外说明仅保留“固定业务批次 + 审核通过”的抽象描述

---

## 使用示例

```python
# 连接项目评审数据库
from src.common.database import get_project_db_connection

# 查询项目信息
conn = get_project_db_connection()
cursor = conn.cursor()
cursor.execute("SELECT xmmc, year FROM Sb_Jbxx WHERE year = '2024'")
projects = cursor.fetchall()
```

---

## 相关文档

- [数据接入概述 →](01-overview.md)
- [奖励评审数据库 →](02-reward-db.md)
- [扩展指南 →](04-extension.md)
