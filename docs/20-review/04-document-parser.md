# 📄 文档解析方案

## 概述

文档解析是形式审查的基础，负责从上传的文件中提取文字、图像、版式等信息。

## 技术选型

| 组件 | 方案 | 用途 |
|------|------|------|
| **PDF 解析** | PyMuPDF | 提取文本、图像、坐标 |
| **OCR** | PaddleOCR | 文字识别 |
| **目标检测** | YOLO | 签名/印章检测 |
| **多模态 LLM** | GPT-4V/Claude | 复杂版式理解 |

## 处理流程

```
┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│  文件输入   │ -> │  格式转换   │ -> │  版式解析   │
└─────────────┘    └─────────────┘    └─────────────┘
                                            │
                                            ▼
                                   ┌─────────────────┐
                                   │   内容提取      │
                                   │  - 文本块       │
                                   │  - 图像区域     │
                                   │  - 表格         │
                                   └────────┬────────┘
                                            │
                                            ▼
                                   ┌─────────────────┐
                                   │   目标检测      │
                                   │  - 签名位置     │
                                   │  - 印章位置     │
                                   └─────────────────┘
```

## 核心实现

### 文档解析器

```python
# src/services/review/parser.py
from typing import List, Optional
from pydantic import BaseModel

from src.common.file_handler import get_parser
from src.common.models import DocumentContent, TextBlock, ImageRegion

class ParseResult(BaseModel):
    """解析结果"""
    content: DocumentContent
    pages: int
    metadata: dict = {}

class DocumentParser:
    """文档解析器"""
    
    async def parse(
        self,
        file_data: bytes,
        file_type: str,
        **kwargs
    ) -> ParseResult:
        """解析文档
        
        Args:
            file_data: 文件数据
            file_type: 文件类型 (pdf, image)
            
        Returns:
            ParseResult: 解析结果
        """
        if file_type == "pdf":
            return await self._parse_pdf(file_data, **kwargs)
        elif file_type in ["jpg", "jpeg", "png"]:
            return await self._parse_image(file_data, **kwargs)
        else:
            raise ValueError(f"Unsupported file type: {file_type}")
    
    async def _parse_pdf(
        self,
        file_data: bytes,
        **kwargs
    ) -> ParseResult:
        """解析 PDF"""
        from src.common.file_handler.pdf_parser import PDFParser
        from src.common.file_handler.ocr import OCRProcessor
        
        # PDF 解析
        parser = PDFParser()
        pdf_result = await parser.parse(file_data)
        
        # 对每一页进行 OCR（可选，增强文本提取）
        ocr = OCRProcessor()
        text_blocks = list(pdf_result.content.text_blocks)
        
        # 提取图片
        images = await parser.extract_images(file_data)
        
        return ParseResult(
            content=DocumentContent(
                text_blocks=text_blocks,
                image_regions=[],
                metadata={"images": len(images)}
            ),
            pages=pdf_result.pages,
            metadata=pdf_result.metadata
        )
    
    async def _parse_image(
        self,
        file_data: bytes,
        **kwargs
    ) -> ParseResult:
        """解析图片"""
        from src.common.file_handler.ocr import OCRProcessor
        
        # OCR 识别
        ocr = OCRProcessor()
        text_blocks = await ocr.recognize(file_data)
        
        return ParseResult(
            content=DocumentContent(
                text_blocks=text_blocks,
                image_regions=[]
            ),
            pages=1,
            metadata={}
        )
```

### 图像预处理

```python
# src/services/review/preprocessor.py
from PIL import Image
import io
import cv2
import numpy as np

class ImagePreprocessor:
    """图像预处理器"""
    
    @staticmethod
    def enhance_for_ocr(image_data: bytes) -> bytes:
        """增强图像以提高 OCR 准确率"""
        # 读取图像
        nparr = np.frombuffer(image_data, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        
        # 灰度化
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        
        # 去噪声
        denoised = cv2.fastNlMeansDenoising(gray)
        
        # 自适应阈值
        thresh = cv2.adaptiveThreshold(
            denoised, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY, 11, 2
        )
        
        # 转回 BGR
        result = cv2.cvtColor(thresh, cv2.COLOR_GRAY2BGR)
        
        _, buffer = cv2.imencode('.png', result)
        return buffer.tobytes()
    
    @staticmethod
    def detect_document_boundary(image_data: bytes) -> dict:
        """检测文档边界"""
        nparr = np.frombuffer(image_data, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        
        # 边缘检测
        edges = cv2.Canny(gray, 50, 150)
        
        # 找轮廓
        contours, _ = cv2.findContours(
            edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        
        if contours:
            # 取最大轮廓
            largest = max(contours, key=cv2.contourArea)
            x, y, w, h = cv2.boundingRect(largest)
            return {"x": x, "y": y, "width": w, "height": h}
        
        return {"x": 0, "y": 0, "width": img.shape[1], "height": img.shape[0]}
```

### 签名/印章区域提取

```python
# src/services/review/region_extractor.py
from typing import List
from src.common.models import BoundingBox, ImageRegion

class RegionExtractor:
    """区域提取器"""
    
    async def extract_signature_regions(
        self,
        image_data: bytes,
        detection_results: List
    ) -> List[ImageRegion]:
        """提取签名区域"""
        regions = []
        
        for detection in detection_results:
            if detection.class_name in ["signature", "handwriting"]:
                region = ImageRegion(
                    type="signature",
                    bbox=detection.bbox,
                    confidence=detection.confidence
                )
                regions.append(region)
        
        return regions
    
    async def extract_stamp_regions(
        self,
        image_data: bytes,
        detection_results: List
    ) -> List[ImageRegion]:
        """提取印章区域"""
        regions = []
        
        for detection in detection_results:
            if detection.class_name in ["stamp", "seal"]:
                region = ImageRegion(
                    type="stamp",
                    bbox=detection.bbox,
                    confidence=detection.confidence
                )
                regions.append(region)
        
        return regions
```

## 复杂版式处理策略

### 1. 多栏文档

```python
async def handle_multi_column(
    self,
    text_blocks: List[TextBlock]
) -> List[TextBlock]:
    """处理多栏文档"""
    # 按 Y 坐标分组
    lines = {}
    for block in text_blocks:
        y_key = int(block.bbox.y / 50)  # 按行分组
        if y_key not in lines:
            lines[y_key] = []
        lines[y_key].append(block)
    
    # 重新排序
    sorted_blocks = []
    for y_key in sorted(lines.keys()):
        blocks = lines[y_key]
        # 按 X 坐标排序
        blocks.sort(key=lambda b: b.bbox.x)
        sorted_blocks.extend(blocks)
    
    return sorted_blocks
```

### 2. 水印处理

```python
async def remove_watermark(
    self,
    image_data: bytes
) -> bytes:
    """去除水印（简化版）"""
    # 实际生产中可使用图像分割模型
    # 这里简单返回原图
    return image_data
```

### 3. 表格处理

```python
async def extract_tables(
    self,
    image_data: bytes
) -> List[dict]:
    """提取表格"""
    # 可使用 TableTransformers 等模型
    # 返回表格结构化数据
    return []
```

## 性能优化

1. **并行处理**: 多页 PDF 并行解析
2. **缓存**: 缓存 OCR 结果
3. **采样**: 大图缩放后检测，小图识别
4. **流式**: 大文件流式处理

## 使用方式

```python
from src.services.review.parser import DocumentParser

parser = DocumentParser()

# 解析 PDF
result = await parser.parse(file_data, "pdf")

# 解析图片
result = await parser.parse(image_data, "image")

# 获取内容
text_blocks = result.content.text_blocks
```
