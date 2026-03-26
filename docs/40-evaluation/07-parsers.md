# 📄 正文解析器设计

## 解析流程

```
┌─────────────────────────────────────────────────────────────┐
│                     文档解析流程                              │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  项目ID ──→ 获取文件列表 ──→ 解析文档 ──→ 章节提取 ──→ 输出  │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

---

## 章节定义

### 章节映射表

| 章节ID | 章节名称 | 用于评审维度 | 匹配关键词 |
|--------|----------|--------------|------------|
| `tech_solution` | 技术方案 | 可行性、创新性 | 技术方案、技术路线、实施方案 |
| `innovation_points` | 创新点 | 创新性 | 创新点、创新内容、主要创新 |
| `team_intro` | 团队介绍 | 团队能力 | 团队介绍、项目团队、人员配置 |
| `leader_resume` | 负责人简历 | 团队能力 | 负责人、项目负责人、简历 |
| `research_basis` | 研究基础 | 团队能力 | 研究基础、前期工作、工作基础 |
| `expected_outcome` | 预期成果 | 预期成果 | 预期成果、预期产出、成果形式 |
| `assessment_indicators` | 考核指标 | 预期成果 | 考核指标、绩效指标、验收指标 |
| `social_benefit` | 社会效益 | 社会效益 | 社会效益、社会影响、社会价值 |
| `economic_benefit` | 经济效益 | 经济效益 | 经济效益、经济分析、投入产出 |
| `benefit_analysis` | 效益分析 | 社会效益、经济效益 | 效益分析、效益评估 |
| `risk_analysis` | 风险分析 | 风险控制 | 风险分析、风险识别、风险因素 |
| `risk_control` | 风险控制 | 风险控制 | 风险控制、风险应对、风险措施 |
| `schedule` | 进度安排 | 进度合理性 | 进度安排、实施进度、时间安排 |
| `implementation_plan` | 实施计划 | 进度合理性 | 实施计划、实施方案、工作计划 |
| `budget` | 经费预算 | 经济效益、合规性 | 经费预算、资金预算、预算说明 |

---

## 解析器架构

```
┌─────────────────────────────────────────────────────────────────────┐
│                       DocumentParser                                 │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐            │
│  │ 文件获取    │    │ 文档解析    │    │ 章节提取    │            │
│  │ FileFetcher │    │ DocParser   │    │ SectionExt  │            │
│  └──────┬──────┘    └──────┬──────┘    └──────┬──────┘            │
│         │                  │                  │                    │
│         └──────────────────┼──────────────────┘                    │
│                            │                                        │
│                            ▼                                        │
│                   Dict[section_id, content]                        │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 核心组件实现

### 1. 文档解析器

```python
# src/services/evaluation/parsers/document_parser.py

import re
import logging
from typing import Dict, List, Optional, Tuple

from src.common.file_handler import PDFParser, DOCXParser


logger = logging.getLogger(__name__)


class Section(BaseModel):
    """章节"""
    id: str                           # 章节ID
    title: str                        # 章节标题
    content: str                      # 章节内容
    start_pos: Optional[int] = None   # 起始位置
    end_pos: Optional[int] = None     # 结束位置


class DocumentParser:
    """文档解析器"""
    
    # 章节匹配规则
    SECTION_PATTERNS = {
        "tech_solution": [
            r"技术方案",
            r"技术路线",
            r"实施方案",
            r"技术内容",
        ],
        "innovation_points": [
            r"创新点",
            r"创新内容",
            r"主要创新",
            r"技术创新",
        ],
        "team_intro": [
            r"团队介绍",
            r"项目团队",
            r"人员配置",
            r"团队构成",
        ],
        "leader_resume": [
            r"负责人简介",
            r"项目负责人",
            r"负责人简历",
            r"项目负责人情况",
        ],
        "research_basis": [
            r"研究基础",
            r"前期工作",
            r"工作基础",
            r"研究条件",
        ],
        "expected_outcome": [
            r"预期成果",
            r"预期产出",
            r"成果形式",
            r"预期目标",
        ],
        "assessment_indicators": [
            r"考核指标",
            r"绩效指标",
            r"验收指标",
            r"考核要求",
        ],
        "social_benefit": [
            r"社会效益",
            r"社会影响",
            r"社会价值",
        ],
        "economic_benefit": [
            r"经济效益",
            r"经济分析",
            r"投入产出",
        ],
        "benefit_analysis": [
            r"效益分析",
            r"效益评估",
        ],
        "risk_analysis": [
            r"风险分析",
            r"风险识别",
            r"风险因素",
        ],
        "risk_control": [
            r"风险控制",
            r"风险应对",
            r"风险措施",
        ],
        "schedule": [
            r"进度安排",
            r"实施进度",
            r"时间安排",
            r"进度计划",
        ],
        "implementation_plan": [
            r"实施计划",
            r"实施方案",
            r"工作计划",
        ],
        "budget": [
            r"经费预算",
            r"资金预算",
            r"预算说明",
            r"经费使用",
        ],
    }
    
    def __init__(self):
        """初始化解析器"""
        self.pdf_parser = PDFParser()
        self.docx_parser = DOCXParser()
    
    async def parse(self, project_id: str) -> Dict[str, str]:
        """
        解析项目文档
        
        Args:
            project_id: 项目ID
        
        Returns:
            Dict[str, str]: 章节内容字典 {section_id: content}
        """
        logger.info(f"开始解析项目文档: {project_id}")
        
        # 1. 获取文件列表
        file_paths = await self._get_project_files(project_id)
        
        if not file_paths:
            logger.warning(f"项目 {project_id} 没有找到文档文件")
            return {}
        
        # 2. 解析所有文档
        full_text = await self._parse_all_documents(file_paths)
        
        if not full_text:
            logger.warning(f"项目 {project_id} 文档解析结果为空")
            return {}
        
        # 3. 提取章节
        sections = self._extract_sections(full_text)
        
        logger.info(f"解析完成，共提取 {len(sections)} 个章节")
        return sections
    
    async def _get_project_files(self, project_id: str) -> List[str]:
        """
        获取项目文件列表
        
        Args:
            project_id: 项目ID
        
        Returns:
            List[str]: 文件路径列表
        """
        # TODO: 从存储服务或数据库获取文件列表
        # 这里需要根据实际存储方式实现
        return []
    
    async def _parse_all_documents(self, file_paths: List[str]) -> str:
        """
        解析所有文档
        
        Args:
            file_paths: 文件路径列表
        
        Returns:
            str: 合并后的文本内容
        """
        texts = []
        
        for path in file_paths:
            try:
                if path.lower().endswith(".pdf"):
                    text = await self._parse_pdf(path)
                elif path.lower().endswith(".docx"):
                    text = await self._parse_docx(path)
                elif path.lower().endswith(".doc"):
                    # 旧版 Word 格式，尝试用 docx 解析
                    text = await self._parse_docx(path)
                else:
                    logger.warning(f"不支持的文件格式: {path}")
                    continue
                
                if text:
                    texts.append(text)
                    
            except Exception as e:
                logger.error(f"解析文件失败 {path}: {e}")
                continue
        
        return "\n\n".join(texts)
    
    async def _parse_pdf(self, file_path: str) -> Optional[str]:
        """解析 PDF 文件"""
        try:
            text = await self.pdf_parser.extract_text(file_path)
            return text
        except Exception as e:
            logger.error(f"PDF 解析失败: {e}")
            return None
    
    async def _parse_docx(self, file_path: str) -> Optional[str]:
        """解析 DOCX 文件"""
        try:
            text = await self.docx_parser.extract_text(file_path)
            return text
        except Exception as e:
            logger.error(f"DOCX 解析失败: {e}")
            return None
    
    def _extract_sections(self, document: str) -> Dict[str, str]:
        """
        提取章节内容
        
        Args:
            document: 文档全文
        
        Returns:
            Dict[str, str]: 章节内容字典
        """
        sections = {}
        
        for section_id, patterns in self.SECTION_PATTERNS.items():
            content = self._find_section(document, patterns)
            if content:
                sections[section_id] = content
        
        return sections
    
    def _find_section(
        self, 
        document: str, 
        patterns: List[str],
        max_length: int = 3000,
    ) -> Optional[str]:
        """
        查找章节内容
        
        Args:
            document: 文档全文
            patterns: 匹配模式列表
            max_length: 内容最大长度
        
        Returns:
            Optional[str]: 章节内容
        """
        for pattern in patterns:
            # 尝试多种匹配方式
            
            # 方式1：标题 + 内容（到下一个标题）
            regex = rf"({pattern})[：:\s]*\n(.*?)(?=\n\s*[一二三四五六七八九十\d]+[、.]|\n\s*第[一二三四五六七八九十\d]+[章节]|$)"
            match = re.search(regex, document, re.DOTALL | re.IGNORECASE)
            
            if match:
                content = match.group(2).strip()
                if len(content) > 50:  # 确保有一定内容
                    return content[:max_length]
            
            # 方式2：标题行后的内容
            regex = rf"{pattern}[：:\s]*\n(.+)"
            match = re.search(regex, document, re.IGNORECASE)
            
            if match:
                content = match.group(1).strip()
                if len(content) > 50:
                    return content[:max_length]
        
        return None
```

---

### 2. 字段定位器

```python
# src/services/evaluation/parsers/field_locator.py

import re
from typing import Dict, List, Optional, Tuple


class FieldLocation(BaseModel):
    """字段位置"""
    field_name: str           # 字段名称
    value: str                # 字段值
    start_pos: int            # 起始位置
    end_pos: int              # 结束位置


class FieldLocator:
    """字段定位器 - 定位关键信息位置"""
    
    # 关键字段匹配规则
    FIELD_PATTERNS = {
        "project_name": [
            r"项目名称[：:]\s*(.+?)(?:\n|$)",
            r"项目名称[：:]\s*([^\n]+)",
        ],
        "project_leader": [
            r"负责人[：:]\s*(.+?)(?:\n|$)",
            r"项目负责人[：:]\s*(.+?)(?:\n|$)",
        ],
        "organization": [
            r"承担单位[：:]\s*(.+?)(?:\n|$)",
            r"申报单位[：:]\s*(.+?)(?:\n|$)",
        ],
        "budget_total": [
            r"总经费[：:]\s*(\d+\.?\d*)",
            r"项目经费[：:]\s*(\d+\.?\d*)",
        ],
        "duration": [
            r"实施期限[：:]\s*(\d+)\s*[个]?[年月]",
            r"项目周期[：:]\s*(\d+)\s*[个]?[年月]",
        ],
        "start_date": [
            r"开始日期[：:]\s*(\d{4}[-/年]\d{1,2}[-/月]\d{1,2}[日]?)",
            r"起始时间[：:]\s*(\d{4}[-/年]\d{1,2}[-/月]\d{1,2}[日]?)",
        ],
        "end_date": [
            r"结束日期[：:]\s*(\d{4}[-/年]\d{1,2}[-/月]\d{1,2}[日]?)",
            r"完成时间[：:]\s*(\d{4}[-/年]\d{1,2}[-/月]\d{1,2}[日]?)",
        ],
    }
    
    def locate(self, document: str) -> Dict[str, FieldLocation]:
        """
        定位关键字段
        
        Args:
            document: 文档全文
        
        Returns:
            Dict[str, FieldLocation]: 字段位置字典
        """
        results = {}
        
        for field_name, patterns in self.FIELD_PATTERNS.items():
            location = self._find_field(document, field_name, patterns)
            if location:
                results[field_name] = location
        
        return results
    
    def _find_field(
        self, 
        document: str, 
        field_name: str,
        patterns: List[str],
    ) -> Optional[FieldLocation]:
        """
        查找字段
        
        Args:
            document: 文档全文
            field_name: 字段名称
            patterns: 匹配模式列表
        
        Returns:
            Optional[FieldLocation]: 字段位置
        """
        for pattern in patterns:
            match = re.search(pattern, document)
            if match:
                value = match.group(1).strip()
                start = match.start(1)
                end = match.end(1)
                
                return FieldLocation(
                    field_name=field_name,
                    value=value,
                    start_pos=start,
                    end_pos=end,
                )
        
        return None
    
    def find_mentions(
        self, 
        document: str, 
        keywords: List[str],
        context_chars: int = 50,
    ) -> List[Dict]:
        """
        查找关键词提及位置
        
        Args:
            document: 文档全文
            keywords: 关键词列表
            context_chars: 上下文字符数
        
        Returns:
            List[Dict]: 提及信息列表
        """
        mentions = []
        
        for keyword in keywords:
            for match in re.finditer(re.escape(keyword), document):
                start = max(0, match.start() - context_chars)
                end = min(len(document), match.end() + context_chars)
                
                mentions.append({
                    "keyword": keyword,
                    "position": match.start(),
                    "context": document[start:end],
                })
        
        return sorted(mentions, key=lambda x: x["position"])
```

---

### 3. 数据仓库

```python
# src/services/evaluation/storage/project_repo.py

import logging
from typing import Any, Dict, Optional

from src.common.database import get_project_db


logger = logging.getLogger(__name__)


class ProjectRepository:
    """项目数据仓库"""
    
    def __init__(self):
        self.db = get_project_db()
    
    async def get_project_info(self, project_id: str) -> Dict[str, Any]:
        """
        获取项目基本信息
        
        Args:
            project_id: 项目ID
        
        Returns:
            Dict: 项目信息字典
        """
        # 从 Sb_Jbxx 表获取基本信息
        query = """
            SELECT 
                id, xmmc, gjc, ssxk1, ssxk2,
                xmFzr, cddwMc, cddwXydm,
                year, starttime, endtime
            FROM Sb_Jbxx
            WHERE id = ?
        """
        
        result = await self.db.fetch_one(query, [project_id])
        
        if not result:
            raise ValueError(f"项目不存在: {project_id}")
        
        return dict(result)
    
    async def get_project_intro(self, project_id: str) -> Optional[str]:
        """
        获取项目简介
        
        Args:
            project_id: 项目ID
        
        Returns:
            Optional[str]: 项目简介
        """
        query = """
            SELECT xmjj, lxbj
            FROM Sb_Jj
            WHERE id = ?
        """
        
        result = await self.db.fetch_one(query, [project_id])
        
        if result:
            return result.get("xmjj") or result.get("lxbj")
        
        return None
    
    async def get_project_files(self, project_id: str) -> list:
        """
        获取项目文件列表
        
        Args:
            project_id: 项目ID
        
        Returns:
            list: 文件路径列表
        """
        # TODO: 根据实际文件存储方式实现
        return []
```

---

## 解析示例

### 输入文档结构

```
项目申报书

一、项目基本信息
项目名称：基于深度学习的智能诊断系统研究
负责人：张三
承担单位：XX大学
...

二、技术方案
本项目采用深度学习技术，构建智能诊断系统...
（详细内容）

三、创新点
1. 提出了一种新的神经网络结构...
2. 实现了多模态数据融合...
...

四、团队介绍
项目负责人张三，教授，博士生导师...

五、预期成果
1. 发表 SCI 论文 3-5 篇
2. 申请发明专利 2 项
...

六、经费预算
总经费：100万元
...
```

### 解析输出

```python
{
    "tech_solution": "本项目采用深度学习技术，构建智能诊断系统...",
    "innovation_points": "1. 提出了一种新的神经网络结构...2. 实现了多模态数据融合...",
    "team_intro": "项目负责人张三，教授，博士生导师...",
    "expected_outcome": "1. 发表 SCI 论文 3-5 篇\n2. 申请发明专利 2 项...",
    "budget": "总经费：100万元...",
}
```

---

## 相关文档

- [← Agent 设计](06-agent.md)
- [API 接口文档 →](08-api.md)