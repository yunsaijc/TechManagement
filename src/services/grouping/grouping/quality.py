"""
项目质量评估器

使用 LLM 评估项目的创新性、技术难度、应用价值
"""
import re
from typing import Any, Dict, List, Optional

from src.common.llm import get_default_llm_client
from src.common.models.grouping import Project, ProjectAnalysis, ProjectQuality


class QualityAssessor:
    """项目质量评估器
    
    使用 LLM 评估项目的创新性、技术难度、应用价值
    """
    
    def __init__(self, llm: Any = None):
        """初始化
        
        Args:
            llm: LLM 客户端实例
        """
        self.llm = llm or get_default_llm_client()
    
    async def assess_quality(
        self,
        project: Project,
        project_analysis: Optional[ProjectAnalysis] = None
    ) -> ProjectQuality:
        """评估单个项目质量
        
        Args:
            project: 项目
            project_analysis: 项目分析结果（可选）
        
        Returns:
            质量评估结果
        """
        # 构建评估文本
        text = self._build_assessment_text(project, project_analysis)
        
        # 构建 prompt
        prompt = self._build_assessment_prompt(text)
        
        # 调用 LLM
        response = await self.llm.ainvoke(prompt)
        content = response.content if hasattr(response, 'content') else str(response)
        
        # 解析结果
        quality = self._parse_assessment_result(project.id, content)
        
        return quality
    
    async def assess_projects(
        self,
        projects: List[Project],
        project_analyses: Optional[Dict[str, ProjectAnalysis]] = None
    ) -> Dict[str, ProjectQuality]:
        """批量评估项目质量
        
        Args:
            projects: 项目列表
            project_analyses: 项目分析结果字典
        
        Returns:
            项目ID -> 质量评估结果
        """
        results = {}
        
        for project in projects:
            analysis = None
            if project_analyses:
                analysis = project_analyses.get(project.id)
            
            quality = await self.assess_quality(project, analysis)
            results[project.id] = quality
        
        return results
    
    def _build_assessment_text(
        self,
        project: Project,
        analysis: Optional[ProjectAnalysis]
    ) -> str:
        """构建评估文本
        
        Args:
            project: 项目
            analysis: 项目分析结果
        
        Returns:
            评估文本
        """
        parts = []
        
        # 项目名称
        if project.xmmc:
            parts.append(f"项目名称: {project.xmmc}")
        
        # 关键词
        if project.gjc:
            parts.append(f"关键词: {project.gjc}")
        
        # 学科代码
        if project.ssxk1:
            parts.append(f"学科代码: {project.ssxk1}")
        
        # 项目简介
        if project.xmjj:
            # 清洗 HTML
            clean_intro = self._clean_html(project.xmjj)
            if len(clean_intro) > 1500:
                clean_intro = clean_intro[:1500] + "..."
            parts.append(f"项目简介: {clean_intro}")
        
        # LLM 分析结果
        if analysis:
            if analysis.innovation:
                parts.append(f"核心创新点: {analysis.innovation}")
            if analysis.tech_direction:
                parts.append(f"技术方向: {analysis.tech_direction}")
            if analysis.research_field:
                parts.append(f"研究领域: {analysis.research_field}")
            if analysis.application:
                parts.append(f"应用场景: {analysis.application}")
        
        return "\n".join(parts)
    
    def _build_assessment_prompt(self, text: str) -> str:
        """构建评估 prompt
        
        Args:
            text: 评估文本
        
        Returns:
            prompt 字符串
        """
        return f"""请评估以下项目的质量分数（0-100分）。

{text}

请根据以下三个维度进行评估：
1. 创新性（40%权重）：技术是否具有原创性，是否处于领先水平
2. 技术难度（30%权重）：技术实现是否复杂，难度高低
3. 应用价值（30%权重）：推广应用前景如何，经济效益如何

请给出评分和简要评语（JSON格式）：
{{
    "innovation_score": 85,
    "difficulty_score": 75,
    "value_score": 80,
    "total_score": 80,
    "comment": "该项目在XX领域具有创新性，技术实现有一定难度..."
}}

请只输出 JSON，不要其他内容。"""
    
    def _parse_assessment_result(
        self,
        project_id: str,
        content: str
    ) -> ProjectQuality:
        """解析 LLM 评估结果
        
        Args:
            project_id: 项目ID
            content: LLM 返回的内容
        
        Returns:
            质量评估结果
        """
        try:
            import json
            # 查找 JSON 块
            json_match = re.search(r'\{[\s\S]*\}', content)
            if json_match:
                data = json.loads(json_match.group())
                
                return ProjectQuality(
                    project_id=project_id,
                    innovation_score=float(data.get("innovation_score", 75)),
                    difficulty_score=float(data.get("difficulty_score", 75)),
                    value_score=float(data.get("value_score", 75)),
                    total_score=float(data.get("total_score", 75)),
                    comment=data.get("comment", "")
                )
        except Exception:
            pass
        
        # 解析失败，返回默认结果
        return ProjectQuality(
            project_id=project_id,
            innovation_score=75.0,
            difficulty_score=75.0,
            value_score=75.0,
            total_score=75.0,
            comment="评估失败，使用默认分数"
        )
    
    def _clean_html(self, text: str) -> str:
        """清洗 HTML 标签
        
        Args:
            text: 原始文本
        
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
