"""评审智能体

正文评审服务的统一编排器，融合九维评审、划重点、产业贴合、技术摸底与聊天索引。
"""
import asyncio
import inspect
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.common.llm import get_default_llm_client
from src.common.models.evaluation import (
    BenchmarkResult,
    CheckResult,
    EvaluationChatAskResponse,
    EvaluationError,
    GuideEvaluationRequest,
    GuideEvaluationResult,
    EvaluationRequest,
    EvaluationResult,
    IndustryFitResult,
    StructuredHighlights,
)

from .benchmark import BenchmarkAnalyzer, BenchmarkRetriever
from .checkers import (
    BaseChecker,
    ComplianceChecker,
    EconomicBenefitChecker,
    FeasibilityChecker,
    InnovationChecker,
    OutcomeChecker,
    RiskControlChecker,
    ScheduleChecker,
    SocialBenefitChecker,
    TeamChecker,
)
from .config import EvaluationConfig, evaluation_config
from .chat import ChatIndexer, EvaluationQAAgent
from .highlight import HighlightExtractor, IndustryFitAnalyzer
from .parsers import DocumentParser
from .packet_builder import EvaluationPacketBuilder
from .profile import PROFILE_GENERIC, ProjectProfileResult, ProjectProfiler
from .scorers import EvaluationScorer, ReportGenerator
from .storage import EvaluationProjectRepository, EvaluationStorage
from .tools import ToolGateway, ToolUnavailableError


class EvaluationAgent:
    """正文评审编排器"""

    EXPERT_QA_QUESTIONS = [
        "这个项目的研究目标是什么？",
        "这个项目的创新点是什么？",
        "申报书里有验证数据吗？",
        "这项工作目前进展到什么程度了？",
        "这项技术有可能落地或量产吗？",
        "这个项目的预期成果和效益是什么？",
    ]

    DIMENSION_CHECKERS = {
        "feasibility": FeasibilityChecker,
        "innovation": InnovationChecker,
        "team": TeamChecker,
        "outcome": OutcomeChecker,
        "social_benefit": SocialBenefitChecker,
        "economic_benefit": EconomicBenefitChecker,
        "risk_control": RiskControlChecker,
        "schedule": ScheduleChecker,
        "compliance": ComplianceChecker,
    }

    def __init__(self, config: Optional[EvaluationConfig] = None, llm: Optional[Any] = None):
        self.config = config or evaluation_config
        self.llm = llm or get_default_llm_client()

        self.parser = DocumentParser()
        self.scorer = EvaluationScorer()
        self.report_generator = ReportGenerator()
        self.storage = EvaluationStorage()
        self.project_repo = EvaluationProjectRepository()
        self.packet_builder = EvaluationPacketBuilder()

        self.tool_gateway = ToolGateway()
        self.highlight_extractor = HighlightExtractor()
        self.industry_fit_analyzer = IndustryFitAnalyzer(self.tool_gateway)
        self.benchmark_analyzer = BenchmarkAnalyzer(BenchmarkRetriever(self.tool_gateway))
        self.chat_indexer = ChatIndexer()
        self.qa_agent = EvaluationQAAgent(llm=self.llm, indexer=self.chat_indexer)
        self.project_profiler = ProjectProfiler()
        self._task_semaphore = asyncio.Semaphore(max(1, self.config.concurrency))

    def get_checker(
        self,
        dimension: str,
        profile_result: Optional[ProjectProfileResult] = None,
    ) -> Optional[BaseChecker]:
        """获取指定维度检查器"""
        checker_class = self.DIMENSION_CHECKERS.get(dimension)
        if not checker_class:
            return None

        overrides = {}
        project_profile = PROFILE_GENERIC
        if profile_result:
            project_profile = profile_result.project_profile
            overrides = profile_result.dimension_overrides.get(dimension, {})

        return checker_class(
            llm=self.llm,
            project_profile=project_profile,
            dimension_overrides=overrides,
        )

    async def evaluate(
        self,
        request: EvaluationRequest,
        file_path: Optional[str] = None,
        content: Optional[Dict[str, Any]] = None,
        source_name: str = "",
    ) -> EvaluationResult:
        """执行融合评审"""
        parsed = await self._prepare_content(file_path=file_path, content=content, source_name=source_name)
        sections = parsed.get("sections", {})
        page_chunks = parsed.get("page_chunks", [])
        meta = parsed.get("meta", {})

        if request.include_sections:
            sections = self._filter_sections(sections, request.include_sections)

        profile_result = self.project_profiler.infer(sections)
        meta["project_profile"] = profile_result.as_dict()

        dimensions = request.get_dimensions()
        weights = request.weights or self.config.default_weights
        valid, message, normalized_weights = self.config.validate_weights(weights)
        if not valid:
            raise ValueError(f"权重验证失败: {message}")

        evaluation_id = self._generate_evaluation_id(request.project_id)
        module_outputs, module_errors, partial = await self._run_modules(
            request=request,
            sections=sections,
            page_chunks=page_chunks,
            meta=meta,
            dimensions=dimensions,
            evaluation_id=evaluation_id,
            profile_result=profile_result,
        )

        check_results = module_outputs.get("checks", [])
        result = self.scorer.build_result(
            project_id=request.project_id,
            project_name=sections.get("项目名称") or meta.get("file_name") or None,
            check_results=check_results,
            weights=normalized_weights,
        )

        result.evaluation_id = evaluation_id
        result.partial = partial
        result.errors = module_errors

        if "highlights" in module_outputs:
            result.highlights = module_outputs["highlights"]
        if "industry_fit" in module_outputs:
            result.industry_fit = module_outputs["industry_fit"]
        if "benchmark" in module_outputs:
            result.benchmark = module_outputs["benchmark"]

        result.evidence = self._merge_evidence(module_outputs)
        result.chat_ready = bool(module_outputs.get("chat_ready", False))

        await self.storage.save(result)
        debug_task = self._save_debug_artifacts(
            result=result,
            sections=sections,
            meta=meta,
            source_name=source_name,
            page_chunks=page_chunks,
        )
        if inspect.isawaitable(debug_task):
            await debug_task
        return result

    async def evaluate_by_project(self, request: EvaluationRequest) -> EvaluationResult:
        """按项目 ID 执行评审"""
        project_info = self.project_repo.get_project_info(request.project_id)
        if not project_info:
            raise ValueError(f"项目不存在: {request.project_id}")

        file_path = self.project_repo.get_primary_document_path(request.project_id)
        if not file_path:
            expected_path = self.project_repo.get_expected_document_path(request.project_id)
            raise ValueError(
                f"未找到项目申报文档: {request.project_id}。"
                f"当前按真实路径规则查找: {expected_path or '无法根据 year 推断路径'}"
            )

        parsed = await self.parser.parse(file_path, source_name=os.path.basename(file_path))
        sections = parsed.get("sections", {})
        sections.setdefault("项目名称", project_info.get("xmmc", ""))
        sections.setdefault("项目简介", project_info.get("xmjj", ""))
        parsed["sections"] = sections
        parsed_meta = parsed.get("meta") or {}
        parsed_meta["attachment_files"] = self.project_repo.get_attachment_file_paths(request.project_id)
        parsed["meta"] = parsed_meta

        return await self.evaluate(
            request=request,
            file_path=file_path,
            content=parsed,
            source_name=os.path.basename(file_path),
        )

    async def evaluate_by_guide(self, request: GuideEvaluationRequest) -> GuideEvaluationResult:
        """按指南代码批量执行评审"""
        projects = self.project_repo.get_projects_by_guide_code(request.zndm, limit=request.limit)
        if not projects:
            raise ValueError(f"未找到已提交项目: {request.zndm}")

        semaphore = asyncio.Semaphore(max(1, request.concurrency))
        results: List[EvaluationResult] = []
        errors: List[Dict[str, Any]] = []

        async def evaluate_one(project: Dict[str, str]) -> None:
            async with semaphore:
                project_id = str(project.get("id") or "").strip()
                if not project_id:
                    raise ValueError("项目记录缺少 id")

                eval_request = EvaluationRequest(
                    project_id=project_id,
                    dimensions=request.dimensions,
                    weights=request.weights,
                    include_sections=request.include_sections,
                    enable_highlight=request.enable_highlight,
                    enable_industry_fit=request.enable_industry_fit,
                    enable_benchmark=request.enable_benchmark,
                    enable_chat_index=request.enable_chat_index,
                )
                result = await self.evaluate_by_project(eval_request)
                results.append(result)

        raw_results = await asyncio.gather(
            *(evaluate_one(project) for project in projects),
            return_exceptions=True,
        )

        for project, item in zip(projects, raw_results):
            if isinstance(item, Exception):
                errors.append(
                    {
                        "project_id": project.get("id"),
                        "project_name": project.get("xmmc"),
                        "error": str(item),
                    }
                )

        return GuideEvaluationResult(
            zndm=request.zndm,
            guide_name=projects[0].get("guide_name") or None,
            total=len(projects),
            success=len(results),
            failed=len(errors),
            results=results,
            errors=errors,
        )

    async def ask(self, evaluation_id: str, question: str) -> EvaluationChatAskResponse:
        """基于历史评审记录进行问答"""
        result = await self.storage.get_by_evaluation_id(evaluation_id)
        if not result:
            raise ValueError(f"评审记录不存在: {evaluation_id}")

        index_payload = await self.storage.load_chat_index(evaluation_id)
        if not index_payload or not index_payload.get("chunk_count"):
            rebuilt = await self._try_rebuild_chat_index(evaluation_id=evaluation_id, result=result)
            if rebuilt:
                index_payload = await self.storage.load_chat_index(evaluation_id)

        if not index_payload or not index_payload.get("chunk_count"):
            raise ValueError("该评审记录未构建聊天索引，且无法自动重建。请重新评审并启用 enable_chat_index")

        return await self.qa_agent.ask(question=question, index_payload=index_payload)

    async def _try_rebuild_chat_index(self, evaluation_id: str, result: EvaluationResult) -> bool:
        """尝试基于调试产物或原始文档重建聊天索引"""
        debug_payload = self._load_debug_payload(result.project_id)
        page_chunks = self._extract_debug_page_chunks(debug_payload, evaluation_id)
        if not page_chunks:
            source_path = self._resolve_source_document_path(result.project_id, debug_payload)
            if source_path:
                parsed = await self.parser.parse(source_path, source_name=os.path.basename(source_path))
                page_chunks = parsed.get("page_chunks", [])

        if not page_chunks:
            return False

        payload = self.chat_indexer.build(evaluation_id=evaluation_id, page_chunks=page_chunks)
        if not payload.get("chunk_count"):
            return False

        await self.storage.save_chat_index(evaluation_id=evaluation_id, payload=payload)
        await self.storage.set_chat_ready(evaluation_id=evaluation_id, chat_ready=True)
        return True

    def _load_debug_payload(self, project_id: str) -> Optional[Dict[str, Any]]:
        """读取项目对应的 debug_eval JSON"""
        debug_path = Path("debug_eval") / f"EVAL_{project_id}.json"
        if not debug_path.exists():
            return None
        try:
            payload = json.loads(debug_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

    def _extract_debug_page_chunks(
        self,
        debug_payload: Optional[Dict[str, Any]],
        evaluation_id: str,
    ) -> List[Dict[str, Any]]:
        """从调试产物中提取可复用页切片"""
        if not debug_payload:
            return []
        debug_eval_id = str(debug_payload.get("evaluation_id") or "")
        if debug_eval_id and debug_eval_id != evaluation_id:
            return []
        page_chunks = debug_payload.get("page_chunks")
        if not isinstance(page_chunks, list):
            return []
        return [chunk for chunk in page_chunks if isinstance(chunk, dict)]

    def _resolve_source_document_path(
        self,
        project_id: str,
        debug_payload: Optional[Dict[str, Any]],
    ) -> Optional[str]:
        """按优先级解析可用于重建索引的源文档路径"""
        candidates: List[str] = []

        if debug_payload:
            meta = debug_payload.get("meta")
            if isinstance(meta, dict):
                debug_file_path = str(meta.get("file_path") or "").strip()
                if debug_file_path:
                    candidates.append(debug_file_path)

        try:
            project_doc = self.project_repo.get_primary_document_path(project_id)
        except Exception:
            project_doc = None
        if project_doc:
            candidates.append(project_doc)

        for path in candidates:
            if path and os.path.exists(path):
                return path
        return None

    async def _prepare_content(
        self,
        file_path: Optional[str],
        content: Optional[Dict[str, Any]],
        source_name: str,
    ) -> Dict[str, Any]:
        """归一化解析内容结构"""
        if content is None:
            if file_path is None:
                raise ValueError("必须提供 file_path 或 content 参数")
            return await self.parser.parse(file_path, source_name=source_name)

        if "sections" in content:
            return content

        # 兼容旧结构：content 直接为章节字典
        return {
            "sections": content,
            "page_chunks": [],
            "meta": {"file_name": source_name or ""},
        }

    async def _run_modules(
        self,
        request: EvaluationRequest,
        sections: Dict[str, str],
        page_chunks: List[Dict[str, Any]],
        meta: Dict[str, Any],
        dimensions: List[str],
        evaluation_id: str,
        profile_result: ProjectProfileResult,
    ) -> tuple[Dict[str, Any], List[EvaluationError], bool]:
        """并发执行评审与增强模块"""
        outputs: Dict[str, Any] = {}
        errors: List[EvaluationError] = []
        partial = False

        module_tasks: Dict[str, asyncio.Task] = {
            "checks": asyncio.create_task(self._run_task(self._run_checks(sections, dimensions, profile_result))),
        }

        if request.enable_highlight:
            module_tasks["highlight"] = asyncio.create_task(
                self._run_task(self._run_highlight(sections, page_chunks, meta))
            )

        if request.enable_industry_fit:
            module_tasks["industry_fit"] = asyncio.create_task(
                self._run_task(self._run_industry_fit(sections, page_chunks))
            )

        if request.enable_benchmark:
            module_tasks["benchmark"] = asyncio.create_task(
                self._run_task(self._run_benchmark(sections))
            )

        if request.enable_chat_index:
            module_tasks["chat_index"] = asyncio.create_task(
                self._run_task(self._run_chat_index(evaluation_id, page_chunks))
            )

        results = await asyncio.gather(*module_tasks.values(), return_exceptions=True)

        for name, module_result in zip(module_tasks.keys(), results):
            if isinstance(module_result, Exception):
                partial = True
                errors.append(self._build_module_error(name, module_result))
                if name == "checks":
                    outputs["checks"] = self._build_default_checks(dimensions)
                if name == "highlight":
                    outputs["highlights"] = StructuredHighlights()
                if name == "industry_fit":
                    outputs["industry_fit"] = IndustryFitResult(
                        fit_score=0.0,
                        matched=[],
                        gaps=["产业指南检索不可用，结果待核验"],
                        suggestions=["待检索工具恢复后补充指南映射"],
                    )
                if name == "benchmark":
                    outputs["benchmark"] = BenchmarkResult(
                        novelty_level="unknown",
                        literature_position="技术摸底工具不可用",
                        patent_overlap="技术摸底工具不可用",
                        conclusion="当前仅基于申报书内容，外部对比结论待补充",
                        references=[],
                    )
                if name == "chat_index":
                    outputs["chat_ready"] = False
                continue

            if name == "checks":
                outputs["checks"] = module_result
            if name == "highlight":
                outputs["highlights"] = module_result["highlights"]
                outputs["evidence_highlight"] = module_result["evidence"]
            if name == "industry_fit":
                outputs["industry_fit"] = module_result["industry_fit"]
                outputs["evidence_industry"] = module_result["evidence"]
            if name == "benchmark":
                outputs["benchmark"] = module_result["benchmark"]
                outputs["evidence_benchmark"] = module_result["evidence"]
            if name == "chat_index":
                outputs["chat_ready"] = module_result["chat_ready"]

        return outputs, errors, partial

    async def _run_task(self, coro):
        """统一并发与超时控制"""
        async with self._task_semaphore:
            return await asyncio.wait_for(coro, timeout=self.config.timeout)

    async def _run_checks(
        self,
        sections: Dict[str, str],
        dimensions: List[str],
        profile_result: ProjectProfileResult,
    ) -> List[CheckResult]:
        """并行执行维度检查"""
        task_specs: List[tuple[str, asyncio.Task]] = []
        results: List[CheckResult] = []
        checker_content = dict(sections)
        checker_content["_project_profile"] = profile_result.project_profile

        for dimension in dimensions:
            checker = self.get_checker(dimension, profile_result)
            if not checker:
                results.append(
                    CheckResult(
                        dimension=dimension,
                        score=5.0,
                        confidence=0.0,
                        opinion=f"未找到对应检查器: {dimension}",
                        issues=["检查器未配置"],
                        highlights=[],
                        items=[],
                    )
                )
                continue
            task_specs.append((dimension, asyncio.create_task(self._safe_check(checker, checker_content))))

        if task_specs:
            raw = await asyncio.gather(*[task for _, task in task_specs], return_exceptions=True)
            for (dimension, _), item in zip(task_specs, raw):
                if isinstance(item, Exception):
                    checker = self.get_checker(dimension, profile_result)
                    if checker:
                        results.append(checker.build_degraded_result(checker_content, str(item)))
                    else:
                        results.append(
                            CheckResult(
                                dimension=dimension,
                                score=5.0,
                                confidence=0.0,
                                opinion=f"检查异常: {str(item)}",
                                issues=["检查过程发生错误"],
                                highlights=[],
                                items=[],
                            )
                        )
                else:
                    results.append(item)

        return results

    async def _run_highlight(
        self,
        sections: Dict[str, str],
        page_chunks: List[Dict[str, Any]],
        meta: Dict[str, Any],
    ) -> Dict[str, Any]:
        """执行划重点"""
        highlights, evidence = await self.highlight_extractor.extract(
            sections=sections,
            page_chunks=page_chunks,
            file_name=str(meta.get("file_name", "")),
        )
        return {"highlights": highlights, "evidence": evidence}

    async def _run_industry_fit(
        self,
        sections: Dict[str, str],
        page_chunks: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """执行产业贴合分析"""
        query_text = "\n".join(
            [
                sections.get("研究目标", ""),
                sections.get("创新点", ""),
                sections.get("技术路线", ""),
            ]
        ).strip()

        industry_fit, evidence = await self.industry_fit_analyzer.analyze(
            sections=sections,
            page_chunks=page_chunks,
            query_text=query_text,
        )
        return {"industry_fit": industry_fit, "evidence": evidence}

    async def _run_benchmark(self, sections: Dict[str, str]) -> Dict[str, Any]:
        """执行技术摸底"""
        benchmark, evidence = await self.benchmark_analyzer.analyze(
            sections=sections,
            highlights=None,
        )
        return {"benchmark": benchmark, "evidence": evidence}

    async def _run_chat_index(self, evaluation_id: str, page_chunks: List[Dict[str, Any]]) -> Dict[str, Any]:
        """构建并保存聊天索引"""
        if not page_chunks:
            return {"chat_ready": False}

        payload = self.chat_indexer.build(evaluation_id=evaluation_id, page_chunks=page_chunks)
        await self.storage.save_chat_index(evaluation_id=evaluation_id, payload=payload)
        return {"chat_ready": bool(payload.get("chunk_count", 0) > 0)}

    async def _safe_check(self, checker: BaseChecker, content: Dict[str, Any]) -> CheckResult:
        """安全执行检查"""
        try:
            result = await checker.check(content)
            if self._should_degrade_check_result(result):
                return checker.build_degraded_result(content, result.opinion)
            return result
        except Exception as e:
            return checker.build_degraded_result(content, str(e))

    def _should_degrade_check_result(self, result: CheckResult) -> bool:
        """识别需要降级替换的检查结果"""
        opinion = result.opinion or ""
        issue_text = " ".join(result.issues or [])
        return any(
            marker in opinion or marker in issue_text
            for marker in ("检查异常", "评审解析失败", "Request timed out", "Connection error")
        )

    def _filter_sections(self, sections: Dict[str, Any], include_sections: List[str]) -> Dict[str, Any]:
        """按 include_sections 过滤章节"""
        normalized = [item.strip() for item in include_sections if item.strip()]
        if not normalized:
            return sections

        filtered: Dict[str, Any] = {}
        for section in normalized:
            for key, value in sections.items():
                if key in ("项目名称", "项目简介"):
                    continue
                if key == section or section in key or key in section:
                    filtered[key] = value

        if "项目名称" in sections:
            filtered["项目名称"] = sections["项目名称"]
        if "项目简介" in sections:
            filtered["项目简介"] = sections["项目简介"]

        return filtered or sections

    def _merge_evidence(self, outputs: Dict[str, Any]) -> List:
        """合并并去重证据"""
        merged = []
        seen = set()

        for key in ("evidence_highlight", "evidence_industry", "evidence_benchmark"):
            for item in outputs.get(key, []):
                unique_key = (item.source, item.file, item.page, item.snippet)
                if unique_key in seen:
                    continue
                seen.add(unique_key)
                merged.append(item)

        return merged

    async def _save_debug_artifacts(
        self,
        result: EvaluationResult,
        sections: Dict[str, str],
        meta: Dict[str, Any],
        source_name: str,
        page_chunks: List[Dict[str, Any]],
    ) -> None:
        """保存评审调试产物到 debug_eval 目录"""
        debug_dir = Path("debug_eval")
        debug_dir.mkdir(exist_ok=True)

        stem = f"EVAL_{result.project_id}"
        json_path = debug_dir / f"{stem}.json"
        html_path = debug_dir / f"{stem}.html"
        debug_html_path = debug_dir / f"{stem}.debug.html"
        expert_qna = await self._build_expert_qna(
            evaluation_id=result.evaluation_id or stem,
            page_chunks=page_chunks,
        )
        attachment_files = meta.get("attachment_files") or []
        attachments = [
            {
                "file_ref": str(path),
                "file_name": Path(str(path)).name,
                "doc_kind": "",
            }
            for path in attachment_files
            if str(path).strip()
        ]
        packet_assets = self.packet_builder.build(
            output_dir=debug_dir,
            project_id=result.project_id,
            source_file=str(meta.get("file_path") or ""),
            source_name=source_name or meta.get("file_name") or "",
            attachments=attachments,
        )

        debug_payload = {
            "evaluation_id": result.evaluation_id,
            "project_id": result.project_id,
            "project_name": result.project_name,
            "source_name": source_name or meta.get("file_name") or "",
            "meta": meta,
            "section_names": list(sections.keys()),
            "sections": sections,
            "page_chunks": page_chunks,
            "attachments": attachments,
            "packet_assets": packet_assets,
            "expert_qna": expert_qna,
            "result": result.model_dump(mode="json"),
        }

        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(debug_payload, f, ensure_ascii=False, indent=2)

        self.report_generator.build_from_debug_file(json_path, html_path, debug_mode=False)
        self.report_generator.build_from_debug_file(json_path, debug_html_path, debug_mode=True)
        self._refresh_debug_index(debug_dir)

    async def _build_expert_qna(
        self,
        evaluation_id: str,
        page_chunks: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """生成用于报告展示的专家典型问答"""
        if not page_chunks:
            return []

        index_payload = self.chat_indexer.build(evaluation_id=evaluation_id, page_chunks=page_chunks)
        if not index_payload.get("chunk_count"):
            return []

        # 报告内典型问答优先使用实际 LLM，失败时由 QAAgent 内部降级到规则回答
        report_qa_agent = EvaluationQAAgent(llm=self.llm, indexer=self.chat_indexer)

        async def ask_one(question: str) -> Dict[str, Any]:
            try:
                response = await report_qa_agent.ask(question=question, index_payload=index_payload)
            except Exception as exc:
                return {
                    "question": question,
                    "answer": f"当前未能生成该问题回答：{str(exc)}",
                    "citations": [],
                }
            return {
                "question": question,
                "answer": response.answer,
                "citations": [citation.model_dump(mode="json") for citation in response.citations],
            }

        return await asyncio.gather(*(ask_one(question) for question in self.EXPERT_QA_QUESTIONS))

    def _refresh_debug_index(self, debug_dir: Path) -> None:
        """刷新 debug_eval 索引页"""
        records: List[Dict[str, Any]] = []
        for path in sorted(debug_dir.glob("EVAL_*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(payload, dict):
                continue

            result = payload.get("result") or {}
            if not isinstance(result, dict):
                continue
            records.append(
                {
                    "created_at": result.get("created_at"),
                    "project_id": result.get("project_id"),
                    "project_name": result.get("project_name"),
                    "source_name": payload.get("source_name"),
                    "overall_score": result.get("overall_score"),
                    "grade": result.get("grade"),
                    "partial": result.get("partial"),
                    "html_file": f"{path.stem}.html",
                    "debug_html_file": f"{path.stem}.debug.html",
                    "json_file": path.name,
                    "payload": payload,
                }
            )

        index_html = self.report_generator.build_index_html(records)
        (debug_dir / "index.html").write_text(index_html, encoding="utf-8")

    def _build_module_error(self, module: str, exc: Exception) -> EvaluationError:
        """构建模块错误对象"""
        if isinstance(exc, ToolUnavailableError):
            code = "TOOL_UNAVAILABLE"
        elif isinstance(exc, asyncio.TimeoutError):
            code = "TASK_TIMEOUT"
        else:
            code = "INTERNAL_ERROR"

        return EvaluationError(code=code, message=str(exc), module=module)

    def _build_default_checks(self, dimensions: List[str]) -> List[CheckResult]:
        """构建默认检查结果"""
        defaults: List[CheckResult] = []
        for dimension in dimensions:
            defaults.append(
                CheckResult(
                    dimension=dimension,
                    score=5.0,
                    confidence=0.0,
                    opinion="检查未执行，已降级为默认分",
                    issues=["检查模块异常"],
                    highlights=[],
                    items=[],
                )
            )
        return defaults

    def _generate_evaluation_id(self, project_id: str) -> str:
        """生成评审记录ID"""
        now = datetime.now().strftime("%Y%m%d%H%M%S%f")
        return f"EVAL_{project_id}_{now}"

    async def get_dimension_info(self, dimension: str) -> Optional[Dict[str, Any]]:
        """获取维度信息"""
        config = self.config.get_dimension_config(dimension)
        if not config:
            return None

        return {
            "code": config.code,
            "name": config.name,
            "category": config.category,
            "description": config.description,
            "default_weight": config.default_weight,
            "check_items": config.check_items,
            "required_sections": config.required_sections,
        }

    async def list_dimensions(self) -> List[Dict[str, Any]]:
        """列出所有维度"""
        dimensions = []
        for _, config in self.config.dimensions.items():
            if not config.enabled:
                continue
            dimensions.append(
                {
                    "code": config.code,
                    "name": config.name,
                    "category": config.category,
                    "description": config.description,
                    "default_weight": config.default_weight,
                    "check_items": config.check_items,
                    "required_sections": config.required_sections,
                }
            )

        return dimensions

    async def get_evaluation_history(self, project_id: str) -> List[EvaluationResult]:
        """获取评审历史"""
        return await self.storage.list_by_project(project_id)

    async def batch_evaluate(
        self,
        requests: List[EvaluationRequest],
        file_paths: Optional[Dict[str, str]] = None,
        concurrency: int = 3,
    ) -> List[EvaluationResult]:
        """批量评审"""
        semaphore = asyncio.Semaphore(concurrency)

        async def _evaluate_with_semaphore(request: EvaluationRequest):
            async with semaphore:
                file_path = file_paths.get(request.project_id) if file_paths else None
                if file_path:
                    return await self.evaluate(request, file_path=file_path)
                return await self.evaluate_by_project(request)

        tasks = [_evaluate_with_semaphore(req) for req in requests]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        final_results = []
        for result in results:
            if isinstance(result, Exception):
                final_results.append(
                    EvaluationResult(
                        project_id="unknown",
                        overall_score=0,
                        grade="E",
                        dimension_scores=[],
                        summary=f"评审失败: {str(result)}",
                        recommendations=[],
                        partial=True,
                        errors=[EvaluationError(code="INTERNAL_ERROR", message=str(result), module="batch")],
                    )
                )
            else:
                final_results.append(result)

        return final_results
