"""
关系回避检测器

检测并回避可能影响评审公平性的关系
"""
from typing import Dict, List, Optional, Set

from src.common.models.grouping import AvoidanceInfo, Expert, Project


class AvoidanceChecker:
    """关系回避检测器
    
    检测并回避可能影响评审公平性的关系：
    1. 师生关系
    2. 历史合作关系
    3. 同一单位
    """
    
    def __init__(self):
        """初始化"""
        # 缓存关系数据
        self._teacher_student_cache: Dict[str, Set[str]] = {}  # expert_id -> set of project_ids
        self._cooperation_cache: Dict[str, Set[str]] = {}  # expert_id -> set of project_ids
        self._expert_units: Dict[str, str] = {}  # expert_id -> unit
        self._project_units: Dict[str, str] = {}  # project_id -> unit
    
    def check_all(
        self,
        expert: Expert,
        project: Project
    ) -> Optional[AvoidanceInfo]:
        """检查所有回避关系
        
        Args:
            expert: 专家
            project: 项目
        
        Returns:
            回避信息（如果有回避则返回，否则返回 None）
        """
        # 1. 检查师生关系
        result = self.check_teacher_student(expert, project)
        if result and result.avoided:
            return result
        
        # 2. 检查历史合作
        result = self.check_history_cooperation(expert, project)
        if result and result.avoided:
            return result
        
        # 3. 检查同一单位
        result = self.check_same_unit(expert, project)
        if result and result.severity == "high":
            return result
        
        return None
    
    def check_teacher_student(
        self,
        expert: Expert,
        project: Project
    ) -> AvoidanceInfo:
        """检测师生关系
        
        规则：专家的毕业院校与项目负责人的学位获取单位相同
        
        Args:
            expert: 专家
            project: 项目
        
        Returns:
            回避结果
        """
        # 简化实现：检查专家单位与项目单位是否相同
        # 实际应该检查：
        # - 专家毕业院校 vs 项目负责人学位获取单位
        # - 专家曾指导的学生 vs 项目负责人
        
        expert_unit = expert.gzdw or ""
        project_unit = project.cddw_mc or ""
        
        if expert_unit and project_unit:
            # 检查是否相同
            if self._is_similar(expert_unit, project_unit):
                return AvoidanceInfo(
                    avoided=True,
                    reason=f"疑似师生关系：专家单位 {expert_unit} 与项目单位 {project_unit} 相同",
                    severity="high"
                )
        
        return AvoidanceInfo(avoided=False, severity="none")
    
    def check_history_cooperation(
        self,
        expert: Expert,
        project: Project
    ) -> AvoidanceInfo:
        """检测历史合作关系
        
        规则：专家与项目负责人共同署名论文/项目
        
        Args:
            expert: 专家
            project: 项目
        
        Returns:
            回避结果
        """
        # 简化实现：暂不检测
        # 实际应该查询数据库：
        # - 论文共同署名记录
        # - 项目共同承担记录
        # - 专利共同申请人
        
        return AvoidanceInfo(avoided=False, severity="none")
    
    def check_same_unit(
        self,
        expert: Expert,
        project: Project
    ) -> AvoidanceInfo:
        """检测同一单位
        
        规则：专家所在单位与项目完成单位相同
        
        Args:
            expert: 专家
            project: 项目
        
        Returns:
            回避结果
        """
        expert_unit = expert.gzdw or ""
        project_unit = project.cddw_mc or ""
        
        if expert_unit and project_unit:
            if self._is_similar(expert_unit, project_unit):
                return AvoidanceInfo(
                    avoided=False,  # 不排除，但标记
                    reason=f"同一单位：{expert_unit}",
                    severity="high"
                )
        
        return AvoidanceInfo(avoided=False, severity="none")
    
    def _is_similar(self, str1: str, str2: str) -> bool:
        """判断两个字符串是否相似（同一单位）
        
        Args:
            str1: 字符串1
            str2: 字符串2
        
        Returns:
            是否相似
        """
        if not str1 or not str2:
            return False
        
        # 转换为小写
        s1 = str1.lower().strip()
        s2 = str2.lower().strip()
        
        # 完全相同
        if s1 == s2:
            return True
        
        # 一个包含另一个
        if s1 in s2 or s2 in s1:
            return True
        
        # 提取关键词比较
        keywords1 = set(self._extract_keywords(s1))
        keywords2 = set(self._extract_keywords(s2))
        
        # 有共同关键词
        common = keywords1 & keywords2
        if len(common) >= 2:
            return True
        
        return False
    
    def _extract_keywords(self, text: str) -> List[str]:
        """提取关键词
        
        Args:
            text: 文本
        
        Returns:
            关键词列表
        """
        # 移除常见词
        stopwords = {"大学", "学院", "研究院", "研究所", "公司", "企业", "有限", "股份"}
        
        # 按标点和空格分割
        import re
        words = re.split(r'[,，\s]+', text)
        
        # 过滤
        keywords = [w for w in words if w and w not in stopwords and len(w) > 1]
        
        return keywords
    
    def load_relations(
        self,
        teacher_student: Dict[str, Set[str]] = None,
        cooperation: Dict[str, Set[str]] = None
    ):
        """加载关系数据
        
        Args:
            teacher_student: 师生关系数据 {expert_id: {project_id, ...}}
            cooperation: 合作关系数据 {expert_id: {project_id, ...}}
        """
        if teacher_student:
            self._teacher_student_cache = teacher_student
        
        if cooperation:
            self._cooperation_cache = cooperation


class AvoidanceRule:
    """回避规则基类"""
    
    def check(self, expert: Expert, project: Project) -> Optional[AvoidanceInfo]:
        """检查是否需要回避
        
        Args:
            expert: 专家
            project: 项目
        
        Returns:
            回避信息
        """
        raise NotImplementedError


class UnitAvoidanceRule(AvoidanceRule):
    """单位回避规则"""
    
    def check(self, expert: Expert, project: Project) -> Optional[AvoidanceInfo]:
        """检查同一单位"""
        expert_unit = expert.gzdw or ""
        project_unit = project.cddw_mc or ""
        
        if expert_unit and project_unit:
            # 简单匹配
            if expert_unit == project_unit:
                return AvoidanceInfo(
                    avoided=True,
                    reason=f"同一单位：{expert_unit}",
                    severity="high"
                )
        
        return None


class SubjectAvoidanceRule(AvoidanceRule):
    """学科回避规则（可选）
    
    专家与项目学科完全不匹配时可以选择回避
    """
    
    def check(self, expert: Expert, project: Project) -> Optional[AvoidanceInfo]:
        """检查学科匹配度"""
        # 获取专家熟悉学科
        expert_subjects = []
        for i in range(1, 6):
            code = getattr(expert, f'sxxk{i}', None)
            if code:
                expert_subjects.append(code[:2])  # 取大类
        
        # 获取项目学科
        project_subjects = []
        if project.ssxk1:
            project_subjects.append(project.ssxk1[:2])
        if project.ssxk2:
            project_subjects.append(project.ssxk2[:2])
        
        # 检查是否有交集
        if expert_subjects and project_subjects:
            overlap = set(expert_subjects) & set(project_subjects)
            if not overlap:
                # 完全不匹配，标记为低优先级
                return AvoidanceInfo(
                    avoided=False,
                    reason="学科不匹配",
                    severity="low"
                )
        
        return None
