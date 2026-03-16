# 📄 文件处理

## 概述

提供统一的文件处理能力，包括 PDF 解析、图片处理、格式转换等。

## 模块结构

```
src/common/file_handler/
├── __init__.py
├── base.py           # 抽象基类
├── pdf_parser.py     # PDF 解析
├── image_processor.py # 图片处理
├── ocr.py           # OCR 识别
└── factory.py       # 工厂函数
```

## 核心接口

```python
# src/common/file_handler/base.py
from abc import ABC, abstractmethod
from typing import List, BinaryIO
from pydantic import BaseModel
from src.common.models.document import DocumentContent

class ParseResult(BaseModel):
    """解析结果"""
    content: DocumentContent
    pages: int
    metadata: dict = {}

class BaseFileParser(ABC):
    """文件解析器基类"""
    
    @abstractmethod
    async def parse(self, file_data: bytes, **kwargs) -> ParseResult:
        """解析文件"""
        pass
    
    @abstractmethod
    async def extract_images(self, file_data: bytes) -> List[bytes]:
        """提取图片"""
        pass
```

## PDF 解析

```python
# src/common/file_handler/pdf_parser.py
from typing import List
import PyMuPDF
from src.common.file_handler.base import BaseFileParser, ParseResult
from src.common.models.document import DocumentContent, TextBlock, BoundingBox

class PDFParser(BaseFileParser):
    """PDF 解析器"""
    
    async def parse(self, file_data: bytes, **kwargs) -> ParseResult:
        """解析 PDF"""
        # 使用 PyMuPDF 解析
        doc = PyMuPDF.open(stream=file_data, filetype="pdf")
        
        text_blocks = []
        for page_num, page in enumerate(doc):
            # 提取文本
            text = page.get_text()
            
            # 提取文本块和位置
            blocks = page.get_text("blocks")
            for block in blocks:
                x0, y0, x1, y1, text_content, *_ = block
                text_blocks.append(TextBlock(
                    text=text_content,
                    bbox=BoundingBox(
                        x=x0, y=y0,
                        width=x1-x0, height=y1-y0
                    ),
                    page=page_num
                ))
        
        metadata = {
            "title": doc.metadata.get("title", ""),
            "author": doc.metadata.get("author", ""),
        }
        
        return ParseResult(
            content=DocumentContent(text_blocks=text_blocks),
            pages=len(doc),
            metadata=metadata
        )
    
    async def extract_images(self, file_data: bytes) -> List[bytes]:
        """提取图片"""
        doc = PyMuPDF.open(stream=file_data, filetype="pdf")
        images = []
        
        for page in doc:
            for img in page.get_images():
                xref = img[0]
                pix = PyMuPDFPixmap(doc, xref)
                images.append(pix.tobytes())
        
        return images
```

## 图片处理

```python
# src/common/file_handler/image_processor.py
from PIL import Image
import io
from typing import Tuple

class ImageProcessor:
    """图片处理器"""
    
    @staticmethod
    def resize(
        image_data: bytes,
        max_size: Tuple[int, int] = (2048, 2048)
    ) -> bytes:
        """调整图片大小"""
        img = Image.open(io.BytesIO(image_data))
        
        # 保持比例缩放
        img.thumbnail(max_size, Image.Resampling.LANCZOS)
        
        output = io.BytesIO()
        img.save(output, format=img.format or "PNG")
        return output.getvalue()
    
    @staticmethod
    def to_rgb(image_data: bytes) -> bytes:
        """转换为 RGB 模式"""
        img = Image.open(io.BytesIO(image_data))
        
        if img.mode != "RGB":
            img = img.convert("RGB")
        
        output = io.BytesIO()
        img.save(output, format="PNG")
        return output.getvalue()
    
    @staticmethod
    def get_dimensions(image_data: bytes) -> Tuple[int, int]:
        """获取图片尺寸"""
        img = Image.open(io.BytesIO(image_data))
        return img.size
```

## OCR 识别

```python
# src/common/file_handler/ocr.py
import paddleocr
from typing import List
from src.common.models.document import TextBlock, BoundingBox

class OCRProcessor:
    """OCR 处理器"""
    
    def __init__(self):
        self.reader = paddleocr.PaddleOCR(
            use_angle_cls=True,
            lang='ch'
        )
    
    async def recognize(
        self,
        image_data: bytes,
        page: int = 0
    ) -> List[TextBlock]:
        """识别文字"""
        import cv2
        import numpy as np
        
        # 转为 numpy 数组
        nparr = np.frombuffer(image_data, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        
        # OCR 识别
        result = self.reader.ocr(img, cls=True)
        
        text_blocks = []
        if result and result[0]:
            for line in result[0]:
                box = line[0]
                text = line[1][0]
                confidence = line[1][1]
                
                # 计算边界框
                x_coords = [p[0] for p in box]
                y_coords = [p[1] for p in box]
                x_min, x_max = min(x_coords), max(x_coords)
                y_min, y_max = min(y_coords), max(y_coords)
                
                text_blocks.append(TextBlock(
                    text=text,
                    bbox=BoundingBox(
                        x=x_min, y=y_min,
                        width=x_max - x_min,
                        height=y_max - y_min
                    ),
                    page=page,
                    confidence=confidence
                ))
        
        return text_blocks
```

## 工厂函数

```python
# src/common/file_handler/factory.py
from src.common.file_handler.base import BaseFileParser
from src.common.file_handler.pdf_parser import PDFParser

def get_parser(file_type: str) -> BaseFileParser:
    """获取解析器"""
    
    parsers = {
        "pdf": PDFParser,
        # 可扩展其他类型
    }
    
    parser_class = parsers.get(file_type.lower())
    if not parser_class:
        raise ValueError(f"Unsupported file type: {file_type}")
    
    return parser_class()
```

## 使用方式

```python
from src.common.file_handler import get_parser

# 根据文件类型获取解析器
parser = get_parser("pdf")

# 解析文件
result = await parser.parse(file_data)

# 提取图片
images = await parser.extract_images(file_data)

# OCR 识别
from src.common.file_handler.ocr import OCRProcessor
ocr = OCRProcessor()
text_blocks = await ocr.recognize(image_data)
```
