# 🤖 Agent 设计

## 概述

查重服务采用分层架构，与形式审查服务保持一致。核心思路是**句子级比对 + 位置追溯**，而非语义 embedding。

## 架构分层

```
┌─────────────────────────────────────────────────────────────────────┐
│  Layer 6: Service/Agent 层 (services/plagiarism/)                   │
│  ┌─────────────────┐  ┌─────────────────┐                          │
│  │ PlagiarismAgent │  │   API 入口      │  ← 流程编排               │
│  └────────┬────────┘  └────────┬────────┘                          │
└───────────┼───────────────────┼────────────────────────────────────┘
            │                   │
┌───────────▼───────────────────▼────────────────────────────────────┐
│  Layer 5: 比对引擎层 (services/plagiarism/comparator.py)            │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐   │
│  │ SentenceSplitter │  │  DuplicateFinder│  │ ResultAggregator│   │
│  │  (句子切分)     │  │  (重复查找)     │  │  (结果聚合)     │   │
│  └────────┬────────┘  └────────┬────────┘  └────────┬────────┘   │
└───────────┼───────────────────┼────────────────────┼──────────────┘
            │                   │                    │
┌───────────▼───────────────────▼────────────────────▼──────────────┐
│  Layer 4: 提取器层 (common/file_handler/)                          │
│                                                                     │
│  ┌──────────────────┐  ┌──────────────────┐                      │
│  │   PDFParser       │  │   DOCXParser     │                      │
│  │  (PDF 文本提取)  │  │  (DOCX 文本提取) │                      │
│  └──────────────────┘  └──────────────────┘                      │
└─────────────────────────────────────────────────────────────────────┘
```

## 核心流程

```
用户上传文件（多个）
        │
        ▼
┌─────────────────────┐
│  1. 文本提取        │  ← PDF/DOCX 解析
│  (file_handler)     │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│  2. Section 提取   │  ← 标题匹配，提取目标区域
│  (SectionExtractor) │    使用配置文件定义的正则模式
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│  3. 句子切分        │  ← 按换行切分成句子
│  (SentenceSplitter) │    记录每个句子的: 文本、来源文档、位置
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│  4. 查找重复        │  ← 构建句子库，查找跨文档重复
│  (DuplicateFinder)  │    统计重复字数、重复率
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│  5. 结果聚合        │  ← 按相似度分类，输出位置信息
│  (ResultAggregator) │
└──────────┬──────────┘
           │
           ▼
      查重结果输出
```

## Section 提取

使用正则表达式从文档中提取指定的 section 区域。

### SectionExtractor

```python
# services/plagiarism/section_extractor.py

class SectionExtractor:
    """Section 区域提取器"""
    
    def __init__(self, section_config: Dict):
        self.sections = section_config.get("sections", [])
    
    def extract(self, text: str) -> str:
        """从全文中提取目标 section 区域
        
        Args:
            text: 完整文档文本
            
        Returns:
            提取后的文本
        """
        results = []
        
        for section in self.sections:
            start_pattern = section.get("start_pattern")
            end_pattern = section.get("end_pattern")
            
            # 查找起始位置
            start_match = re.search(start_pattern, text)
            if not start_match:
                continue
            
            start_pos = start_match.start()
            
            # 查找结束位置
            if end_pattern:
                end_match = re.search(end_pattern, text[start_pos + 1:])
                if end_match:
                    end_pos = start_pos + 1 + end_match.start()
                else:
                    continue
            else:
                # 无结束模式，提取到文档结尾
                end_pos = len(text)
            
            # 提取区域内容
            section_text = text[start_pos:end_pos]
            results.append(section_text)
        
        return "\n".join(results)
```

### 配置加载

```python
# services/plagiarism/agent.py

from src.services.plagiarism.config import get_section_config

class PlagiarismAgent:
    def __init__(self, doc_type: str = "default"):
        section_config = get_section_config(doc_type)
        self.extractor = SectionExtractor(section_config)
```

### 支持自定义配置

```python
# 通过 API 传入自定义配置
section_config = {
    "sections": [
        {
            "name": "自定义区域",
            "start_pattern": r"开始标题",
            "end_pattern": r"结束标题",
        }
    ]
}
extractor = SectionExtractor(section_config)
```

## 核心组件

### PlagiarismAgent (Layer 6)

```python
# services/plagiarism/agent.py
class PlagiarismAgent:
    """查重 Agent"""
    
    def __init__(self):
        self.parser_factory = get_parser()  # 复用 file_handler
        self.comparator = TextComparator()
    
    async def check(
        self,
        files: List[tuple[str, bytes]],  # [(doc_id, file_data)]
    ) -> PlagiarismResult:
        """执行查重"""
        # 1. 文本提取
        texts = {}
        for doc_id, file_data in files:
            parser = get_parser(detect_type(file_data))
            result = await parser.parse(file_data)
            texts[doc_id] = result.content.to_text()
        
        # 2. 句子级比对
        result = self.comparator.compare(texts)
        
        return result
```

### TextComparator (Layer 5) - 核心逻辑

```python
# services/plagiarism/comparator.py

@dataclass
class DuplicateSegment:
    """重复片段"""
    text: str                    # 重复的句子/段落
    line_number: int            # 在当前文档中的位置（行号）
    source_docs: List[str]       # 来源文档列表
    source_lines: List[int]      # 来源文档中的位置

@dataclass
class DocumentSimilarity:
    """文档相似度"""
    doc_a: str
    doc_b: str
    similarity: float             # 0-1，重复字数/总字数
    duplicate_segments: List[DuplicateSegment]
    total_chars: int             # 文档总字符数
    duplicate_chars: int         # 重复字符数

class TextComparator:
    """文本比对器"""
    
    def __init__(
        self,
        threshold_high: float = 0.8,
        threshold_medium: float = 0.5,
    ):
        self.threshold_high = threshold_high
        self.threshold_medium = threshold_medium
    
    def compare(self, texts: Dict[str, str]) -> PlagiarismResult:
        """执行句子级比对
        
        步骤:
        1. 切分句子: 每个文档按标点/换行切分
        2. 构建句子库: {句子: {doc_id: [line_numbers]}}
        3. 查找重复: 跨文档的相同句子
        4. 计算相似度: 重复字数 / 总字数
        """
        # Step 1: 句子切分
        sentence_map = {}  # {doc_id: [(line_no, text), ...]}
        for doc_id, text in texts.items():
            sentences = self._split_sentences(text)
            sentence_map[doc_id] = sentences
        
        # Step 2: 构建句子库
        # {text: {doc_id: [line_numbers]}}
        text_sources = defaultdict(lambda: defaultdict(list))
        for doc_id, sentences in sentence_map.items():
            for line_no, text in sentences:
                text_sources[text][doc_id].append(line_no)
        
        # Step 3: 查找重复
        results = []
        doc_ids = list(texts.keys())
        
        for i, doc_a in enumerate(doc_ids):
            for doc_b in doc_ids[i+1:]:
                dup_segments = self._find_duplicates(
                    sentence_map[doc_a],
                    sentence_map[doc_b],
                    text_sources
                )
                
                # 计算相似度
                total_chars = len(texts[doc_a])
                dup_chars = sum(len(seg.text) for seg in dup_segments)
                similarity = dup_chars / total_chars if total_chars > 0 else 0
                
                results.append(DocumentSimilarity(
                    doc_a=doc_a,
                    doc_b=doc_b,
                    similarity=similarity,
                    duplicate_segments=dup_segments,
                    total_chars=total_chars,
                    duplicate_chars=dup_chars,
                ))
        
        # Step 4: 分类聚合
        return self._aggregate_results(results)
    
    def _split_sentences(self, text: str) -> List[tuple[int, str]]:
        """按换行符切分成句子，返回 (行号, 文本)"""
        lines = text.split('\n')
        return [(i+1, line.strip()) for i, line in enumerate(lines) if line.strip()]
    
    def _find_duplicates(
        self,
        sentences_a: List[tuple[int, str]],
        sentences_b: List[tuple[int, str]],
        text_sources: Dict,
    ) -> List[DuplicateSegment]:
        """查找两个文档间的重复句子"""
        duplicates = []
        texts_b = {text: line_no for line_no, text in sentences_b}
        
        for line_no_a, text_a in sentences_a:
            if text_a in texts_b:
                line_no_b = texts_b[text_a]
                duplicates.append(DuplicateSegment(
                    text=text_a,
                    line_number=line_no_a,
                    source_docs=[],  # 填充来源文档
                    source_lines=[line_no_b],
                ))
        
        return duplicates
    
    def _aggregate_results(self, results: List[DocumentSimilarity]) -> PlagiarismResult:
        """聚合结果"""
        # 按相似度分类
        high = [r for r in results if r.similarity >= self.threshold_high]
        medium = [r for r in results if self.threshold_medium <= r.similarity < self.threshold_high]
        low = [r for r in results if r.similarity < self.threshold_medium]
        
        return PlagiarismResult(...)
```

## 数据结构

### DuplicateSegment

```python
@dataclass
class DuplicateSegment:
    text: str                    # 重复的句子
    line_number: int            # 在当前文档中的行号
    source_docs: List[str]      # 来源文档列表
    source_lines: List[int]     # 来源文档中的行号
```

### 返回结果示例

```json
{
  "doc_a": "相似组2-A.docx",
  "doc_b": "相似组2-B.docx",
  "similarity": 0.85,
  "duplicate_segments": [
    {
      "text": "河北省中央引导地方科技发展资金项目申报书",
      "line_number": 1,
      "source_docs": ["相似组2-B.docx"],
      "source_lines": [1]
    },
    {
      "text": "专项名称：中央引导地方科技发展资金项目",
      "line_number": 5,
      "source_docs": ["相似组2-B.docx"],
      "source_lines": [5]
    }
  ],
  "total_chars": 25000,
  "duplicate_chars": 21250
}
```

## 设计原则

1. **句子级比对**: 按行/句子切分，精确匹配相同文本
2. **位置追溯**: 记录重复内容在源文档和目标文档中的位置
3. **全文查重**: 不截断文本，处理任意长度的文档
4. **可扩展**: 易于添加更复杂的比对策略（如 n-gram、编辑距离）

## 与语义分组的区别

| 特性 | 查重（本文） | 语义分组 |
|------|-------------|---------|
| 目标 | 检测文字重复 | 判断领域相关性 |
| 方法 | 句子级精确匹配 | Embedding 语义向量 |
| 输出 | 重复位置 + 来源 | 相似文档列表 |
| 场景 | 抄袭检测、重复申报 | 学科分组、推荐 |
