# 🔧 扩展指南

本文档说明如何扩展接入新的数据库。

---

## 接入新数据库步骤

### 步骤 1: 探查表结构

在 `scripts/` 目录下编写探查脚本：

```python
# scripts/explore_new_db.py
import pymysql

DB_CONFIG = {
    "host": "192.168.0.xxx",
    "port": 3306,
    "user": "xxx",
    "password": "xxx",
}

DATABASES = {
    "new_db": "新数据库用途说明",
}

# ... 探查逻辑
```

运行探查：
```bash
uv run python scripts/explore_new_db.py
```

### 步骤 2: 分析表结构

识别核心表：
- 主键字段
- 关键业务字段
- 外键关联关系
- 时间字段

### 步骤 3: 创建数据模型

在 `src/common/database/models/` 下创建对应模型：

```python
# src/common/database/models/new_module.py
from sqlalchemy import String, DateTime
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

class Base(DeclarativeBase):
    pass

class NewTable(Base):
    __tablename__ = "table_name"
    __table_args__ = {"schema": "database_name"}
    
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    # ... 其他字段
```

### 步骤 4: 创建数据访问层

在 `src/common/database/` 下创建 repository：

```python
# src/common/database/repositories/new_repo.py
class NewRepository:
    def __init__(self, session):
        self.session = session
    
    async def list_by_condition(self, condition):
        # 查询逻辑
        pass
```

### 步骤 5: 注册到数据层

在 `src/common/database/__init__.py` 中导出：

```python
from src.common.database.repositories.new_repo import NewRepository

def get_new_repo() -> NewRepository:
    # 获取数据库连接的逻辑
    pass
```

### 步骤 6: 更新文档

1. 在 `01-overview.md` 中添加新数据库信息
2. 创建 `xx-db.md` 详细记录表结构
3. 更新本文档的数据库清单

---

## 数据库配置管理

所有数据库连接配置集中在 `src/common/database/config.py`：

```python
from pydantic_settings import BaseSettings

class DatabaseSettings(BaseSettings):
    # 已有数据库
    reward_host: str = "192.168.0.211"
    # ...
    
    # 新数据库
    new_host: str = "192.168.0.xxx"
    new_port: int = 3306
    new_user: str = "xxx"
    new_password: str = "xxx"
    new_database: str = "xxx"
```

---

## 最佳实践

| 实践 | 说明 |
|------|------|
| **只读优先** | 所有数据操作使用只读连接 |
| **按需加载** | 不一次性加载全部数据，使用分页 |
| **连接池** | 使用连接池管理数据库连接 |
| **异常处理** | 做好超时和重试机制 |
| **日志记录** | 记录关键查询日志 |

---

## 相关文档

- [数据接入概述 →](01-overview.md)
- [奖励评审数据库 →](02-reward-db.md)
- [项目评审数据库 →](03-project-db.md)
