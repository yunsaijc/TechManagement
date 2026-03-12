# 📦 通用数据模型

## 概述

定义系统中通用的数据结构和类型，所有服务共享使用。

## 核心模型

### 文件相关

```python
# src/common/models/file.py
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional
from enum import Enum

class FileType(str, Enum):
    """文件类型"""
    PDF = "pdf"
    IMAGE = "image"
    DOCX = "docx"
    TXT = "txt"

class FileMeta(BaseModel):
    """文件元数据"""
    id: str = Field(..., description="文件唯一标识")
    filename: str = Field(..., description="文件名")
    file_type: FileType = Field(..., description="文件类型")
    size: int = Field(..., description="文件大小（字节）")
    mime_type: str = Field(..., description="MIME类型")
    created_at: datetime = Field(default_factory=datetime.now)
    storage_path: str = Field(..., description="存储路径")
    
class UploadFile(BaseModel):
    """上传文件"""
    file: bytes
    filename: str
    content_type: str
```

### 审查结果

```python
# src/common/models/review.py
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
from enum import Enum
from datetime import datetime

class CheckStatus(str, Enum):
    """检查状态"""
    PASSED = "passed"
    FAILED = "failed"
    WARNING = "warning"
    SKIPPED = "skipped"

class CheckResult(BaseModel):
    """检查结果"""
    item: str = Field(..., description="检查项名称")
    status: CheckStatus = Field(..., description="检查状态")
    message: str = Field(..., description="检查详情")
    evidence: Dict[str, Any] = Field(default_factory=dict, description="证据")
    confidence: float = Field(default=1.0, ge=0, le=1, description="置信度")

class ReviewResult(BaseModel):
    """审查结果"""
    id: str = Field(..., description="审查ID")
    document_type: str = Field(..., description="文档类型")
    results: List[CheckResult] = Field(default_factory=list, description="检查结果列表")
    summary: str = Field(..., description="审查总结")
    suggestions: List[str] = Field(default_factory=list, description="建议")
    processed_at: datetime = Field(default_factory=datetime.now)
    processing_time: float = Field(..., description="处理时间（秒）")
```

### 文档内容

```python
# src/common/models/document.py
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional

class BoundingBox(BaseModel):
    """边界框"""
    x: float
    y: float
    width: float
    height: float
    
    def to_xyxy(self) -> tuple:
        """转换为 xyxy 格式"""
        return (self.x, self.y, self.x + self.width, self.y + self.height)

class TextBlock(BaseModel):
    """文本块"""
    text: str
    bbox: BoundingBox
    page: int
    confidence: float = 1.0

class ImageRegion(BaseModel):
    """图像区域"""
    type: str  # "signature", "stamp", "text", "table"
    bbox: BoundingBox
    confidence: float = 1.0
    content: Optional[str] = None

class DocumentContent(BaseModel):
    """文档内容"""
    text_blocks: List[TextBlock] = Field(default_factory=list)
    image_regions: List[ImageRegion] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
```

### API 响应

```python
# src/common/models/api.py
from pydantic import BaseModel, Field
from typing import TypeVar, Generic, Optional
from enum import Enum

class ResponseStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"

T = TypeVar("T")

class ApiResponse(BaseModel, Generic[T]):
    """API 响应"""
    status: ResponseStatus
    data: Optional[T] = None
    message: str = ""
    code: int = 200

class PaginatedResponse(BaseModel, Generic[T]):
    """分页响应"""
    items: List[T]
    total: int
    page: int
    page_size: int
    has_next: bool
```

## 类型别名

```python
# src/common/models/types.py
from typing import TypeAlias

# JSON 类型
JSON: TypeAlias = dict | list | str | int | float | bool | None

# 图像类型
ImageData: TypeAlias = bytes | str  # 文件路径或二进制

# 检查器类型
CheckFunction: TypeAlias = callable[..., CheckResult]
```

## 枚举定义

```python
# src/common/models/enums.py
from enum import Enum

class DocumentType(str, Enum):
    """文档类型"""
    PATENT_CERTIFICATE = "patent_certificate"      # 专利证书
    PATENT_APPLICATION = "patent_application"     # 专利申请
    ACCEPTANCE_REPORT = "acceptance_report"       # 验收报告
    LICENSE = "license"                            # 行政许可
    RETRIEVAL_REPORT = "retrieval_report"          # 检索报告
    AWARD_CERTIFICATE = "award_certificate"        # 奖励证书
    CONTRACT = "contract"                          # 合同
    OTHER = "other"

class CheckItem(str, Enum):
    """检查项"""
    SIGNATURE = "signature"           # 签字检查
    STAMP = "stamp"                   # 盖章检查
    PREREQUISITE = "prerequisite"     # 前置条件
    CONSISTENCY = "consistency"      # 一致性检查
    COMPLETENESS = "completeness"    # 完整性检查
    FORMAT = "format"                 # 格式检查
```

## 扩展模型

在对应模块目录下创建新文件：

```
src/common/models/
├── __init__.py
├── file.py
├── review.py
├── document.py
├── api.py
├── enums.py
└── types.py
```

在 `__init__.py` 中导出：

```python
# src/common/models/__init__.py
from src.common.models.file import FileMeta, FileType, UploadFile
from src.common.models.review import CheckResult, ReviewResult, CheckStatus
from src.common.models.document import DocumentContent, BoundingBox, TextBlock
# ...
```
