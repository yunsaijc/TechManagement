# 🤖 Agent 设计

## 概述

查重服务采用分层架构，与形式审查服务保持一致。核心思路是**N-gram 滑动窗口 + 指纹索引 + 多层模板过滤**，对齐业界最佳实践（如知网、Turnitin）。

## 核心设计原则

1. **语义分句**：按标点符号（。！？；）分句，而非简单按行切分
2. **多层过滤**：白名单 + 标题检测 + 短句过滤，去除模板内容
3. **N-gram 比对**：滑动窗口生成 N-gram，支持连续匹配检测
4. **指纹索引**：使用 SimHash 指纹加速大规模比对
5. **位置追溯**：精确定位到行号、段落、Section

## 架构分层

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  Layer 6: Service/Agent 层 (services/plagiarism/)                           │
│  ┌─────────────────┐  ┌─────────────────┐                                  │
│  │ PlagiarismAgent │  │     API 入口     │  ← 流程编排                      │
│  └────────┬────────┘  └────────┬────────┘                                  │
└───────────┼───────────────────┼────────────────────────────────────────────┘
            │                   │
┌───────────▼───────────────────▼────────────────────────────────────────────┐
│  Layer 5: 比对引擎层                                                          │
│                                                                              │
│  ┌───────────────┐  ┌───────────────┐  ┌───────────────┐  ┌───────────────┐ │
│  │SentenceTokenizer│ │TemplateFilter │  │  NGramSplitter│  │ResultAggregator│ │
│  │  (语义分句)   │  │  (模板过滤)   │  │  (N-gram切分) │  │  (结果聚合)   │ │
│  └───────┬───────┘  └───────┬───────┘  └───────┬───────┘  └───────┬───────┘ │
│          │                  │                  │                  │         │
│  ┌───────▼──────────────────▼──────────────────▼──────────────────▼───────┐
│  │                         ComparisonEngine                                │ │
│  │                    (指纹索引 + 连续匹配检测)                              │ │
│  └───────────────────────────────────────────────────────────────────────────┘
└──────────────────────────────────────────────────────────────────────────────┘
            │
┌───────────▼────────────────────────────────────────────────────────────────┐
│  Layer 4: 提取器层 (common/file_handler/)                                    │
│                                                                              │
│  ┌──────────────────┐  ┌──────────────────┐                               │
│  │   PDFParser      │  │   DOCXParser     │                               │
│  │  (PDF 文本提取)  │  │  (DOCX 文本提取) │                               │
│  └──────────────────┘  └──────────────────┘                               │
└─────────────────────────────────────────────────────────────────────────────┘
```

## 核心流程

```
用户上传文件（多个）
        │
        ▼
┌─────────────────────┐
│  1. 文本提取        │  ← PDF/DOCX 解析
│  (file_handler)     │    提取段落、表格、标题
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│  2. Section 提取    │  ← 仅主文档提取指定区域
│ (SectionExtractor)  │    对比文档使用全文
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│  3. 语义分句        │  ← 按标点分句（。！？；）
│ (SentenceTokenizer) │    保留位置映射
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│  4. N-gram 切分     │  ← 生成 5-gram
│ (NGramSplitter)     │    不过滤，保留原始位置
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│  5. 指纹索引构建    │  ← SimHash 指纹
│(ComparisonEngine)   │    倒排索引
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│  6. 连续匹配检测    │  ← 连续 ≥5 个相同
│(ComparisonEngine)   │    滑动窗口匹配
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│  7. 后置模板过滤    │  ← 对匹配结果过滤
│ (TemplateFilter)    │    区分模板重复 vs 有效重复
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│  8. 结果聚合        │  ← 片段合并
│(ResultAggregator)   │    位置追溯
└──────────┬──────────┘    分类输出（高/中/低）
           │
           ▼
      查重结果输出
```

## 查重策略：后置过滤

业界最佳实践（知网、Turnitin）采用**先比对、后过滤**的策略：

1. **全文N-gram指纹比对**（位置精确对齐）
2. **找出所有重复片段**
3. **后置过滤**：去除白名单短语、标题、表格等
4. **输出**：总重复 + 有效重复（过滤后）

### 为什么后置过滤？

- **位置对齐**：主文档和对比文档都在原始位置上进行比对
- **过滤准确**：基于匹配到的具体内容判断是否是模板
- **可区分性**：可区分"模板重复"和"有效重复"

### 输出结构

```json
{
  "total_similarity": 0.52,        // 总重复率
  "effective_similarity": 0.35,     // 有效重复率（过滤后）
  "template_segments": [            // 模板重复片段（不计入有效重复）
    {
      "text": "为了认真贯彻落实...",
      "reason": "whitelist_match"
    }
  ],
  "effective_segments": [...]        // 有效重复片段
}
```

## 核心组件

### 1. SentenceTokenizer (语义分词器)

```python
# services/plagiarism/tokenizer.py

@dataclass
class Sentence:
    """句子"""
    text: str                    # 句子文本
    start_pos: int               # 在原文中的起始位置
    end_pos: int                 # 在原文中的结束位置
    line_number: int             # 起始行号
    is_from_table: bool = False  # 是否来自表格


class SentenceTokenizer:
    """中文句子分词器 - 按标点分句"""
    
    # 句末标点
    SENTENCE_ENDINGS = ['。', '！', '？', '；']
    
    # 句内分隔符（不分句，但标记位置）
    INTERNAL_SEPARATORS = ['，', '、', ':', '：']
    
    def tokenize(self, text: str) -> List[Sentence]:
        """
        将文本切分为句子列表
        
        规则:
        1. 按句末标点（。！？；）切分
        2. 表格内容按单元格切分
        3. 保留原始位置（start_pos, end_pos）
        """
        
    def _split_by_punctuation(self, text: str) -> List[Sentence]:
        """按标点分句"""
        sentences = []
        current_pos = 0
        current_text = []
        line_offset = 0
        
        for i, char in enumerate(text):
            if char in self.SENTENCE_ENDINGS:
                # 遇到句末标点，结束当前句子
                sentence_text = ''.join(current_text).strip()
                if sentence_text:
                    sentences.append(Sentence(
                        text=sentence_text,
                        start_pos=current_pos,
                        end_pos=i + 1,
                        line_number=line_offset + 1,
                    ))
                current_pos = i + 1
                current_text = []
            else:
                current_text.append(char)
                if char == '\n':
                    line_offset += 1
        
        # 处理最后一个句子
        if current_text:
            sentence_text = ''.join(current_text).strip()
            if sentence_text:
                sentences.append(Sentence(
                    text=sentence_text,
                    start_pos=current_pos,
                    end_pos=len(text),
                    line_number=line_offset + 1,
                ))
        
        return sentences
```

### 2. TemplateFilter (模板内容过滤器)

```python
# services/plagiarism/template_filter.py

class TemplateFilter:
    """模板内容过滤器"""
    
    # 白名单：常见模板句式（不计入重复）
    TEMPLATE_PHRASES = [
        r"为了认真贯彻落实.*?要求",
        r"根据.*?规定",
        r"特制定本.*?",
        r"本办法适用于",
        r"现将.*?情况汇报如下",
        r"\d+[万千百亿].*?元",  # 金额模板
    ]
    
    # 标题模式
    HEADING_PATTERNS = [
        r"^第[一二三四五六七八九十百]+部分",  # 第一部分
        r"^[一二三四五六七八九十]、",          # 一、二、三
        r"^\d+\.\d+",                         # 1.2.3
        r"^[A-Z]\.",                         # A. B. C.
        r"^\([a-zA-Z0-9一二三四五六七八九十]+\)",  # (1) (一)
    ]
    
    # 表格相关
    TABLE_PATTERNS = [
        r"^\[表格行\d+\]",      # [表格行1]
        r"^\s*[\u4e00-\u9fa5]+\s*\|\s*[\u4e00-\u9fa5]+",  # "项目 | 金额"
    ]
    
    # 最小句子长度
    MIN_SENTENCE_LENGTH = 15
    
    def filter(self, sentences: List[Sentence]) -> List[Sentence]:
        """
        过滤模板内容
        
        策略:
        1. 白名单匹配 → 跳过
        2. 标题检测 → 跳过
        3. 短句过滤（< 15字）→ 跳过
        4. 纯数字/符号 → 跳过
        """
        filtered = []
        
        for sent in sentences:
            if self._is_template(sent.text):
                continue
            if self._is_heading(sent.text):
                continue
            if self._is_too_short(sent.text):
                continue
            if self._is_number_only(sent.text):
                continue
            filtered.append(sent)
        
        return filtered
    
    def _is_template(self, text: str) -> bool:
        """检查是否匹配白名单模板"""
        for pattern in self.TEMPLATE_PHRASES:
            if re.match(pattern, text):
                return True
        return False
    
    def _is_heading(self, text: str) -> bool:
        """检查是否标题"""
        for pattern in self.HEADING_PATTERNS:
            if re.match(pattern, text):
                return True
        return False
    
    def _is_too_short(self, text: str) -> bool:
        """检查是否过短（独立句子）"""
        return len(text) < self.MIN_SENTENCE_LENGTH
    
    def _is_number_only(self, text: str) -> bool:
        """检查是否纯数字/符号"""
        return bool(re.match(r'^[\d\s,，。.．:：%％]+$', text))

    def is_template(self, text: str) -> bool:
        """
        检查文本片段是否是模板内容（用于后置过滤）

        Args:
            text: 待检查的文本片段

        Returns:
            True 如果是模板内容
        """
        if self._is_heading(text):
            return True
        if self._is_too_short(text):
            return True
        if self._is_table_related(text):
            return True
        if self._is_template(text):
            return True
        return False

    def _is_table_related(self, text: str) -> bool:
        """检查是否表格相关内容"""
        for pattern in self.TABLE_PATTERNS:
            if re.search(pattern, text):
                return True
        return False
```

### 3. NGramSplitter (N-gram 切分器)

```python
# services/plagiarism/ngram.py

@dataclass
class NGram:
    """N-gram 片段"""
    text: str              # N-gram 文本
    position: int          # 在句子中的位置
    sentence_idx: int      # 所属句子索引
    fingerprint: int       # SimHash 指纹


DEFAULT_STOP_WORDS = {
    '的', '了', '和', '与', '对', '在', '是', '为', '以', '及',
    '等', '于', '用', '可', '能', '会', '有', '也', '但', '或',
    '把', '被', '让', '使', '将', '要', '这', '那', '其', '所',
}


class NGramSplitter:
    """N-gram 滑动窗口切分 + 指纹生成"""
    
    def __init__(self, n: int = 5, stop_words: Set[str] = None):
        self.n = n
        self.stop_words = stop_words or DEFAULT_STOP_WORDS
    
    def split(self, sentences: List[Sentence]) -> List[NGram]:
        """
        将句子列表切分为 N-gram
        
        示例（5-gram）:
        输入: "项目组织及参与单位拥有成熟的科学家团队"
        输出: [
            NGram(text="项目组织及参与单位拥有成熟", position=0, ...),
            NGram(text="织及参与单位拥有成熟的科学", position=1, ...),
            ...
        ]
        """
        ngrams = []
        
        for sent_idx, sent in enumerate(sentences):
            # 预处理：去停用词
            text = self._remove_stop_words(sent.text)
            
            # 滑动窗口生成 N-gram
            for pos in range(len(text) - self.n + 1):
                gram_text = text[pos:pos + self.n]
                fingerprint = self._simhash(gram_text)
                
                ngrams.append(NGram(
                    text=gram_text,
                    position=pos,
                    sentence_idx=sent_idx,
                    fingerprint=fingerprint,
                ))
        
        return ngrams
    
    def _remove_stop_words(self, text: str) -> str:
        """去除停用词"""
        return ''.join(c for c in text if c not in self.stop_words)
    
    def _simhash(self, text: str) -> int:
        """生成 SimHash 指纹（简化版）"""
        import hashlib
        # 简化实现：使用 MD5 哈希作为指纹
        return int(hashlib.md5(text.encode()).hexdigest()[:8], 16)
```

### 4. ComparisonEngine (比对引擎)

```python
# services/plagiarism/engine.py

@dataclass
class Match:
    """匹配片段"""
    text: str                    # 匹配的文本
    start_pos: int              # 在文档A中的起始位置
    end_pos: int                # 在文档A中的结束位置
    ngram_count: int            # 包含的 N-gram 数量
    source_doc: str             # 来源文档
    source_start: int           # 在来源文档中的起始位置
    source_end: int             # 在来源文档中的结束位置


@dataclass
class DocumentFingerprint:
    """文档指纹索引"""
    doc_id: str
    ngrams: List[NGram]
    fingerprint_map: Dict[int, List[int]]  # fingerprint -> positions


class ComparisonEngine:
    """查重比对引擎"""
    
    def __init__(self, min_continuous_match: int = 5):
        self.min_continuous_match = min_continuous_match
    
    def compare(
        self,
        docs: Dict[str, List[Sentence]]
    ) -> List[DocumentSimilarity]:
        """
        执行文档间比对
        
        步骤:
        1. 构建指纹索引（所有文档的 N-gram 指纹）
        2. 滑动窗口检测连续重复
        3. 计算相似度分数
        """
        # Step 1: 切分 N-gram
        doc_ngrams = {}
        for doc_id, sentences in docs.items():
            splitter = NGramSplitter()
            doc_ngrams[doc_id] = splitter.split(sentences)
        
        # Step 2: 构建指纹倒排索引
        fingerprint_index = self._build_fingerprint_index(doc_ngrams)
        
        # Step 3: 查找连续匹配
        results = []
        doc_ids = list(docs.keys())
        
        for i, doc_a in enumerate(doc_ids):
            for doc_b in doc_ids[i+1:]:
                matches = self._find_continuous_matches(
                    doc_ngrams[doc_a],
                    doc_ngrams[doc_b],
                    fingerprint_index,
                    doc_b
                )
                
                # 计算相似度
                total_chars = sum(len(s.text) for s in docs[doc_a])
                match_chars = sum(
                    docs[doc_a][m.sentence_idx].text[m.start_pos:m.end_pos]
                    for m in matches
                )
                
                similarity = len(match_chars) / total_chars if total_chars > 0 else 0
                
                results.append(DocumentSimilarity(
                    doc_a=doc_a,
                    doc_b=doc_b,
                    similarity=similarity,
                    matches=matches,
                    total_chars=total_chars,
                    match_chars=len(match_chars),
                ))
        
        return results
    
    def _build_fingerprint_index(
        self,
        doc_ngrams: Dict[str, List[NGram]]
    ) -> Dict[int, Dict[str, List[int]]]:
        """构建指纹倒排索引: {fingerprint: {doc_id: [positions]}}"""
        index = defaultdict(lambda: defaultdict(list))
        
        for doc_id, ngrams in doc_ngrams.items():
            for ng in ngrams:
                index[ng.fingerprint][doc_id].append(ng.position)
        
        return index
    
    def _find_continuous_matches(
        self,
        ngrams_a: List[NGram],
        ngrams_b: List[NGram],
        fingerprint_index: Dict,
        doc_b: str,
    ) -> List[Match]:
        """查找连续重复片段"""
        matches = []
        
        # 构建 doc_b 的指纹集合
        fingerprints_b = {ng.fingerprint for ng in ngrams_b}
        
        # 滑动窗口检测连续匹配
        i = 0
        while i < len(ngrams_a):
            ng = ngrams_a[i]
            
            if ng.fingerprint in fingerprints_b:
                # 找到匹配，扩展窗口
                match_end = i
                while (match_end + 1 < len(ngrams_a) and
                       ngrams_a[match_end + 1].fingerprint in fingerprints_b):
                    match_end += 1
                
                count = match_end - i + 1
                if count >= self.min_continuous_match:
                    # 构造匹配文本
                    start_sent_idx = ngrams_a[i].sentence_idx
                    end_sent_idx = ngrams_a[match_end].sentence_idx
                    
                    matches.append(Match(
                        text="",  # 后续填充
                        start_pos=ngrams_a[i].position,
                        end_pos=ngrams_a[match_end].position + self.n,
                        ngram_count=count,
                        source_doc=doc_b,
                        source_start=0,  # 后续填充
                        source_end=0,
                    ))
                
                i = match_end + 1
            else:
                i += 1
        
        return matches
```

### 5. ResultAggregator (结果聚合器)

```python
# services/plagiarism/aggregator.py

@dataclass
class PlagiarismResult:
    """查重结果"""
    id: str
    total_pairs: int
    high_similarity: List[dict]
    medium_similarity: List[dict]
    low_similarity: List[dict]
    processing_time: float


class ResultAggregator:
    """查重结果聚合器 - 后置过滤"""

    def __init__(self, template_filter: TemplateFilter = None):
        self.template_filter = template_filter or TemplateFilter()

    def aggregate(
        self,
        results: List[DocumentSimilarity],
        threshold_high: float = 0.8,
        threshold_medium: float = 0.5,
        doc_texts: Dict[str, str] = None,
    ) -> PlagiarismResult:
        """
        聚合比对结果 - 后置过滤模式

        步骤:
        1. 遍历每个文档对的匹配结果
        2. 对每个匹配片段进行模板检测
        3. 区分"模板重复"和"有效重复"
        4. 计算总相似度和有效相似度
        """
        high = []
        medium = []
        low = []

        for r in results:
            # 分离模板片段和有效片段
            template_segments = []
            effective_segments = []

            for m in r.matches:
                # 检测是否是模板内容
                if self._is_template_match(m.text):
                    template_segments.append(m)
                else:
                    effective_segments.append(m)

            # 计算有效重复字符数（排除模板）
            effective_chars = sum(len(m.text) for m in effective_segments)
            total_chars = sum(len(m.text) for m in r.matches)
            effective_similarity = effective_chars / total_chars if total_chars > 0 else 0

            result_dict = {
                "doc_a": r.doc_a,
                "doc_b": r.doc_b,
                "similarity": round(r.similarity, 4),          # 总重复率
                "effective_similarity": round(effective_similarity, 4),  # 有效重复率
                "type": self._classify(r.similarity, threshold_high, threshold_medium),
                "total_chars": total_chars,
                "effective_chars": effective_chars,             # 有效重复字符
                "template_chars": total_chars - effective_chars,  # 模板重复字符
                "duplicate_segments": [
                    {
                        "primary_line": m.start_pos,
                        "primary_text": m.text,
                        "sources": [{
                            "doc": m.source_doc,
                            "line": m.source_start,
                            "text": "",  # 后续填充
                        }],
                        "is_template": False,
                        "template_reason": None,
                    }
                    for m in effective_segments[:20]  # 限制数量
                ],
                "template_segments": [
                    {
                        "primary_line": m.start_pos,
                        "primary_text": m.text,
                        "template_reason": self._get_template_reason(m.text),
                    }
                    for m in template_segments[:10]
                ],
            }

            if r.similarity >= threshold_high:
                high.append(result_dict)
            elif r.similarity >= threshold_medium:
                medium.append(result_dict)
            else:
                low.append(result_dict)

        return PlagiarismResult(
            id=f"plagiarism_{int(time.time() * 1000)}",
            total_pairs=len(results),
            high_similarity=high,
            medium_similarity=medium,
            low_similarity=low,
            processing_time=0,  # 外部计时
        )

    def _is_template_match(self, text: str) -> bool:
        """检测匹配片段是否是模板内容"""
        return self.template_filter.is_template(text)

    def _get_template_reason(self, text: str) -> str:
        """获取模板原因"""
        if self.template_filter._is_heading(text):
            return "heading"
        if self.template_filter._is_too_short(text):
            return "short"
        if self.template_filter._is_table_related(text):
            return "table"
        if self.template_filter._is_template(text):
            return "whitelist"
        return "unknown"
    
    def _classify(self, similarity, threshold_high, threshold_medium):
        if similarity >= threshold_high:
            return "high"
        elif similarity >= threshold_medium:
            return "medium"
        return "low"
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
    
    def filter_template_content(self, text: str) -> str:
        """过滤模板内容（兼容旧接口）"""
        # 委托给 TemplateFilter
        pass
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

## 核心组件 - PlagiarismAgent (Layer 6)

```python
# services/plagiarism/agent.py

class PlagiarismAgent:
    """查重 Agent"""
    
    def __init__(
        self,
        threshold: float = 0.5,
        threshold_high: float = 0.8,
        threshold_medium: float = 0.5,
        section_config: Optional[Dict] = None,
        debug: bool = False,
    ):
        self.threshold = threshold
        self.threshold_high = threshold_high
        self.threshold_medium = threshold_medium
        self.debug = debug
        
        # 初始化 Section 提取器
        if section_config and SectionExtractor.validate_config(section_config):
            self.section_extractor = SectionExtractor(section_config)
        else:
            self.section_extractor = None
        
        # 初始化 Layer 5 组件
        self.tokenizer = SentenceTokenizer()
        self.template_filter = TemplateFilter()
        self.ngram_splitter = NGramSplitter()
        self.comparison_engine = ComparisonEngine()
        self.result_aggregator = ResultAggregator()
    
    async def check(
        self,
        files: List[tuple[str, bytes]],  # [(doc_id, file_data)]
    ) -> PlagiarismResult:
        """执行查重"""
        start_time = time.time()
        
        # 1. 文本提取
        texts = {}
        doc_ids = [doc_id for doc_id, _ in files]
        primary_doc_id = doc_ids[0] if doc_ids else None
        
        for idx, (doc_id, file_data) in enumerate(files):
            parser = get_parser(detect_type(file_data))
            result = await parser.parse(file_data)
            full_text = result.content.to_text()
            
            # 只有第一个文档使用 section 提取
            if idx == 0 and self.section_extractor:
                text = self.section_extractor.extract(full_text)
                text = self.template_filter.filter_text(text)
            else:
                text = full_text
            
            texts[doc_id] = text
        
        # 2. 语义分句
        sentences_map = {}
        for doc_id, text in texts.items():
            sentences_map[doc_id] = self.tokenizer.tokenize(text)
        
        # 3. 模板过滤
        filtered_map = {}
        for doc_id, sentences in sentences_map.items():
            filtered_map[doc_id] = self.template_filter.filter(sentences)
        
        # 4. N-gram 比对
        similarities = self.comparison_engine.compare(filtered_map)
        
        # 5. 结果聚合
        result = self.result_aggregator.aggregate(
            similarities,
            self.threshold_high,
            self.threshold_medium,
        )
        result.processing_time = time.time() - start_time
        
        return result
```

## 数据结构

### Sentence

```python
@dataclass
class Sentence:
    """句子"""
    text: str                    # 句子文本
    start_pos: int               # 在原文中的起始位置
    end_pos: int                 # 在原文中的结束位置
    line_number: int             # 起始行号
    is_from_table: bool = False  # 是否来自表格
```

### NGram

```python
@dataclass
class NGram:
    """N-gram 片段"""
    text: str              # N-gram 文本
    position: int          # 在句子中的位置
    sentence_idx: int      # 所属句子索引
    fingerprint: int       # SimHash 指纹
```

### Match

```python
@dataclass
class Match:
    """匹配片段"""
    text: str                    # 匹配的文本
    start_pos: int              # 在文档A中的起始位置
    end_pos: int                # 在文档A中的结束位置
    ngram_count: int            # 包含的 N-gram 数量
    source_doc: str             # 来源文档
    source_start: int           # 在来源文档中的起始位置
    source_end: int             # 在来源文档中的结束位置
```

### DocumentSimilarity

```python
@dataclass
class DocumentSimilarity:
    """文档相似度"""
    doc_a: str
    doc_b: str
    similarity: float
    matches: List[Match]
    total_chars: int
    match_chars: int
```

## 设计原则

1. **语义分句**: 按标点符号（。！？；）分句，而非简单按行
2. **多层过滤**: 白名单 + 标题检测 + 短句过滤，去除模板内容
3. **N-gram 比对**: 滑动窗口生成 N-gram，支持连续匹配检测
4. **指纹索引**: 使用 SimHash 指纹加速大规模比对
5. **位置追溯**: 精确定位到行号、段落、Section
6. **可扩展**: 易于添加更复杂的比对策略

## 与语义分组的区别

| 特性 | 查重（本文） | 语义分组 |
|------|-------------|---------|
| 目标 | 检测文字重复 | 判断领域相关性 |
| 方法 | N-gram 精确匹配 + 指纹索引 | Embedding 语义向量 |
| 输出 | 重复位置 + 来源 | 相似文档列表 |
| 场景 | 抄袭检测、重复申报 | 学科分组、推荐 |
