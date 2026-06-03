"""
检查器基类

定义所有检查器的公共接口和基础实现。
"""
import re
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from src.common.models.evaluation import CheckResult, CheckItem, EvaluationDimension
from src.common.llm import get_default_llm_client
from src.services.evaluation.profile import (
    PROFILE_GENERIC,
    PROFILE_PLATFORM,
    PROFILE_SCIENCE_POPULARIZATION,
    PROFILE_TECH_RND,
)


class BaseChecker(ABC):
    """检查器基类
    
    所有维度检查器的抽象基类，定义公共接口。
    """
    
    # 子类必须指定维度代码
    dimension: str = ""
    dimension_name: str = ""
    PROJECT_PROFILE_TECH_RND = PROFILE_TECH_RND
    PROJECT_PROFILE_PLATFORM = PROFILE_PLATFORM
    PROJECT_PROFILE_SCIENCE_POPULARIZATION = PROFILE_SCIENCE_POPULARIZATION
    PROJECT_PROFILE_GENERIC = PROFILE_GENERIC
    MAX_PROMPT_SECTIONS = 4
    MAX_PROMPT_SECTION_CHARS = 1800
    MAX_PROMPT_TOTAL_CHARS = 6000
    TABLE_LINE_PATTERN = re.compile(r"^\s*(?:\[表格行\d+\]|[|｜]|第?\d+[行列项])")
    EXCESSIVE_SEPARATOR_PATTERN = re.compile(r"[|｜]\s*")
    SECTION_ALIASES: Dict[str, List[str]] = {
        "预期效益": [
            "预期效益",
            "项目实施的预期经济社会效益目标",
            "项目效益",
            "主要指标、效益",
            "推广应用",
            "应用范围与普及前景",
            "普及前景",
        ],
        "社会效益": [
            "社会效益",
            "项目实施的预期经济社会效益目标",
            "项目效益",
            "主要指标、效益",
            "普及前景",
        ],
        "经济效益": [
            "经济效益",
            "项目实施的预期经济社会效益目标",
            "项目效益",
            "产业化",
            "应用前景",
            "项目实施对产业的引领促进作用",
        ],
        "风险分析": [
            "风险分析",
            "风险控制",
            "风险管理",
            "风险应对",
            "技术风险",
            "市场风险",
            "政策风险",
            "实施制约因素",
        ],
        "风险控制": [
            "风险控制",
            "风险分析",
            "风险管理",
            "风险应对",
            "技术风险",
            "市场风险",
            "政策风险",
            "实施制约因素",
        ],
        "进度安排": [
            "进度安排",
            "实施计划",
            "工作计划",
            "研究计划",
        ],
        "政策依据": [
            "政策依据",
            "政策支撑条件",
            "政策保障",
            "申报项目与所属指南或申报通知方向的关联关系",
        ],
        "经费预算": [
            "经费预算",
            "预算说明",
            "预算合理性说明",
            "项目预算",
            "项目预算表",
            "省级财政资金",
            "直接费用",
            "间接费用",
            "自筹资金",
        ],
        "预算说明": [
            "预算说明",
            "预算合理性说明",
            "项目预算",
            "项目预算表",
            "省级财政资金",
            "直接费用",
            "间接费用",
            "自筹资金",
        ],
        "伦理审查": [
            "伦理审查",
            "组织支撑条件",
            "技术支持",
        ],
        "项目团队": [
            "项目团队",
            "项目组主要成员",
            "负责人及项目主要骨干人员的科研水平及主要成果",
            "任务分工",
            "现有工作基础及合作分工",
        ],
        "人员分工": [
            "人员分工",
            "任务分工",
            "项目组主要成员",
            "现有工作基础及合作分工",
        ],
        "成员简介": [
            "成员简介",
            "负责人及项目主要骨干人员的科研水平及主要成果",
            "项目组主要成员",
        ],
        "预期成果": [
            "预期成果",
            "项目实施的预期绩效目标",
            "项目绩效评价考核目标及指标",
            "主要指标、效益",
            "科普内容产出",
        ],
        "考核指标": [
            "考核指标",
            "项目实施的预期绩效目标",
            "项目绩效评价考核目标及指标",
            "主要指标、效益",
            "科普基础设施建设",
            "科普内容产出",
            "科普活动开展",
        ],
        "技术指标": [
            "技术指标",
            "项目实施的预期绩效目标",
            "项目绩效评价考核目标及指标",
            "主要指标、效益",
        ],
        "成果形式": [
            "成果形式",
            "项目实施的预期绩效目标",
            "项目绩效评价考核目标及指标",
            "科普内容产出",
        ],
    }
    
    def __init__(
        self,
        llm: Optional[Any] = None,
        project_profile: str = PROFILE_GENERIC,
        dimension_overrides: Optional[Dict[str, Any]] = None,
    ):
        """初始化检查器
        
        Args:
            llm: LLM实例，如未指定则使用默认配置
        """
        self.llm = llm or get_default_llm_client()
        self._check_items: List[Dict[str, str]] = []
        self._required_sections: List[str] = []
        self.project_profile = project_profile
        self.dimension_overrides = dimension_overrides or {}
    
    @property
    def check_items(self) -> List[Dict[str, str]]:
        """获取检查项列表"""
        return self._check_items
    
    @property
    def required_sections(self) -> List[str]:
        """获取依赖的文档章节"""
        override_sections = self.dimension_overrides.get("required_sections")
        if override_sections:
            return override_sections
        return self._required_sections

    @property
    def alternative_sections(self) -> List[str]:
        """获取替代章节列表"""
        return list(self.dimension_overrides.get("alternative_sections", []))
    
    @abstractmethod
    async def check(self, content: Dict[str, Any]) -> CheckResult:
        """执行检查
        
        Args:
            content: 包含文档内容的字典，key为章节名，value为章节内容
            
        Returns:
            CheckResult: 检查结果
        """
        pass
    
    def _build_prompt(self, content: Dict[str, Any]) -> str:
        """构建LLM提示词
        
        Args:
            content: 文档内容
            
        Returns:
            str: 构建好的提示词
        """
        raise NotImplementedError("子类应实现此方法")
    
    def _parse_result(self, llm_output: str) -> CheckResult:
        """解析LLM输出
        
        Args:
            llm_output: LLM的输出文本
            
        Returns:
            CheckResult: 解析后的检查结果
        """
        raise NotImplementedError("子类应实现此方法")
    
    def _extract_sections(
        self, 
        content: Dict[str, Any], 
        section_names: List[str]
    ) -> Dict[str, Any]:
        """提取指定章节的内容
        
        Args:
            content: 完整文档内容
            section_names: 需要提取的章节名列表
            
        Returns:
            Dict[str, Any]: 提取的章节内容
        """
        result = {}
        for name in section_names:
            matched_sections = self._match_sections(content, name)
            if matched_sections:
                result[name] = "\n\n".join(matched_sections)
        
        return result

    def _match_sections(self, content: Dict[str, Any], section_name: str) -> List[str]:
        """匹配章节及其别名，并返回去重后的内容列表"""
        matched: List[str] = []
        seen_keys: set[str] = set()
        candidates = [section_name] + self.SECTION_ALIASES.get(section_name, [])

        for candidate in candidates:
            for key, value in content.items():
                if key in seen_keys:
                    continue
                if self._section_matches(key, candidate):
                    text = str(value).strip()
                    if text:
                        matched.append(text)
                        seen_keys.add(key)

        if section_name == "进度安排":
            for key, value in content.items():
                if key in seen_keys:
                    continue
                if self._is_schedule_timeline_section(key):
                    text = str(value).strip()
                    if text:
                        matched.append(f"{key}\n{text}")
                        seen_keys.add(key)

        return matched

    def _section_matches(self, actual_name: str, expected_name: str) -> bool:
        """判断实际章节名是否匹配目标章节名"""
        normalized_actual = re.sub(r"\s+", "", actual_name)
        normalized_expected = re.sub(r"\s+", "", expected_name)
        return (
            normalized_actual == normalized_expected
            or normalized_expected in normalized_actual
            or normalized_actual in normalized_expected
        )

    def _is_schedule_timeline_section(self, section_name: str) -> bool:
        """识别形如 2025年7月-2025年12月 的时间段章节"""
        normalized = re.sub(r"\s+", "", section_name)
        return bool(re.fullmatch(r"\d{4}年\d{1,2}月[-—至]+\d{4}年\d{1,2}月", normalized))
    
    def _format_content_for_prompt(self, content: Dict[str, Any]) -> str:
        """格式化内容用于提示词
        
        Args:
            content: 文档内容
            
        Returns:
            str: 格式化后的文本
        """
        lines = []
        total_chars = 0
        selected_items = list(content.items())[: self.MAX_PROMPT_SECTIONS]

        for section, text in selected_items:
            normalized_text = self._normalize_text_for_prompt(str(text))
            truncated_text = self._truncate_text_for_prompt(normalized_text, self.MAX_PROMPT_SECTION_CHARS)
            if total_chars >= self.MAX_PROMPT_TOTAL_CHARS:
                break

            remaining = self.MAX_PROMPT_TOTAL_CHARS - total_chars
            if len(truncated_text) > remaining:
                truncated_text = self._truncate_text_for_prompt(truncated_text, remaining)

            lines.append(f"## {section}")
            lines.append(truncated_text)
            lines.append("")
            total_chars += len(truncated_text)
        return "\n".join(lines)

    def _normalize_text_for_prompt(self, text: str) -> str:
        """清理提示词中的长表格、空白和明显噪声"""
        normalized_lines: List[str] = []
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if self.TABLE_LINE_PATTERN.match(line):
                continue
            if self.EXCESSIVE_SEPARATOR_PATTERN.search(line) and len(line) > 80:
                continue
            normalized_lines.append(line)

        normalized = "\n".join(normalized_lines)
        normalized = re.sub(r"\n{3,}", "\n\n", normalized)
        return normalized.strip()

    def _truncate_text_for_prompt(self, text: str, limit: int) -> str:
        """截断长文本，保留头尾信息，降低超时概率"""
        if limit <= 0:
            return ""
        if len(text) <= limit:
            return text
        if limit <= 120:
            return text[:limit]

        head = int(limit * 0.7)
        tail = max(0, limit - head - 12)
        suffix = text[-tail:] if tail else ""
        return f"{text[:head]}\n[内容已截断]\n{suffix}".strip()
    
    def _calculate_weighted_score(self, items: List[CheckItem]) -> float:
        """计算加权得分
        
        Args:
            items: 检查项列表
            
        Returns:
            float: 加权平均分
        """
        if not items:
            return 5.0  # 默认中等分数
        
        total_weight = sum(item.weight for item in items)
        if total_weight == 0:
            return 5.0
        
        weighted_sum = sum(item.score * item.weight for item in items)
        return round(weighted_sum / total_weight, 2)
    
    def _aggregate_confidence(self, items: List[CheckItem]) -> float:
        """聚合置信度
        
        Args:
            items: 检查项列表
            
        Returns:
            float: 平均置信度
        """
        if not items:
            return 0.5
        
        return round(sum(item.weight for item in items) / len(items), 2)

    def infer_project_profile(self, content: Dict[str, Any]) -> str:
        """向后兼容：优先使用 agent 注入画像，否则回退为通用口径"""
        return self.get_project_profile(content)

    def get_project_profile(self, content: Dict[str, Any]) -> str:
        """获取当前检查执行使用的项目画像"""
        explicit_profile = content.get("_project_profile")
        if isinstance(explicit_profile, str) and explicit_profile:
            return explicit_profile
        return self.project_profile or self.PROJECT_PROFILE_GENERIC

    def profile_matches(self, content: Dict[str, Any], *profiles: str) -> bool:
        """判断当前画像是否命中指定类型"""
        return self.get_project_profile(content) in profiles

    def get_alternative_sections(self, *section_groups: List[str]) -> List[str]:
        """合并检查器自身与画像覆盖的替代章节"""
        merged: List[str] = []
        seen: set[str] = set()

        for section_name in self.alternative_sections:
            if section_name not in seen:
                merged.append(section_name)
                seen.add(section_name)

        for group in section_groups:
            for section_name in group:
                if section_name not in seen:
                    merged.append(section_name)
                    seen.add(section_name)

        return merged

    def build_degraded_result(self, content: Dict[str, Any], reason: str = "") -> CheckResult:
        """在模型不可用时，基于章节命中结果返回规则降级结果"""
        sections = self._extract_sections(content, self.required_sections)
        if not sections:
            missing_issue = self._build_missing_sections_issue()
            return CheckResult(
                dimension=self.dimension,
                dimension_name=self.dimension_name,
                score=5.0,
                confidence=0.3,
                opinion=f"未找到{self.dimension_name}相关章节，当前无法完成有效评估",
                issues=[missing_issue],
                highlights=[],
                items=[],
                details={"degraded": True, "reason": reason},
            )

        section_names = list(sections.keys())
        opinion = (
            f"已定位到 {len(section_names)} 个相关章节，当前基于规则完成基础判断；"
            "详细评语待模型服务恢复后补充。"
        )
        highlights = [f"已识别章节：{name}" for name in section_names[:2]]
        issues = []
        if reason:
            issues.append(f"模型不可用，已输出规则降级结果：{reason}")

        return CheckResult(
            dimension=self.dimension,
            dimension_name=self.dimension_name,
            score=6.0,
            confidence=0.45,
            opinion=opinion,
            issues=issues,
            highlights=highlights,
            items=[],
            details={"degraded": True, "reason": reason, "matched_sections": section_names},
        )

    def _build_missing_sections_issue(self) -> str:
        """生成缺失章节提示"""
        required_sections = self.required_sections
        if not required_sections:
            return "缺少相关章节"
        if len(required_sections) == 1:
            return f"缺少{required_sections[0]}章节"
        primary = required_sections[:2]
        return f"缺少{'或'.join(primary)}章节"
