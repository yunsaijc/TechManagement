# 📄 文档解析方案

## 概述

文档解析模块负责将申报书/任务书转换为可计算的结构化数据，为后续实体抽取与逻辑比对提供统一输入。

## 设计思路

1. **结构优先**：先解析章节、段落、表格，再做语义抽取。
2. **坐标可追踪**：保留页码、段落号、表格行列索引，支持冲突回溯。
3. **格式统一化**：将 DOCX/PDF 归一为统一中间表示（IR）。

---

## 解析流程

```
输入文件 (DOCX/PDF)
   │
   ├─> 1. 格式识别与预处理
   ├─> 2. 章节切分（标题层级）
   ├─> 3. 表格结构化（行列与合并单元格）
   ├─> 4. 文本清洗（空格、单位、标点）
   └─> 5. 统一输出 IR
```

---

## 中间表示（IR）

```python
from dataclasses import dataclass
from typing import List, Dict, Any


@dataclass
class ParagraphNode:
    section: str
    page: int
    index: int
    text: str


@dataclass
class TableCell:
    row: int
    col: int
    text: str


@dataclass
class TableNode:
    section: str
    page: int
    table_id: str
    cells: List[TableCell]


@dataclass
class ParsedDocument:
    file_type: str
    paragraphs: List[ParagraphNode]
    tables: List[TableNode]
    metadata: Dict[str, Any]
```

---

## 核心代码结构

```python
class DocumentParser:
    """统一文档解析器"""

    async def parse(self, file_data: bytes, file_type: str) -> ParsedDocument:
        if file_type == "docx":
            return await self._parse_docx(file_data)
        if file_type == "pdf":
            return await self._parse_pdf(file_data)
        raise ValueError(f"unsupported file type: {file_type}")

    async def _parse_docx(self, file_data: bytes) -> ParsedDocument:
        # 解析段落、标题、表格
        raise NotImplementedError

    async def _parse_pdf(self, file_data: bytes) -> ParsedDocument:
        # 解析页文本、块坐标、表格
        raise NotImplementedError
```

---

## 使用示例

```python
parser = DocumentParser()
parsed = await parser.parse(file_data=doc_bytes, file_type="docx")

print(len(parsed.paragraphs))
print(len(parsed.tables))
```

---

## 解析质量要求

| 指标 | 目标 |
|------|------|
| 章节识别准确率 | ≥ 95% |
| 表格结构识别准确率 | ≥ 90% |
| 页码/段落定位可追溯率 | 100% |
