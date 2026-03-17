# 📦 奖励评审数据库

## 概述

包含专家信息、项目申报、形式审查、评审结果等数据。

## 连接信息

> ⚠️ **注意**: 连接信息存储在配置文件中，请勿提交到版本控制

| 项目 | 值 |
|------|-----|
| 地址 | `{{REWARD_DB_HOST}}` |
| 用户名 | `{{REWARD_DB_USER}}` |
| 密码 | `{{REWARD_DB_PASSWORD}}` |

---

## 核心表清单

### 1. 专家信息库 (zjknew)

| 表名 | 用途 | 数据量 |
|------|------|-------|
| t_zjxx | 专家基本信息 | ~ |
| t_gzdwxx | 工作单位信息 | ~ |
| t_tjdwxx | 推荐单位信息 | ~ |
| t_jsly | 技术领域（树形） | ~ |

### 2. 业务数据 (xmsbnew)

| 表名 | 用途 | 数据量 |
|------|------|-------|
| t_xm_ggjbxx | 项目/奖励基本信息 | ~ |
| t_xm_zywcr | 主要完成人 | ~ |
| t_xm_xmwcdwqk | 完成单位情况 | ~ |
| t_xm_cl | 项目材料 | ~ |
| t_xm_xsjg | 形式审查结果 | ~ |
| ps_xmpsxx | 评审信息（网评/行评/总评） | ~ |

### 3. 学科与评审组 (hbstanew)

| 表名 | 用途 |
|------|------|
| sys_subject | 学科代码 |
| t_pszglqx | 评审组管理权限 |

---

## 核心表结构

### t_zjxx - 专家基本信息

| 字段 | 类型 | 说明 |
|------|------|------|
| id | varchar(64) | 主键 |
| ZJNO | varchar(20) | 专家号 |
| XM | varchar(40) | 姓名 |
| XB | varchar(10) | 性别 |
| CSRQ | datetime | 出生日期 |
| YDDH | varchar(30) | 移动电话 |
| DZYX | varchar(100) | 电子邮箱 |
| GZDWID | varchar(10) | 工作单位ID |
| SXXK1~SXXK5 | varchar(8) | 熟悉学科1~5 |
| ZC | text | 职称 |
| RKZT | varchar(255) | 入库状态 |
| RKSJ | datetime | 入库时间 |

### t_gzdwxx - 工作单位

| 字段 | 类型 | 说明 |
|------|------|------|
| GZDWID | varchar(8) | 工作单位ID |
| GZDWMC | varchar(120) | 工作单位名称 |
| ZZJGDM | varchar(10) | 统一社会信用代码 |

### t_tjdwxx - 推荐单位

| 字段 | 类型 | 说明 |
|------|------|------|
| TJDWID | varchar(5) | 推荐单位ID |
| TJDWMC | varchar(100) | 推荐单位名称 |

### t_jsly - 技术领域

| 字段 | 类型 | 说明 |
|------|------|------|
| id | varchar(64) | 主键 |
| parent_id | varchar(64) | 上级ID |
| code | varchar(100) | 编码 |
| name | varchar(100) | 名称 |

### t_xm_ggjbxx - 项目基本信息

| 字段 | 类型 | 说明 |
|------|------|------|
| XMBH | varchar(40) | 项目编号（主键） |
| XMMC | varchar(120) | 项目名称 |
| XMTJH | varchar(40) | 项目推荐号 |
| JZBH | varchar(5) | 奖种编号 |
| XKDZBH | varchar(5) | 学科大组编号 |
| XKDZMC | varchar(70) | 学科大组名称 |
| XMXK1~3 | varchar(8) | 项目学科1~3 |
| TJDWBH | varchar(10) | 推荐单位编号 |
| ND | varchar(10) | 年度 |

### t_xm_zywcr - 主要完成人

| 字段 | 类型 | 说明 |
|------|------|------|
| XMBH | varchar(40) | 项目编号 |
| XH | double | 序号 |
| PM | double | 排名 |
| XM | varchar(30) | 姓名 |
| GZDW | varchar(200) | 工作单位 |
| WCDW | varchar(200) | 完成单位 |
| SFZH | varchar(30) | 身份证号 |

### t_xm_xmwcdwqk - 完成单位情况

| 字段 | 类型 | 说明 |
|------|------|------|
| XMBH | varchar(40) | 项目编号 |
| DWMC | varchar(120) | 单位名称 |
| DWPM | decimal(5,0) | 排名 |

### t_xm_xsjg - 形式审查结果

| 字段 | 类型 | 说明 |
|------|------|------|
| XMBH | varchar(40) | 项目编号 |
| XMTJBH | varchar(255) | 项目提名号 |
| SFHG | varchar(20) | 形审是否合格 |
| BHGXXYY | mediumtext | 不合格详细原因 |
| JSSFHG | varchar(20) | 机审是否合格 |

### ps_xmpsxx - 评审信息

| 字段 | 类型 | 说明 |
|------|------|------|
| XMBH | varchar(40) | 项目编号 |
| XMMC | varchar(255) | 项目名称 |
| WPZBH | varchar(5) | 网评组号 |
| HPZBH | char(2) | 行评组号 |
| XSJG | varchar(64) | 形式审查结果 |
| SFJRWP | varchar(64) | 是否进入网评 |
| WPFS | decimal(65,2) | 网评分数 |
| HPZDF | decimal(65,2) | 行评总得分 |
| HPJYDJ | decimal(65,0) | 行评建议等级 |

---

## 数据关系

```
项目 (t_xm_ggjbxx)
    ├── 1:N → 完成人 (t_xm_zywcr)     [通过 XMBH 关联]
    ├── 1:N → 完成单位 (t_xm_xmwcdwqk) [通过 XMBH 关联]
    ├── 1:1 → 形审结果 (t_xm_xsjg)    [通过 XMBH 关联]
    └── 1:1 → 评审信息 (ps_xmpsxx)    [通过 XMBH 关联]

专家 (t_zjxx)
    ├── 技术领域: SXXK1~5 → sys_subject
    ├── 工作单位: GZDWID → t_gzdwxx
    └── 推荐单位: TJDWID → t_tjdwxx
```

---

## 使用示例

```python
# 接入专家数据
from src.common.database import get_expert_repo

expert_repo = get_expert_repo()
experts = await expert_repo.list_by_subject("010101")

# 接入项目数据
from src.common.database import get_project_repo

project_repo = get_project_repo()
project = await project_repo.get_by_xmbh("2024-XM-001")
```

---

## 相关文档

- [数据接入概述 →](01-overview.md)
- [项目评审数据库 →](03-project-db.md)
- [扩展指南 →](04-extension.md)
