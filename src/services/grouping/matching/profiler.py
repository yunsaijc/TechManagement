"""
专家画像构建器

使用 LLM 分析专家信息，构建专家画像
"""
import re
from typing import Any, List, Optional

from src.common.llm import get_default_llm_client
from src.common.models.grouping import Expert, ExpertProfile


class ExpertProfiler:
    """专家画像构建器
    
    使用 LLM 从研究领域、论文、擅长专业构建专家画像
    """
    
    def __init__(self, llm: Any = None):
        """初始化
        
        Args:
            llm: LLM 客户端实例
        """
        self.llm = llm or get_default_llm_client()
    
    def build_expert_text(self, expert: Expert) -> str:
        """构建专家融合文本
        
        将专家信息融合为用于向量化的文本
        
        Args:
            expert: 专家
        
        Returns:
            融合后的文本
        """
        parts = []
        
        if expert.xm:
            parts.append(f"姓名: {expert.xm}")
        
        # 添加熟悉学科
        subject_codes = []
        for i in range(1, 6):
            code = getattr(expert, f'sxxk{i}', None)
            if code:
                subject_codes.append(code)
        if subject_codes:
            parts.append(f"熟悉学科: {', '.join(subject_codes)}")
        
        if expert.sxzy:
            parts.append(f"擅长专业: {expert.sxzy}")
        
        if expert.yjly:
            # 限制长度
            yjly = expert.yjly
            if len(yjly) > 2000:
                yjly = yjly[:2000] + "..."
            parts.append(f"研究领域: {yjly}")
        
        if expert.lwlz:
            # 限制长度
            lwlz = expert.lwlz
            if len(lwlz) > 1000:
                lwlz = lwlz[:1000] + "..."
            parts.append(f"论文论著: {lwlz}")
        
        if expert.gzdw:
            parts.append(f"工作单位: {expert.gzdw}")
        
        return "\n\n".join(parts)
    
    async def profile_expert(self, expert: Expert) -> ExpertProfile:
        """分析单个专家
        
        Args:
            expert: 专家
        
        Returns:
            画像结果
        """
        # 构建融合文本
        text = self.build_expert_text(expert)
        
        # 构建 prompt
        prompt = self._build_profile_prompt(expert, text)
        
        # 调用 LLM
        response = await self.llm.ainvoke(prompt)
        content = response.content if hasattr(response, 'content') else str(response)
        
        # 解析结果
        profile = self._parse_profile_result(expert.id, content)
        profile.text = text
        
        return profile
    
    async def profile_experts(self, experts: List[Expert]) -> List[ExpertProfile]:
        """批量分析专家
        
        Args:
            experts: 专家列表
        
        Returns:
            画像结果列表
        """
        results = []
        for expert in experts:
            profile = await self.profile_expert(expert)
            results.append(profile)
        
        return results
    
    def _build_profile_prompt(self, expert: Expert, text: str) -> str:
        """构建画像 prompt
        
        Args:
            expert: 专家
            text: 融合文本
        
        Returns:
            prompt 字符串
        """
        return f"""请分析以下专家信息，构建专家画像。

姓名：{expert.xm}
擅长专业：{expert.sxzy or '无'}
研究领域：{(expert.yjly or '无')[:1000]}
论文论著：{(expert.lwlz or '无')[:500]}
工作单位：{expert.gzdw or '无'}

请提取以下信息（JSON格式）：
{{
    "main_research_area": "主要研究方向（如：有机化学、人工智能）",
    "sub_research_fields": ["细分领域1", "细分领域2"],
    "tech_expertise": ["技术专长1", "技术专长2"],
    "keywords": ["关键词1", "关键词2", "关键词3"]
}}

请只输出 JSON，不要其他内容。"""
    
    def _parse_profile_result(self, expert_id: str, content: str) -> ExpertProfile:
        """解析 LLM 分析结果
        
        Args:
            expert_id: 专家ID
            content: LLM 返回的内容
        
        Returns:
            画像结果
        """
        # 尝试提取 JSON
        try:
            import json
            json_match = re.search(r'\{[\s\S]*\}', content)
            if json_match:
                data = json.loads(json_match.group())
                return ExpertProfile(
                    expert_id=expert_id,
                    main_research_area=data.get("main_research_area"),
                    sub_research_fields=data.get("sub_research_fields", []),
                    tech_expertise=data.get("tech_expertise", []),
                    keywords=data.get("keywords", []),
                )
        except Exception:
            pass
        
        # 解析失败，返回空结果
        return ExpertProfile(expert_id=expert_id)
