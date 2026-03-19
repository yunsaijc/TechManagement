"""
项目质量评估器

使用 LLM 评估项目的创新性、技术难度、应用价值
支持双重评估机制提升可靠性
"""
import re
from typing import Any, Dict, List, Optional, Tuple

from src.common.llm import get_default_llm_client
from src.common.models.grouping import Project, ProjectAnalysis, ProjectQuality
from src.services.grouping.config import grouping_settings

# 从配置读取常量
AUDIT_SAMPLE_THRESHOLD = grouping_settings.audit_sample_threshold  # 每50个建议抽一次
AUDIT_SAMPLE_SIZE = grouping_settings.audit_sample_size  # 抽5个
DUAL_EVAL_THRESHOLD = grouping_settings.dual_eval_threshold  # 差异阈值
MAX_EVAL_RETRY = grouping_settings.max_eval_retry  # 最大重试次数

# 模块级评估计数（用于触发人工复审提醒）
_eval_count = 0


class QualityAssessor:
    """项目质量评估器

    使用 LLM 评估项目的创新性、技术难度、应用价值
    支持双重评估机制提升可靠性
    """

    def __init__(self, llm: Any = None):
        """初始化

        Args:
            llm: LLM 客户端实例
        """
        self.llm = llm or get_default_llm_client()
        self._detail_cache: Dict[str, dict] = {}  # 详细分数缓存
        self._dual_eval_results: Dict[str, dict] = {}  # 双重评估结果缓存
    
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
        import asyncio
        
        # 构建评估文本
        text = self._build_assessment_text(project, project_analysis)
        
        # 构建 prompt
        prompt = self._build_assessment_prompt(text)
        
        # 调用 LLM (带超时)
        try:
            response = await asyncio.wait_for(self.llm.ainvoke(prompt), timeout=30.0)
            content = response.content if hasattr(response, 'content') else str(response)
        except asyncio.TimeoutError:
            content = '{"innovation_score": 50, "difficulty_score": 50, "value_score": 50, "total_score": 50}'
        
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
        
        for i, project in enumerate(projects):
            analysis = None
            if project_analyses:
                analysis = project_analyses.get(project.id)
            
            quality = await self.assess_quality(project, analysis)
            results[project.id] = quality
        
        return results
    
    async def batch_assess(
        self,
        projects: List[Project]
    ) -> Dict[str, float]:
        """批量评估项目质量（双重评估版本）

        优化：合并多个项目的评估到一次API调用
        双重评估：对每个项目用两个 prompt 评估，取平均或标记不稳定

        Args:
            projects: 项目列表

        Returns:
            项目ID -> 质量分数
        """
        global _eval_count

        if not projects:
            return {}

        # 构建 Prompt A（原始版本）
        prompt_a = "请评估以下项目的质量分数（0-100分），返回JSON数组：\n\n"
        for i, p in enumerate(projects):
            prompt_a += f"{i+1}. 项目名称: {p.xmmc}\n"
            if p.gjc:
                prompt_a += f"   关键词: {p.gjc}\n"
            if p.xmjj:
                clean = self._clean_html(p.xmjj)[:800]
                prompt_a += f"   简介: {clean}\n"
            prompt_a += "\n"
        prompt_a += """请按以下JSON格式返回（只需JSON数组，不要其他内容）：
[
  {"index": 1, "innovation": 80, "difficulty": 70, "value": 75, "total": 75,
   "comment": "综合评价，如'该项目总体质量较高，具备较好的发展潜力'",
   "innovation_comment": "简要评价创新性，如'技术路线具有原创性，在XX领域有突破'或'属于跟踪性研究，创新点不足'",
   "difficulty_comment": "简要评价技术难度，如'涉及多学科交叉，实现难度大'或'技术方案成熟，实施难度较低'",
   "value_comment": "简要评价应用价值，如'成果可直接转化应用，市场前景广阔'或'偏基础研究，实际应用尚需时日'"},
  ...
]"""

        # 构建 Prompt B（措辞略有差异）
        prompt_b = "请对以下项目进行质量评估（每项0-100分），返回JSON数组：\n\n"
        for i, p in enumerate(projects):
            prompt_b += f"{i+1}. 名称: {p.xmmc}\n"
            if p.gjc:
                prompt_b += f"   关键词: {p.gjc}\n"
            if p.xmjj:
                clean = self._clean_html(p.xmjj)[:800]
                prompt_b += f"   简介: {clean}\n"
            prompt_b += "\n"
        prompt_b += """按以下格式返回JSON数组（只输出JSON）：
[
  {"index": 1, "innovation": 80, "difficulty": 70, "value": 75, "total": 75,
   "comment": "综合评价",
   "innovation_comment": "创新性评语",
   "difficulty_comment": "难度评语",
   "value_comment": "价值评语"},
  ...
]"""

        # 调用 LLM（失败重试）
        import asyncio
        max_retries = 3
        for attempt in range(max_retries):
            try:
                response_a, response_b = await asyncio.gather(
                    asyncio.wait_for(self.llm.ainvoke(prompt_a), timeout=60.0),
                    asyncio.wait_for(self.llm.ainvoke(prompt_b), timeout=60.0)
                )
                content_a = response_a.content if hasattr(response_a, 'content') else str(response_a)
                content_b = response_b.content if hasattr(response_b, 'content') else str(response_b)
                break  # 成功，跳出重试循环
            except Exception as e:
                if attempt < max_retries - 1:
                    print(f"[Quality] 批量评估失败 (尝试 {attempt+1}/{max_retries}): {e}，重试...")
                    await asyncio.sleep(2)  # 等待2秒后重试
                else:
                    print(f"[Quality] 批量评估失败 (已重试 {max_retries} 次): {e}")
                    raise  # 最后一次也失败则抛出异常

        # 解析两次结果
        result_a = self._parse_batch_result(projects, content_a, "a")
        result_b = self._parse_batch_result(projects, content_b, "b")

        # 找出需要第三次评估的项目
        unstable_pids = []
        for p in projects:
            pid = p.id
            score_a = result_a.get(pid, 75.0)
            score_b = result_b.get(pid, 75.0)
            diff = abs(score_a - score_b)
            if diff > DUAL_EVAL_THRESHOLD:
                unstable_pids.append(pid)

        # 如果有不稳定的项目，进行第三次评估
        result_c = {}
        if unstable_pids and MAX_EVAL_RETRY > 0:
            unstable_projects = [p for p in projects if p.id in unstable_pids]
            prompt_c = "请对以下科研项目进行质量评估（0-100分制），返回JSON数组：\n\n"
            for i, p in enumerate(unstable_projects):
                prompt_c += f"{i+1}. 项目名称: {p.xmmc}\n"
                if p.gjc:
                    prompt_c += f"   关键词: {p.gjc}\n"
                if p.xmjj:
                    clean = self._clean_html(p.xmjj)[:800]
                    prompt_c += f"   简介: {clean}\n"
                prompt_c += "\n"
            prompt_c += """请按以下JSON格式返回（只需JSON数组，不要其他内容）：
[
  {"index": 1, "innovation": 80, "difficulty": 70, "value": 75, "total": 75,
   "comment": "综合评价，如'该项目总体质量较高，具备较好的发展潜力'",
   "innovation_comment": "简要评价创新性，如'技术路线具有原创性，在XX领域有突破'或'属于跟踪性研究，创新点不足'",
   "difficulty_comment": "简要评价技术难度，如'涉及多学科交叉，实现难度大'或'技术方案成熟，实施难度较低'",
   "value_comment": "简要评价应用价值，如'成果可直接转化应用，市场前景广阔'或'偏基础研究，实际应用尚需时日'"},
  ...
]"""
            try:
                response_c = await asyncio.wait_for(self.llm.ainvoke(prompt_c), timeout=60.0)
                content_c = response_c.content if hasattr(response_c, 'content') else str(response_c)
                result_c = self._parse_batch_result(unstable_projects, content_c, "c")
                print(f"[Quality] 第三次评估完成: {len(result_c)} 个不稳定项目")
            except Exception as e:
                print(f"[Quality] 第三次评估失败: {e}")

        # 处理所有项目
        final_result = {}
        for p in projects:
            pid = p.id
            score_a = result_a.get(pid, 75.0)
            score_b = result_b.get(pid, 75.0)
            diff = abs(score_a - score_b)

            # 确定最终分数和 need_review 标记
            need_review = False
            if pid in unstable_pids and result_c:
                score_c = result_c.get(pid, 75.0)
                mean_ab = (score_a + score_b) / 2
                diff_c = abs(score_c - mean_ab)

                # C 验证 A/B 共识是否稳定
                if diff_c <= DUAL_EVAL_THRESHOLD:
                    # C 与 A/B 共识一致，三次平均
                    final_score = (score_a + score_b + score_c) / 3
                else:
                    # 三次评估太分散，以 A/B 共识为准，标记待复审
                    final_score = mean_ab
                    need_review = True
                    print(f"[Quality] 警告: 项目 {pid} 三次评估差异较大 (C与均值差{diff_c:.1f}分)，标记待复审")
            else:
                final_score = (score_a + score_b) / 2
                if diff > DUAL_EVAL_THRESHOLD:
                    print(f"[Quality] 警告: 项目 {pid} 双重评估差异较大 ({diff:.1f}分)")

            final_result[pid] = round(final_score, 2)

            # 更新计数
            _eval_count += 1

            # 保存结果到 _detail_cache
            detail_a = self._detail_cache.get(f"_batch_a_{pid}", {})
            detail_b = self._detail_cache.get(f"_batch_b_{pid}", {})
            detail_c = self._detail_cache.get(f"_batch_c_{pid}", {}) if pid in unstable_pids else {}

            self._detail_cache[pid] = {
                "total": final_score,
                "innovation": (detail_a.get('innovation', score_a) + detail_b.get('innovation', score_a)) / 2,
                "difficulty": (detail_a.get('difficulty', score_a) + detail_b.get('difficulty', score_a)) / 2,
                "value": (detail_a.get('value', score_a) + detail_b.get('value', score_a)) / 2,
                # 双重评估完整结果
                "result_a": detail_a,
                "result_b": detail_b,
                "result_c": detail_c,
                "diff": diff,
                "need_review": need_review
            }

        return final_result

    def _parse_batch_result(self, projects: List[Project], content: str, batch_id: str = "a") -> Dict[str, float]:
        """解析批量评估结果

        Args:
            projects: 项目列表
            content: LLM 返回内容
            batch_id: 批次标识 "a" 或 "b"

        Returns:
            {project_id: total_score}
        """
        try:
            import json
            start = content.find('[')
            end = content.rfind(']') + 1
            if start >= 0 and end > start:
                arr = json.loads(content[start:end])
                result = {}
                for item in arr:
                    idx = item.get('index', 1) - 1
                    if 0 <= idx < len(projects):
                        pid = projects[idx].id
                        total = float(item.get('total', 75))
                        result[pid] = total
                        # 保存完整结果到 _detail_cache（带前缀标记来源A或B）
                        cache_key = f"_batch_{batch_id}_{pid}"
                        if hasattr(self, '_detail_cache'):
                            self._detail_cache[cache_key] = {
                                "total": total,
                                "innovation": float(item.get('innovation', total)),
                                "difficulty": float(item.get('difficulty', total)),
                                "value": float(item.get('value', total)),
                                "comment": item.get('comment', ''),  # LLM 生成的综合评语
                                "innovation_comment": item.get('innovation_comment', ''),
                                "difficulty_comment": item.get('difficulty_comment', ''),
                                "value_comment": item.get('value_comment', '')
                            }
                return result
        except:
            pass
        return {p.id: 75.0 for p in projects}
    
    async def assess_single(self, project: Project) -> float:
        """评估单个项目，返回分数（双重评估版本）

        简化版，直接返回综合分数
        使用双重评估提升可靠性：两次独立评估取平均

        Args:
            project: 项目

        Returns:
            质量分数 (0-100)
        """
        global _eval_count

        # 构建评估文本
        clean_xmjj = self._clean_html(project.xmjj)[:1000] if project.xmjj else ""

        # Prompt A（原始版本）
        prompt_a = f"""项目名称: {project.xmmc}
关键词: {project.gjc or '无'}
项目简介: {clean_xmjj}

请从以下三个维度评估该项目质量（每个维度0-100分）：
1. 创新性: 项目的创新程度
2. 技术难度: 技术实现的复杂程度
3. 应用价值: 实际应用和推广价值

请返回JSON格式：
{{"innovation": 85, "difficulty": 70, "value": 90, "comment": "简要评语"}}
只需返回JSON，不要其他内容。"""

        # Prompt B（措辞略有差异的复本）
        prompt_b = f"""请对以下项目进行质量评估：

项目名称：{project.xmmc}
关键词：{project.gjc or '无'}
项目简介：{clean_xmjj}

评估维度（各维度0-100分）：
- 创新程度
- 技术复杂性
- 应用前景

请以JSON格式输出评估结果：
{{"innovation": 80, "difficulty": 75, "value": 85, "comment": "评语"}}
只输出JSON。"""

        score_a, detail_a = await self._do_eval(project.id, prompt_a)
        score_b, detail_b = await self._do_eval(project.id, prompt_b)

        # 计算差异
        diff = abs(score_a - score_b)

        # 保存双重评估结果
        self._dual_eval_results[project.id] = {
            "score_a": score_a,
            "score_b": score_b,
            "diff": diff,
            "is_stable": diff <= DUAL_EVAL_THRESHOLD
        }

        # 计算最终分数：始终取平均
        final_score = (score_a + score_b) / 2
        if diff > DUAL_EVAL_THRESHOLD:
            print(f"[Quality] 警告: 项目 {project.id} 双重评估差异较大 ({diff:.1f}分)")

        # 更新计数
        _eval_count += 1

        # 同时更新 _detail_cache（用于缓存持久化）
        self._detail_cache[project.id] = {
            "total": final_score,
            "innovation": (detail_a.get('innovation', score_a) + detail_b.get('innovation', score_a)) / 2,
            "difficulty": (detail_a.get('difficulty', score_a) + detail_b.get('difficulty', score_a)) / 2,
            "value": (detail_a.get('value', score_a) + detail_b.get('value', score_a)) / 2,
            # 双重评估完整结果
            "result_a": detail_a,
            "result_b": detail_b,
            "diff": diff
        }

        return round(final_score, 2)

    async def _do_eval(self, project_id: str, prompt: str) -> Tuple[float, dict]:
        """执行一次评估

        Args:
            project_id: 项目ID
            prompt: 评估prompt

        Returns:
            (总分, 详细结果dict)
        """
        try:
            import asyncio
            response = await asyncio.wait_for(self.llm.ainvoke(prompt), timeout=30.0)
            content = response.content if hasattr(response, 'content') else str(response)
        except Exception as e:
            print(f"[Quality] 评估失败: {project_id}, {e}")
            return 75.0, {}

        # 解析 JSON
        try:
            import json
            start = content.find('{')
            end = content.rfind('}') + 1
            if start >= 0 and end > start:
                data = json.loads(content[start:end])
                innovation = data.get('innovation', 75)
                difficulty = data.get('difficulty', 75)
                value = data.get('value', 75)
                total = (innovation + difficulty + value) / 3
                return round(total, 2), data
        except Exception as e:
            print(f"[Quality] 解析失败: {project_id}, {e}")

        return 75.0, {}
    
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
