# 📝 开发规范

## 操作原则（不可妥协）

> 遵守这些原则是不可商量的底线。

1. **正确性优于技巧**：优先选择无聊但可读的解决方案，易于维护。

2. **最小可行改动**：最小化影响范围；除非能显著降低风险或复杂度，否则不要重构相邻代码。

3. **利用现有模式**：在引入新的抽象或依赖之前，遵循项目既定的约定。

4. **证明它有效**：「看起来对」不算完成。必须用测试来验证。

5. **明确不确定性**：如果无法验证某事，明确说明并提出最安全的下一步验证方案。

6. **遵循文档设计**：代码实现必须始终遵循 `docs/` 中的文档设计，文档是代码的蓝图。

7. **避免太多兜底**：不要总是增加try等兜底逻辑，有错直接报才能快速定位原因。

---

## 文档即设计

> 代码必须与文档保持一致。文档是设计的唯一真相来源。

## 文档即设计

> 代码必须与文档保持一致。文档是设计的唯一真相来源。

### 文档与代码的对应关系

| 文档目录 | 对应代码目录 | 说明 |
|----------|--------------|------|
| `docs/00-global/` | `src/` 根目录 | 全局配置、根模块 |
| `docs/10-common/` | `src/common/` | 通用组件 |
| `docs/20-review/` | `src/services/review/` | 形式审查服务 |
| `docs/30-project/` | `src/services/project/` | 项目评审服务 |
| `docs/40-award/` | `src/services/award/` | 奖励评审服务 |
| `docs/50-expert/` | `src/services/expert/` | 专家匹配服务 |

### 遵循原则

1. **先文档后代码**：开发前必须先有对应的设计文档
2. **文档驱动**：代码实现必须严格遵循文档中的设计
3. **同步更新**：文档变更必须同步到代码，反之亦然

### 禁止事项

- ❌ **禁止**在代码中创建文档未定义的类/模块
- ❌ **禁止**修改代码而不更新对应文档
- ❌ **禁止**使用与文档不一致的命名
- ❌ **禁止**实现文档未描述的功能
- ❌ **禁止**擅自修改文档


## 开发流程

遵循以下流程确保开发质量：

```
┌─────────────┐
│  待办 (Todo)  │  ← 列出要做的功能，分解任务
└──────┬──────┘
       │
       ▼
┌─────────────┐
│  计划 (Plan) │  ← 给用户方案，详细说明实现思路
└──────┬──────┘
       │
       ▼
┌─────────────┐
│ 确认 (Confirm)│  ← 等用户确认方案后再开发
└──────┬──────┘
       │
       ▼
┌─────────────┐
│ 开发 (Develop)│  ← 实现代码
└──────┬──────┘
       │
       ▼
┌─────────────┐
│ 自测 (Self-test)│ ← 自己测试，确保功能正常
└──────┬──────┘
       │
       ▼
    重复下一个功能
```

---

## 目录结构

```
src/
├── app/                    # API 层
│   ├── main.py             # FastAPI 应用
│   └── routes/             # 路由
│
├── services/               # 业务服务层
│   ├── base.py            # 基础服务抽象
│   ├── review/            # 形式审查服务
│   ├── project/           # 项目评审服务（未来）
│   ├── award/             # 奖励评审服务（未来）
│   └── expert/            # 专家匹配服务（未来）
│
├── common/                 # 通用组件层
│   ├── models/            # 数据模型
│   ├── llm/               # LLM 封装
│   ├── file_handler/      # 文件处理
│   ├── vision/            # 视觉能力
│   └── tools/             # 工具函数
│
├── core/                   # 核心基础
│   ├── config.py          # 配置管理
│   ├── logger.py          # 日志
│   └── constants.py       # 常量
│
└── utils/                  # 工具
```

---

## 命名规范

### 文件命名

- **Python 文件**: `snake_case`（如 `review_agent.py`）
- **目录**: `snake_case`（如 `file_handler/`）
- **测试文件**: `test_xxx.py` 或 `xxx_test.py`

### 类命名

- **类名**: `PascalCase`（如 `ReviewAgent`）
- **抽象基类**: 以 `Base` 开头（如 `BaseRule`）
- **异常类**: 以 `Error` 结尾（如 `ValidationError`）

### 函数/方法命名

- **函数**: `snake_case`（如 `extract_text`）
- **私有方法**: 以 `_` 开头（如 `_parse_document`）
- **异步方法**: 以 `async_` 开头或使用 `async def`

### 常量

- **常量**: `UPPER_SNAKE_CASE`（如 `MAX_FILE_SIZE`）

---

## 注释规范

### 中文优先

所有注释使用中文，说明代码意图。

```python
# 获取文档中的签名区域
def extract_signature_region(image: Image) -> List[BoundingBox]:
    """提取图像中的签名区域
    
    Args:
        image: 输入图像
        
    Returns:
        签名区域列表
    """
    pass
```

### 文档字符串

使用 Google 风格的文档字符串：

```python
def process_document(file: UploadFile) -> Document:
    """处理上传的文档文件
    
    Args:
        file: 上传的文件对象
        
    Returns:
        解析后的文档对象
        
    Raises:
        UnsupportedFormatError: 不支持的文件格式
        
    Example:
        >>> file = UploadFile(...)
        >>> doc = process_document(file)
        >>> print(doc.text)
    """
```

---

## 代码组织

### 导入顺序

1. 标准库
2. 第三方库
3. 本地模块（相对导入）

```python
# 标准库
import asyncio
from typing import List, Optional
from datetime import datetime

# 第三方库
from pydantic import BaseModel
from langchain_core.runnables import Runnable

# 本地模块
from src.common.models import FileMeta
from src.services.base import BaseService
```

### 类型注解

- 使用 `typing` 模块进行类型注解
- 复杂类型使用 TypeAlias

```python
from typing import List, Dict, Union, TypeAlias

# 类型别名
JSON: TypeAlias = Dict[str, "JSON"] | List["JSON"] | str | int | float | bool | None

# 泛型
from typing import Generic, TypeVar

T = TypeVar("T")
Result = Dict[str, T]
```

---

## 工程最佳实践

### 1. API/接口规范

- **围绕稳定接口设计边界**：接口一旦确定，尽量避免破坏性变更
- **优先选择添加可选参数而非复制代码路径**：减少代码重复
- **保持错误语义一致**：相同的错误场景返回相同的错误码和消息

```python
# 好的做法：添加可选参数
def process_file(path: str, options: ProcessOptions = None) -> Result:
    options = options or ProcessOptions()
    # ...

# 不好的做法：复制代码路径
def process_file_v1(path: str) -> Result:
    # ... 重复代码

def process_file_v2(path: str, option: str) -> Result:
    # ... 更多重复
```

### 2. 测试策略

- **添加能捕获 bug 的最小测试**：不要为了覆盖率而写无意义的测试
- **避免与偶发实现细节绑定的脆弱测试**：测试行为而非实现

```python
# 好的做法：测试行为
def test_review_returns_results():
    result = agent.process(file_data, "pdf")
    assert result.summary is not None

# 不好的做法：脆弱的测试（依赖内部实现细节）
def test_review_uses_specific_llm():
    assert agent.llm.model_name == "gpt-4o"  # 脆弱
```

### 3. 类型安全与不变量

- **避免使用抑制**（`Any`、`# type: ignore`），除非项目明确允许且你没有替代方案
- **在边界处编码不变量**，而非分散的检查

```python
# 好的做法：定义清晰的不变量
class ReviewResult:
    results: List[CheckResult]
    
    def __init__(self, **data):
        # 在边界处验证
        if not data.get('results'):
            raise ValueError("results cannot be empty")
        super().__init__(**data)

# 不好的做法：分散的类型抑制
result = something_unsafe()  # type: ignore
```

### 4. 依赖规范

- **不要添加新依赖**，除非现有技术栈无法干净地解决且好处明确
- **优先选择标准库/现有工具**

```bash
# 决策流程
1. 现有技术栈能否解决？ → 能 → 不添加依赖
2. 新依赖好处是否明确？ → 否 → 不添加依赖
3. 确实需要 → 添加，并说明理由
```

### 5. 安全与隐私

- **永远不要在代码、日志或聊天输出中引入机密材料**：API Key、密码等
- **将用户输入视为不可信**：验证、清理和约束
- **优先选择最小权限**

```python
# 好的做法
def process_file(filename: str):
    # 验证输入
    if ".." in filename or "/" in filename:
        raise ValueError("invalid filename")
    
    # 限制大小
    if file_size > MAX_SIZE:
        raise ValueError("file too large")

# 不好的做法：信任用户输入
def process_file(filename: str):
    os.remove(filename)  # 危险！
```

### 6. 性能

- **避免过早优化**：先让代码工作，再考虑性能
- **要修复**：明显的 N+1 模式、意外的无限循环、重复的重计算
- **有疑问时测量，别猜测**

```python
# 需要修复的性能问题
def get_all_users():
    users = []
    for user_id in user_ids:
        users.append(db.get_user(user_id))  # N+1
    return users

# 优化后
def get_all_users():
    return db.get_users(user_ids)  # 批量查询
```

---

## Git 提交规范

### 提交信息格式

```
<类型>(<范围>): <描述>

[可选的正文]

[可选的脚注]
```

### 类型说明

| 类型 | 说明 |
|------|------|
| `feat` | 新功能 |
| `fix` | Bug 修复 |
| `docs` | 文档更新 |
| `style` | 代码格式（不影响功能） |
| `refactor` | 重构 |
| `test` | 测试相关 |
| `chore` | 构建/工具相关 |

### 示例

```
feat(review): 添加签名检查规则

实现了基于目标检测的签名识别功能，
支持 PDF 和图片格式的文档审查。

Closes #123
```

---

## 测试规范

### 单元测试

- 测试文件放在 `tests/` 目录
- 使用 `pytest` 框架
- 异步测试使用 `pytest-asyncio`

```python
import pytest
from src.common.llm import OpenAIClient

@pytest.fixture
def llm_client():
    return OpenAIClient()

@pytest.mark.asyncio
async def test_generate(llm_client):
    result = await llm_client.generate("你好")
    assert result is not None
```

### 测试覆盖

- 核心业务逻辑必须包含测试
- 边界条件和异常处理需要测试

---

## 错误处理与恢复模式

### 异常类定义

```python
class ReviewError(Exception):
    """审查基础异常"""
    pass

class DocumentParseError(ReviewError):
    """文档解析异常"""
    pass

class ValidationError(ReviewError):
    """验证异常"""
    pass
```

### 错误处理原则

- 捕获具体异常，避免 bare `except`
- 记录详细错误信息
- 返回有意义的错误消息

### 「停产整顿」规则

> 如果发生任何意外情况（测试失败、构建错误、行为回归）：

1. **停止添加功能**：不要在有问题的代码上继续开发
2. **保留证据**：记录错误输出、复现步骤
3. **回到诊断并重新规划**：找到根本原因后再继续

### 分诊清单（按顺序使用）

```
1. 可靠复现
   └─ 能够稳定地触发问题
   
2. 定位失败点
   └─ 找到具体哪个测试/功能失败
   
3. 简化为最小失败情况
   └─ 去掉无关代码，只保留能触发问题的最小部分
   
4. 修复根本原因
   └─ 解决本质问题，而非症状
   
5. 回归测试
   └─ 确保修复没有引入新问题
```

```python
# 错误处理示例
async def process_review(file_data: bytes):
    try:
        # 业务逻辑
        result = await agent.process(file_data)
        return result
    except DocumentParseError as e:
        logger.error(f"文档解析失败: {e}")
        raise ReviewError(f"无法解析文档: {e}") from e
    except ValidationError as e:
        logger.warning(f"验证失败: {e}")
        raise
    except Exception as e:
        # 「停产整顿」：记录并重新抛出
        logger.error(f"未知错误: {e}", exc_info=True)
        raise ReviewError("系统错误，请稍后重试") from e
```
