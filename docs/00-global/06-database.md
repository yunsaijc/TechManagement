# 🗄️ 数据库配置

## 连接信息

### 奖励评审数据库

> ⚠️ **注意**: 连接信息存储在环境变量或配置中心，请勿提交到版本控制

| 项目 | 值 |
|------|-----|
| 地址 | `{{DB_REWARD_HOST}}` |
| 用户名 | `{{DB_REWARD_USER}}` |
| 密码 | `{{DB_REWARD_PASSWORD}}` |
| 数据库 | hbstanew, xmsbnew, zjknew |

### 项目评审数据库

| 项目 | 值 |
|------|-----|
| 地址 | `{{DB_PROJECT_HOST}}` |
| 数据库 | `{{DB_PROJECT_NAME}}` |
| 用户名 | `{{DB_PROJECT_USER}}` |
| 密码 | `{{DB_PROJECT_PASSWORD}}` |
| 驱动 | ODBC Driver 18 for SQL Server |

---

## 凭据管理

> ⚠️ **注意**: 当前数据库凭据为开发环境临时使用，上线前需：
> 1. 变更默认密码
> 2. 使用环境变量或密钥管理系统存储
> 3. 限制 IP 访问范围

## 开发环境配置

在项目根目录创建 `.env` 文件（**不要提交到版本控制**，已在 .gitignore 中忽略）：

```bash
# 奖励评审数据库 (MySQL)
DB_REWARD_HOST=your_host
DB_REWARD_PORT=3306
DB_REWARD_USER=your_user
DB_REWARD_PASSWORD=your_password

# 项目评审数据库 (SQL Server)
DB_PROJECT_HOST=your_host
DB_PROJECT_PORT=1433
DB_PROJECT_USER=your_user
DB_PROJECT_PASSWORD=your_password
```

---

## 相关文档

- [数据接入概述 →](../15-data/01-overview.md)
- [奖励评审数据库 →](../15-data/02-reward-db.md)
- [项目评审数据库 →](../15-data/03-project-db.md)
- [扩展指南 →](../15-data/04-extension.md)
