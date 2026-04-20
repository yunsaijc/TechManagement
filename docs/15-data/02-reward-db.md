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
| t_xm_gzy | 奖励附件及签章识别结果 | ~ |
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

### t_xm_gzy - 奖励附件

用于存储奖励平台签字盖章相关附件及识别结果。

| 字段 | 类型 | 说明 |
|------|------|------|
| id | varchar(64) | 主键 |
| XMBH | varchar(40) | 项目编号 |
| LX | varchar(10) | 附件类型编码 |
| XH | decimal / double | 附件序号 |
| FJMC | varchar | 附件名称 |
| FJLJ | varchar | 附件文件名/相对路径片段 |
| ND | varchar(10) | 年度 |
| wcr_id | varchar(64) | 关联明细行 ID |
| seal_check | varchar / int | 盖章检查结果 |
| seal_info | text | 盖章识别详情 |
| signature_check | varchar / int | 签字检查结果 |
| signature_info | text | 签字识别详情 |

`LX` 与材料字典类型对应关系：

| LX | `doc_type` | 中文名称 | 注释 |
|------|------|------|------|
| `10.1` | `tjdwyj` | 提名单位意见表 | 校验提名单位名称与提名单位盖章 |
| `10.2` | `gzdwyj` | 候选人工作单位意见 | 校验候选人工作单位名称与单位盖章 |
| `10.3` | `wcr` / `wjwcr` | 主要完成人情况表 / 外籍主要完成人情况表 | 校验姓名、工作单位、完成单位、签字、盖章 |
| `10.4` | `wcdw` | 主要完成单位情况表 | 校验单位名称、法定代表人、单位盖章 |
| `10.5` | `hzdw` | 河北省内主要合作单位情况表 | 校验合作单位名称与单位盖章 |

SMB 文件路径组装规则：

```text
K:\FJCL\static\rpw\gzy{ND}\{XMTJH}\{FJLJ}
```

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
    ├── 1:N → 奖励附件 (t_xm_gzy)      [通过 XMBH 关联]
    ├── 1:N → 完成人 (t_xm_zywcr)     [通过 XMBH 关联]
    ├── 1:N → 完成单位 (t_xm_xmwcdwqk) [通过 XMBH 关联]
    ├── 1:1 → 形审结果 (t_xm_xsjg)    [通过 XMBH 关联]
    └── 1:1 → 评审信息 (ps_xmpsxx)    [通过 XMBH 关联]

专家 (t_zjxx)
    ├── 技术领域: SXXK1~5 → sys_subject
    ├── 工作单位: GZDWID → t_gzdwxx
    └── 推荐单位: TJDWID → t_tjdwxx
```

奖励平台签字盖章专项当前确认的附件关联关系：

| `doc_type` | `LX` | 目标表 | 关联方式 | 核验字段 |
|------|------|------|------|------|
| `tjdwyj` | `10.1` | `t_xm_tjdwxx` | `t_xm_gzy.XMBH -> t_xm_ggjbxx(XMBH, ND, TJDWBH) -> t_xm_tjdwxx(TJDWBH, ND)` | `tjdwqc` |
| `gzdwyj` | `10.2` | `t_xm_tcgxgrjbxx` | `t_xm_gzy.XMBH -> t_xm_tcgxgrjbxx.XMBH` | `grdwmc` |
| `wcr` / `wjwcr` | `10.3` | `t_xm_zywcr` | `t_xm_gzy.wcr_id -> t_xm_zywcr.id` | `xm`, `gzdw`, `wcdw` |
| `wcdw` | `10.4` | `t_xm_xmwcdwqk` | `t_xm_gzy.wcr_id -> t_xm_xmwcdwqk.id` | `dwmc`, `fddbr` |
| `hzdw` | `10.5` | `t_xm_gjhzhzdw` | `t_xm_gzy.wcr_id -> t_xm_gjhzhzdw.ID` | `dwmc` |

当前已确认：`ND + XMTJH + FJLJ` 可唯一定位一条奖励附件记录。

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
