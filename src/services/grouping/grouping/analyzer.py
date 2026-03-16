"""
项目内容分析器

使用 LLM 分析项目内容，提取核心创新点、技术方向、研究领域
"""
import re
from typing import Any, List, Optional

from src.common.llm import get_default_llm_client
from src.common.models.grouping import Project, ProjectAnalysis


class ProjectAnalyzer:
    """项目内容分析器
    
    使用 LLM 提取项目的核心创新点、技术方向、研究领域
    """
    
    def __init__(self, llm: Any = None):
        """初始化
        
        Args:
            llm: LLM 客户端实例
        """
        self.llm = llm or get_default_llm_client()
    
    def clean_html(self, text: str) -> str:
        """清洗 HTML 标签，提取纯文本
        
        Args:
            text: 原始文本 (可能包含 HTML)
        
        Returns:
            纯文本
        """
        if not text:
            return ""
        
        # 移除 HTML 标签
        clean = re.sub(r'<[^>]+>', '', text)
        # 移除多余空白
        clean = re.sub(r'\s+', ' ', clean)
        return clean.strip()
    
    def build_project_text(self, project: Project) -> str:
        """构建项目融合文本
        
        将项目名称、关键词、简介融合为用于向量化的文本
        
        Args:
            project: 项目
        
        Returns:
            融合后的文本
        """
        parts = []
        
        if project.xmmc:
            parts.append(f"项目名称: {project.xmmc}")
        
        if project.gjc:
            parts.append(f"关键词: {project.gjc}")
        
        # 清洗并添加简介
        if project.xmjj:
            clean_intro = self.clean_html(project.xmjj)
            # 限制长度，避免过长
            if len(clean_intro) > 2000:
                clean_intro = clean_intro[:2000] + "..."
            parts.append(f"项目简介: {clean_intro}")
        
        if project.lxbj:
            clean_lxbj = self.clean_html(project.lxbj)
            if len(clean_lxbj) > 1000:
                clean_lxbj = clean_lxbj[:1000] + "..."
            parts.append(f"类型编辑: {clean_lxbj}")
        
        return "\n\n".join(parts)
    
    async def analyze_project(self, project: Project) -> ProjectAnalysis:
        """分析单个项目
        
        Args:
            project: 项目
        
        Returns:
            分析结果
        """
        # 构建融合文本
        text = self.build_project_text(project)
        
        # 构建 prompt
        prompt = self._build_analysis_prompt(project, text)
        
        # 调用 LLM
        response = await self.llm.ainvoke(prompt)
        content = response.content if hasattr(response, 'content') else str(response)
        
        # 解析结果
        analysis = self._parse_analysis_result(project.id, content)
        analysis.text = text
        
        return analysis
    
    async def analyze_projects(self, projects: List[Project]) -> List[ProjectAnalysis]:
        """批量分析项目
        
        Args:
            projects: 项目列表
        
        Returns:
            分析结果列表
        """
        results = []
        for project in projects:
            analysis = await self.analyze_project(project)
            results.append(analysis)
        
        return results
    
    def _build_analysis_prompt(self, project: Project, text: str) -> str:
        """构建分析 prompt
        
        Args:
            project: 项目
            text: 融合文本
        
        Returns:
            prompt 字符串
        """
        return f"""请分析以下项目内容，提取关键信息。

项目名称：{project.xmmc}
关键词：{project.gjc or '无'}
学科代码：{project.ssxk1 or '无'}
项目简介：{self.clean_html(project.xmjj or '无') if project.xmjj else '无'}

请提取以下信息（JSON格式）：
{{
    "innovation": "核心创新点（50字以内）",
    "tech_direction": "技术方向，用逗号分隔（如：人工智能,电力系统,自动化）",
    "research_field": "研究领域，用逗号分隔（如：故障预测,智能电网,数据挖掘）",
    "application": "应用场景，用逗号分隔（如：电力系统,工业物联网,智慧城市）"
}}

请只输出 JSON，不要其他内容。"""
    
    def _parse_analysis_result(self, project_id: str, content: str) -> ProjectAnalysis:
        """解析 LLM 分析结果
        
        Args:
            project_id: 项目ID
            content: LLM 返回的内容
        
        Returns:
            分析结果
        """
        # 尝试提取 JSON
        try:
            # 查找 JSON 块
            import json
            json_match = re.search(r'\{[\s\S]*\}', content)
            if json_match:
                data = json.loads(json_match.group())
                return ProjectAnalysis(
                    project_id=project_id,
                    innovation=data.get("innovation"),
                    tech_direction=data.get("tech_direction"),
                    research_field=data.get("research_field"),
                    application=data.get("application"),
                )
        except Exception:
            pass
        
        # 解析失败，返回空结果
        return ProjectAnalysis(project_id=project_id)
