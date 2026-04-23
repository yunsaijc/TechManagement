"""审查 Agent"""
import asyncio
import logging
import os
import time
from typing import Any, Dict, List, Optional

from src.common.llm import get_review_llm_client
from src.common.models import CheckResult, CheckStatus, ReviewResult
from src.common.vision.multimodal import MultimodalLLM
from src.services.review.doc_types import normalize_doc_type
from src.services.review.extractor import DocumentExtractor
from src.services.review.rules import ReviewContext, RuleRegistry
from src.services.review.rules.config import DOCUMENT_CONFIG, load_rules

logger = logging.getLogger(__name__)


class ReviewAgent:
    """形式审查 Agent

    协调规则引擎和多模态 LLM，实现文档的智能审查。
    """

    def __init__(
        self,
        llm: Any = None,
        document_parser: Any = None,
        rule_registry: type[RuleRegistry] = RuleRegistry,
    ):
        """初始化

        Args:
            llm: LangChain ChatModel 实例
            document_parser: 文档解析器
            rule_registry: 规则注册表
        """
        self.llm = llm or get_review_llm_client()
        self.parser = document_parser
        self.rule_registry = rule_registry
        self.extractor = DocumentExtractor(self.llm)
        self._last_raw_type = ""  # 保存原始分类结果
        self._last_ocr_text = ""  # 保存 OCR 文字

    async def process(
        self,
        file_data: bytes,
        file_type: str,
        doc_type: Optional[str] = None,
        check_items: Optional[List[str]] = None,
        enable_llm_analysis: bool = False,
        review_id: Optional[str] = None,
        **kwargs,
    ) -> ReviewResult:
        """执行审查

        Args:
            file_data: 文件数据
            file_type: 文件类型
            doc_type: 文档类型（必填，由调用方指定）
            check_items: 检查项列表（可选）
            enable_llm_analysis: 是否启用 LLM 深度分析

        Returns:
            ReviewResult: 审查结果
        """
        start_time = time.time()
        logger.info("[REVIEW] 开始处理请求")
        print("[REVIEW] 开始处理请求", flush=True)

        # 1. 文档类型由请求指定，不再进行 LLM 分类
        requested_doc_type = doc_type or kwargs.pop("document_type", None)
        if not requested_doc_type:
            raise ValueError("doc_type 为必填参数")
        normalized_doc_type = normalize_doc_type(requested_doc_type)
        if normalized_doc_type not in DOCUMENT_CONFIG:
            raise ValueError(f"不支持的 doc_type: {requested_doc_type}")
        self._last_raw_type = str(requested_doc_type)
        logger.info(f"[REVIEW] Step1 使用请求指定类型: {normalized_doc_type}")
        print(f"[REVIEW] Step1 使用请求指定类型: {normalized_doc_type}", flush=True)

        from src.services.review.extractor import ExtractedContent
        extracted = ExtractedContent()

        # 3. LLM 深度分析（可选，提前到规则之前，用于规则使用）
        llm_analysis = None
        llm_analysis_error = ""
        auto_llm_analysis = bool(DOCUMENT_CONFIG.get(normalized_doc_type, {}).get("auto_llm_analysis"))
        if enable_llm_analysis or auto_llm_analysis:
            logger.info("[REVIEW] Step2.5 LLM深度分析开始（提前到规则前）")
            print("[REVIEW] Step2.5 LLM深度分析开始（提前到规则前）", flush=True)
            try:
                llm_analysis = await self._do_llm_analysis(
                    file_data,
                    extracted,
                    normalized_doc_type,
                    kwargs.get("metadata", {}),
                )
            except Exception as exc:
                llm_analysis_error = str(exc)
                logger.warning("[REVIEW] Step2.5 LLM深度分析降级: %s", llm_analysis_error)
                print(f"[REVIEW] Step2.5 LLM深度分析降级: {llm_analysis_error}", flush=True)
                llm_analysis = {
                    "error": llm_analysis_error,
                    "document_type_llm": normalized_doc_type,
                }
            # 存到 extracted 里，供规则使用
            extracted.set("llm_analysis", llm_analysis)
            if not llm_analysis_error:
                self._hydrate_extracted_from_llm_analysis(
                    extracted=extracted,
                    llm_analysis=llm_analysis,
                    doc_type=normalized_doc_type,
                    file_data=file_data,
                )
            logger.info("[REVIEW] Step2.5 LLM深度分析完成")
            print("[REVIEW] Step2.5 LLM深度分析完成", flush=True)

        # 4. 构建审查上下文
        context = ReviewContext(
            file_data=file_data,
            file_type=file_type,
            doc_type=normalized_doc_type,
            extracted=extracted,
            metadata=kwargs.get("metadata", {}),
        )

        # 5. 加载并运行规则
        logger.info("[REVIEW] Step3 规则检查开始")
        print("[REVIEW] Step3 规则检查开始", flush=True)
        rule_results = await self._run_rules(context, check_items)
        logger.info(f"[REVIEW] Step3 规则检查完成: {len(rule_results)} 项")
        print(f"[REVIEW] Step3 规则检查完成: {len(rule_results)} 项", flush=True)

        # 5. LLM 补充（可选）
        logger.info("[REVIEW] Step3 LLM补充检查开始")
        llm_results = await self._llm_check(context, check_items)
        logger.info(f"[REVIEW] Step3 LLM补充检查完成: {len(llm_results)} 项")

        # 4. 结果聚合（LLM分析已在Step2.5提前执行）
        all_results = rule_results + llm_results
        if llm_analysis_error:
            all_results.append(
                CheckResult(
                    item="system",
                    status=CheckStatus.WARNING,
                    message=f"LLM深度分析已降级：{llm_analysis_error}",
                    evidence={"stage": "llm_analysis"},
                )
            )

        # 7. 如果是 unknown 类型，添加警告并提示管理员
        if normalized_doc_type == "unknown":
            all_results.append(CheckResult(
                item="doc_type",
                status=CheckStatus.WARNING,
                message=f"文档类型为 unknown（请求指定值：{self._last_raw_type}），请管理员新增类别后重新审查",
                evidence={"raw_type": self._last_raw_type},
                confidence=1.0,
            ))
            summary = "审查中断：文档类型无法识别，请管理员新增类别"
            suggestions = ["请管理员在系统中新增文档类型后重新提交审查"]

        else:
            summary = self._generate_summary(all_results)
            suggestions = self._generate_suggestions(all_results)

        result = ReviewResult(
            id=review_id or f"review_{int(time.time() * 1000)}",
            status="done",
            doc_type=normalized_doc_type,
            doc_type_raw=self._last_raw_type,
            results=all_results,
            ocr_text=extracted.get("text", ""),
            extracted_data={
                "units": extracted.get("units", []),
                "work_units": extracted.get("work_units", []),
                "authors": extracted.get("authors", []),
                "project_name": extracted.get("project_name", ""),
                "stamps": extracted.get("stamps", []),
                "signatures": extracted.get("signatures", []),
                "pages": extracted.get("pages", 0),
            },
            llm_analysis=llm_analysis,
            summary=summary,
            suggestions=suggestions,
            processing_time=time.time() - start_time,
        )
        logger.info(f"[REVIEW] 处理完成，总耗时: {result.processing_time:.2f}s")
        print(f"[REVIEW] 处理完成，总耗时: {result.processing_time:.2f}s", flush=True)
        return result

    def _hydrate_extracted_from_llm_analysis(
        self,
        extracted: Any,
        llm_analysis: Optional[Dict[str, Any]],
        doc_type: str,
        file_data: bytes,
    ) -> None:
        """将专项分析结果回填到 extracted，避免 extracted_data 与 llm_analysis 打架。"""
        if not llm_analysis:
            return

        normalized_doc_type = normalize_doc_type(doc_type)
        if normalized_doc_type in {"wcr", "wjwcr"}:
            payload = llm_analysis.get("award_contributor_analysis") or {}
            contributor_name = str(payload.get("contributor_name") or "").strip()
            work_unit = str(payload.get("work_unit") or "").strip()
            completion_unit = str(payload.get("completion_unit") or "").strip()
            signature_names = [str(item).strip() for item in payload.get("signature_names", []) if str(item).strip()]
            stamps_result = llm_analysis.get("stamps_result") or {}
            signatures_result = llm_analysis.get("signatures_result") or {}

            units: List[str] = []
            for unit in (completion_unit, work_unit):
                if unit and unit not in units:
                    units.append(unit)

            extracted.set("authors", [contributor_name] if contributor_name else [])
            extracted.set("work_units", [work_unit] if work_unit else [])
            extracted.set("units", units)
            extracted.set("project_name", "")
            extracted.set("stamps", list(stamps_result.get("stamps", [])) if isinstance(stamps_result, dict) else [])
            if isinstance(signatures_result, dict) and signatures_result.get("signatures"):
                extracted.set("signatures", list(signatures_result.get("signatures", [])))
            else:
                extracted.set(
                    "signatures",
                    [{"text": name, "bbox": None, "confidence": 0.9} for name in signature_names],
                )
            extracted.set("pages", self._count_pages(file_data))
            return

        extracted_fields = llm_analysis.get("extracted_fields") or {}
        if not extracted.get("project_name"):
            extracted.set("project_name", str(extracted_fields.get("项目名称") or "").strip())
        stamps_result = llm_analysis.get("stamps_result") or {}
        if not extracted.get("stamps") and isinstance(stamps_result, dict):
            extracted.set("stamps", list(stamps_result.get("stamps", [])))

    def _count_pages(self, file_data: bytes) -> int:
        """统计页数，供结果输出使用。"""
        if not file_data.startswith(b"%PDF"):
            return 1
        try:
            import fitz

            doc = fitz.open(stream=file_data, filetype="pdf")
            page_count = int(doc.page_count or 1)
            doc.close()
            return page_count
        except Exception:
            return 1

    def _build_award_contributor_analysis_image(self, file_data: bytes) -> bytes:
        """构建主要完成人情况表的复合分析图。

        面板包含：
        A. 字段区（姓名/工作单位/完成单位）
        B. 签名区
        C. 工作单位公章候选区
        D. 完成单位公章候选区
        """
        import io
        from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps

        image_data = self._pdf_to_image(file_data)
        try:
            page = Image.open(io.BytesIO(image_data))
            page = ImageOps.exif_transpose(page).convert("RGB")
        except Exception:
            return image_data

        def _crop_ratio(box: tuple[float, float, float, float]) -> Image.Image:
            w, h = page.size
            x1 = int(max(0.0, min(1.0, box[0])) * w)
            y1 = int(max(0.0, min(1.0, box[1])) * h)
            x2 = int(max(0.0, min(1.0, box[2])) * w)
            y2 = int(max(0.0, min(1.0, box[3])) * h)
            if x2 <= x1 or y2 <= y1:
                return page.copy()
            return page.crop((x1, y1, x2, y2))

        def _enhance_region(img: Image.Image) -> Image.Image:
            out = img.convert("RGB")
            out = ImageOps.autocontrast(out, cutoff=1)
            out = ImageEnhance.Color(out).enhance(1.1)
            out = ImageEnhance.Contrast(out).enhance(1.22)
            out = ImageEnhance.Sharpness(out).enhance(1.2)
            out = out.filter(ImageFilter.UnsharpMask(radius=1.1, percent=110, threshold=2))
            out = out.resize((max(1, int(out.width * 1.6)), max(1, int(out.height * 1.6))), Image.LANCZOS)
            border = max(10, min(out.size) // 20)
            return ImageOps.expand(out, border=border, fill="white")

        def _fit(img: Image.Image, target_size: tuple[int, int]) -> Image.Image:
            fitted = img.copy()
            fitted.thumbnail(target_size, Image.LANCZOS)
            canvas = Image.new("RGB", target_size, "white")
            x = (target_size[0] - fitted.width) // 2
            y = (target_size[1] - fitted.height) // 2
            canvas.paste(fitted, (x, y))
            return canvas

        def _panel(img: Image.Image, label: str, target_size: tuple[int, int], enhance: bool = False) -> Image.Image:
            panel_img = _enhance_region(img) if enhance else img.convert("RGB")
            panel = _fit(panel_img, target_size)
            header_h = 44
            panel_with_header = Image.new("RGB", (target_size[0], target_size[1] + header_h), "white")
            panel_with_header.paste(panel, (0, header_h))
            draw = ImageDraw.Draw(panel_with_header)
            font = ImageFont.load_default()
            draw.rectangle((0, 0, target_size[0], header_h), fill="#f3f4f6")
            draw.text((14, 14), label, fill="black", font=font)
            return panel_with_header

        fields_panel = _panel(_crop_ratio((0.04, 0.06, 0.96, 0.52)), "A 字段区", (760, 360), enhance=True)
        signature_panel = _panel(_crop_ratio((0.02, 0.58, 0.46, 0.97)), "B 签名区", (360, 300), enhance=True)
        work_panel = _panel(_crop_ratio((0.44, 0.58, 0.76, 0.97)), "C 工作单位公章区", (360, 300), enhance=True)
        completion_panel = _panel(_crop_ratio((0.60, 0.58, 0.98, 0.97)), "D 完成单位公章区", (360, 300), enhance=True)

        gap = 18
        canvas_w = fields_panel.width + signature_panel.width + gap
        canvas_h = fields_panel.height + gap + max(work_panel.height, completion_panel.height)
        canvas = Image.new("RGB", (canvas_w, canvas_h), "white")
        canvas.paste(fields_panel, (0, 0))
        canvas.paste(signature_panel, (fields_panel.width + gap, 0))
        canvas.paste(work_panel, (0, fields_panel.height + gap))
        canvas.paste(completion_panel, (work_panel.width + gap, fields_panel.height + gap))

        buf = io.BytesIO()
        canvas.save(buf, format="PNG", optimize=True)
        return buf.getvalue()

    def _compress_image_for_llm(self, img_data: bytes, max_size: int = 2000000) -> bytes:
        """压缩图片到合理大小，避免超过 LLM 10MB 限制"""
        try:
            from PIL import Image
            import io
            img = Image.open(io.BytesIO(img_data))
            max_dim = 2048
            if max(img.size) > max_dim:
                ratio = max_dim / max(img.size)
                new_size = (int(img.size[0] * ratio), int(img.size[1] * ratio))
                img = img.resize(new_size, Image.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, format='JPEG', quality=85, optimize=True)
            return buf.getvalue()
        except Exception:
            return img_data

    async def _analyze_image_with_timeout(
        self,
        multi_llm: MultimodalLLM,
        image_data: bytes,
        prompt: str,
        stage: str,
        timeout_sec: Optional[int] = None,
    ) -> str:
        """统一的多模态调用封装：带超时和步骤日志。"""
        # 压缩图片避免超过 LLM 10MB 限制
        image_data = self._compress_image_for_llm(image_data)
        timeout = timeout_sec or int(os.getenv("LLM_STEP_TIMEOUT", "45"))
        logger.info(f"[LLM] {stage} 开始 (timeout={timeout}s)")
        print(f"[LLM] {stage} 开始", flush=True)
        try:
            result = await asyncio.wait_for(
                multi_llm.analyze_image(image_data, prompt),
                timeout=timeout,
            )
            logger.info(f"[LLM] {stage} 完成")
            print(f"[LLM] {stage} 完成", flush=True)
            return result
        except asyncio.TimeoutError as e:
            msg = f"{stage} 超时（>{timeout}s）"
            logger.error(f"[LLM] {msg}")
            print(f"[LLM] {msg}", flush=True)
            raise RuntimeError(msg) from e

    async def _classify_document(self, file_data: bytes) -> tuple[str, Any]:
        """文档分类 - 直接用 LLM 识别（不依赖 OCR）
        
        Returns:
            (doc_type, extracted_content)
        """
        from src.common.vision.multimodal import MultimodalLLM
        from src.services.review.rules.config import get_type_labels_for_llm
        
        multi_llm = MultimodalLLM(self.llm)
        
        # 将 PDF 转为图片
        image_data = self._pdf_to_image(file_data)
        
        # 用 LLM 直接识别文档类型
        labels_text = get_type_labels_for_llm()
        prompt = f"""请识别这个文档的类型（直接返回中文名称，不要其他内容）：
{labels_text}

直接返回上述类型名称之一。如果不在上述类型中，请返回"未知"。"""
        
        try:
            result = await self._analyze_image_with_timeout(
                multi_llm, image_data, prompt, "分类", timeout_sec=30
            )
            doc_type = self._match_document_type(result)
            self._last_raw_type = result.strip()
        except Exception as e:
            doc_type = "unknown"
            self._last_raw_type = f"LLM分类失败: {e}"
        
        # 返回空 extracted（等 LLM 分析时再提取字段）
        self._last_ocr_text = ""
        
        from src.services.review.extractor import ExtractedContent
        return doc_type, ExtractedContent()
    
    def _match_document_type(self, ocr_text: str) -> str:
        """根据 OCR 文字匹配文档类型（从配置读取）"""
        import re
        from src.services.review.rules.config import DOCUMENT_CONFIG
        
        # 从配置中读取所有标签进行匹配
        for doc_type, config in DOCUMENT_CONFIG.items():
            labels = config.get("labels", [])
            for label in labels:
                if re.search(label, ocr_text):
                    return doc_type
        
        return "unknown"

    async def _run_rules(
        self,
        context: ReviewContext,
        check_items: Optional[List[str]] = None,
    ) -> List[CheckResult]:
        """运行规则"""
        # 从配置加载规则
        rule_names = load_rules(context.doc_type)
        
        # 创建规则实例
        rules = []
        for name in rule_names:
            rule_class = self.rule_registry.get_rule(name)
            if rule_class:
                rules.append(rule_class())
        
        # 如果没有配置规则，使用 registry 的默认链
        if not rules:
            rules = self.rule_registry.create_chain(context.doc_type)

        # 过滤检查项
        if check_items:
            rules = [r for r in rules if r.name in check_items]

        results = []
        for rule in rules:
            if await rule.should_run(context):
                result = await rule.check(context)
                results.append(result)

        return results

    async def _llm_check(
        self,
        context: ReviewContext,
        check_items: Optional[List[str]] = None,
    ) -> List[CheckResult]:
        """LLM 补充检查"""
        # 需要 LLM 检查的项目
        llm_items = ["consistency", "completeness", "signature_name_consistency"]
        if check_items:
            llm_items = [i for i in llm_items if i in check_items]

        results = []

        if "consistency" in llm_items:
            result = await self._check_consistency(context)
            if result:
                results.append(result)

        if "signature_name_consistency" in llm_items:
            result = await self._check_signature_name_consistency(context)
            if result:
                results.append(result)

        return results

    async def _check_consistency(self, context: ReviewContext) -> Optional[CheckResult]:
        """一致性检查"""
        form_data = context.metadata.get("form_data", {})
        if not form_data:
            return None

        multi_llm = MultimodalLLM(self.llm)

        prompt = f"""请检查文档中的信息与以下表单数据是否一致：

表单数据：
{form_data}

请分析并给出结果（一致/不一致）。"""

        try:
            result = await self._analyze_image_with_timeout(
                multi_llm, context.file_data, prompt, "一致性检查", timeout_sec=30
            )

            return CheckResult(
                item="consistency",
                status=CheckStatus.PASSED if "一致" in result else CheckStatus.FAILED,
                message="一致性检查完成",
                evidence={"llm_analysis": result},
            )
        except Exception:
            return CheckResult(
                item="consistency",
                status=CheckStatus.WARNING,
                message="一致性检查暂时不可用",
                evidence={},
            )

    async def _check_signature_name_consistency(
        self, context: ReviewContext
    ) -> Optional[CheckResult]:
        """签字与完成人姓名一致性检查
        
        检查签字区域识别出的人名是否与"主要完成人情况表"中的姓名一致。
        """
        extracted = context.extracted
        llm_analysis = extracted.get("llm_analysis", {})
        
        if not llm_analysis:
            return CheckResult(
                item="signature_name_consistency",
                status=CheckStatus.WARNING,
                message="未找到 LLM 分析结果",
                evidence={},
            )
        
        # 从提取的字段获取姓名
        fields = llm_analysis.get("extracted_fields", {})
        contributor_name = fields.get("姓名", "").strip()
        
        # 从签字描述获取签字人名
        signatures_desc = llm_analysis.get("signatures_description", "").strip()
        
        if not contributor_name:
            return CheckResult(
                item="signature_name_consistency",
                status=CheckStatus.WARNING,
                message="未提取到完成人姓名",
                evidence={"fields": fields},
            )
        
        if not signatures_desc:
            return CheckResult(
                item="signature_name_consistency",
                status=CheckStatus.FAILED,
                message="未提取到签字信息",
                evidence={"signatures_description": signatures_desc},
            )
        
        # 检查签字描述中是否包含完成人姓名
        if contributor_name in signatures_desc:
            return CheckResult(
                item="signature_name_consistency",
                status=CheckStatus.PASSED,
                message=f"签字人'{contributor_name}'与完成人一致",
                evidence={
                    "contributor_name": contributor_name,
                    "signatures_description": signatures_desc,
                },
            )
        else:
            return CheckResult(
                item="signature_name_consistency",
                status=CheckStatus.FAILED,
                message=f"完成人'{contributor_name}'与签字人不一致",
                evidence={
                    "contributor_name": contributor_name,
                    "signatures_description": signatures_desc,
                },
            )

    def _generate_summary(self, results: List[CheckResult]) -> str:
        """生成总结"""
        passed = sum(1 for r in results if r.status == CheckStatus.PASSED)
        failed = sum(1 for r in results if r.status == CheckStatus.FAILED)
        warnings = sum(1 for r in results if r.status == CheckStatus.WARNING)

        return f"审查完成：通过 {passed} 项，失败 {failed} 项，警告 {warnings} 项"

    def _generate_suggestions(self, results: List[CheckResult]) -> List[str]:
        """生成建议"""
        suggestions = []

        for result in results:
            if result.status == CheckStatus.FAILED:
                suggestions.append(f"请检查：{result.item} - {result.message}")
            elif result.status == CheckStatus.WARNING:
                suggestions.append(f"注意：{result.item} - {result.message}")

        return suggestions

    async def _do_llm_analysis(
        self,
        file_data: bytes,
        extracted: Any,
        doc_type: str = "unknown",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """LLM 深度分析（用于调试 OCR 效果）
        
        Args:
            file_data: 文件数据
            extracted: OCR 提取的内容
            doc_type: 文档类型
            
        Returns:
            LLM 分析结果
        """
        normalized_doc_type = normalize_doc_type(doc_type)
        if normalized_doc_type in {"wcr", "wjwcr"}:
            return await self._do_award_contributor_llm_analysis(file_data, doc_type, metadata or {})
        if normalized_doc_type == "dywcrcns":
            return await self._do_first_contributor_commitment_llm_analysis(file_data, doc_type, metadata or {})
        if normalized_doc_type == "dywcdwcns":
            return await self._do_first_completion_unit_commitment_llm_analysis(file_data, doc_type)
        if normalized_doc_type == "qysm":
            return await self._do_enterprise_statement_llm_analysis(file_data, doc_type, metadata or {})

        multi_llm = MultimodalLLM(self.llm)
        logger.info(f"[LLM] 深度分析开始，doc_type={doc_type}")
        print(f"[LLM] 深度分析开始，doc_type={doc_type}", flush=True)
        
        # 将 PDF 转为图片（取第一页）
        image_data = self._pdf_to_image(file_data)
        
        ocr_text = extracted.get("text", "") or ""
        
        # 1. 文档类型由请求指定，不做 LLM 分类
        doc_type_llm = doc_type
        
        # 2. LLM 通用表格内容提取（一次调用，原文照抄）
        import re
        from src.services.review.rules.config import load_llm_extract_fields
        from PIL import Image
        import io
        
        # 尝试从配置中获取关键字段
        configured_fields = load_llm_extract_fields(doc_type)
        
        try:
            # 将 PDF 转为图片（取第一页）
            image_data = self._pdf_to_image(file_data)
            img = Image.open(io.BytesIO(image_data))
            img_w, img_h = img.size
            
            # Step1: 识别表格字段（如果没有配置字段，才走自动识别）
            if configured_fields:
                field_names = configured_fields
                logger.info(f"[LLM] 使用配置的关键字段: {field_names}")
            else:
                logger.info("[LLM] Step1: 识别表格字段...")
                prompt_detect = """请仔细看图，列出这个表格/表单的所有字段名（只返回字段名列表，每行一个）。

只输出字段名，不要其他内容。"""

                cols_result = await self._analyze_image_with_timeout(
                    multi_llm, image_data, prompt_detect, "深度分析-Step1字段检测", timeout_sec=40
                )
                field_names = [line.strip() for line in cols_result.strip().split('\n') if line.strip() and len(line.strip()) > 1]
                max_fields = int(os.getenv("LLM_MAX_FIELDS", "25"))
                if len(field_names) > max_fields:
                    logger.warning(f"[LLM] 字段数过多({len(field_names)})，仅保留前{max_fields}个")
                    field_names = field_names[:max_fields]
                logger.info(f"[LLM] 识别到字段数: {len(field_names)}")
                
                if not field_names:
                    raise Exception("未能识别到表格字段")
            
            # Step2: 定位每个字段的值区域
            logger.info("[LLM] Step2: 定位字段值区域...")
            prompt_locate = f"""请在图片中找出以下字段的【填写内容】区域（不是字段名，是实际填写文字的区域，要尽量小，只包含文字）：

{chr(10).join(field_names)}

返回格式（每行）：
字段名: x1,y1,x2,y2 （归一化坐标0-1）"""

            locate_result = await self._analyze_image_with_timeout(
                    multi_llm, image_data, prompt_locate, "深度分析-Step2字段定位", timeout_sec=180
            )
            
            # 解析坐标
            field_coords = {}
            for line in locate_result.strip().split('\n'):
                match = re.match(r'(.+?):\s*([\d.]+),([\d.]+),([\d.]+),([\d.]+)', line)
                if match:
                    fname = match.group(1).strip()
                    x1, y1, x2, y2 = float(match.group(2)), float(match.group(3)), float(match.group(4)), float(match.group(5))
                    field_coords[fname] = (x1, y1, x2, y2)
            
            logger.info(f"[LLM] 定位到 {len(field_coords)} 个字段区域")
            
            # Step3: 使用 FieldExtractor 提取（统一提取逻辑）
            from src.common.extractors import FieldExtractor
            extractor = FieldExtractor()
            fields_llm = await extractor.extract_with_coords(
                file_data=image_data,
                field_coords=field_coords,
                field_names=field_names,
            )
            
            logger.info("[LLM] 表格提取完成")
        except Exception as e:
            logger.error(f"[LLM] 表格提取失败: {e}")
            fields_llm = {"error": str(e)}
        
        # 3. 使用 StampExtractor 提取印章
        from src.common.extractors import StampExtractor
        stamp_extractor = StampExtractor()
        stamps_result = await stamp_extractor.extract(file_data)
        
        # stamps_result 是结构化数据，stamps_desc 是用于展示的描述文本
        if stamps_result and stamps_result.get("stamps"):
            stamps_desc = " ".join([
                f"印章{i+1}: {s.get('unit', '未知单位')}" 
                for i, s in enumerate(stamps_result.get("stamps", []))
            ])
        else:
            stamps_desc = "未检测到印章"
        
        # 4. 使用 SignatureExtractor 提取签字
        from src.common.extractors import SignatureExtractor
        sig_extractor = SignatureExtractor()
        sigs_result = await sig_extractor.extract(file_data)
        sigs_desc = sigs_result if sigs_result else "未检测到签字"
        
        return {
            "document_type_llm": doc_type_llm.strip(),
            "extracted_fields": fields_llm,
            "stamps_description": stamps_desc,
            "stamps_result": stamps_result,  # 结构化印章数据
            "signatures_description": str(sigs_desc) if sigs_desc else "未检测到签字",
        }

    async def _do_award_contributor_llm_analysis(
        self,
        file_data: bytes,
        doc_type: str,
        metadata: Dict[str, Any],
    ) -> Dict[str, Any]:
        """主要完成人情况表专项结构化分析。"""
        multi_llm = MultimodalLLM(self.llm)
        logger.info(f"[LLM] 主要完成人情况表专项分析开始，doc_type={doc_type}")
        print(f"[LLM] 主要完成人情况表专项分析开始，doc_type={doc_type}", flush=True)

        field_values, signatures_result, stamp_anchors = await asyncio.gather(
            self._extract_award_contributor_fields_with_ocr(file_data, doc_type),
            self._extract_award_contributor_signatures(file_data),
            self._locate_award_contributor_stamp_anchors(file_data),
        )
        signature_names = [
            str(item.get("text") or "").strip()
            for item in signatures_result.get("signatures", [])
            if isinstance(item, dict) and str(item.get("text") or "").strip()
        ]
        payload = {
            "signature_names": signature_names,
            "work_unit_stamp_units": [],
            "completion_unit_stamp_units": [],
            "all_stamp_units": [],
            "raw_response": "",
        }
        payload["contributor_name"] = field_values.get("姓名", "")
        payload["work_unit"] = field_values.get("工作单位", "")
        payload["completion_unit"] = field_values.get("完成单位", "")
        payload["field_ocr_result"] = field_values
        payload["stamp_regions"] = []
        payload["stamp_anchor_regions"] = dict(stamp_anchors or {})

        image_data = self._build_award_contributor_analysis_image(file_data)
        stamp_result, verification_result = await asyncio.gather(
            self._extract_award_contributor_stamps(file_data, anchors=stamp_anchors),
            self._verify_award_contributor_signature_if_needed(
                multi_llm=multi_llm,
                image_data=image_data,
                metadata=metadata,
                payload=payload,
            ),
        )
        payload["work_unit_stamp_units"] = list(stamp_result.get("work_unit_stamp_units", []))
        payload["completion_unit_stamp_units"] = list(stamp_result.get("completion_unit_stamp_units", []))
        payload["all_stamp_units"] = list(stamp_result.get("all_stamp_units", []))
        payload["stamp_regions"] = list(stamp_result.get("regions", []))
        payload["stamp_anchor_regions"] = dict(stamp_result.get("anchor_regions", {}))

        extracted_fields = {
            "姓名": payload.get("contributor_name", ""),
            "工作单位": payload.get("work_unit", ""),
            "完成单位": payload.get("completion_unit", ""),
        }
        work_stamp_units = payload.get("work_unit_stamp_units", [])
        completion_stamp_units = payload.get("completion_unit_stamp_units", [])
        all_stamp_units = []
        for unit in [*work_stamp_units, *completion_stamp_units]:
            text = str(unit or "").strip()
            if text and text not in all_stamp_units:
                all_stamp_units.append(text)
        stamps_result = stamp_result

        signatures_description = "；".join(signature_names) if signature_names else "未检测到签字"
        stamps_description = "；".join(all_stamp_units) if all_stamp_units else "未检测到印章"

        return {
            "document_type_llm": doc_type,
            "extracted_fields": extracted_fields,
            "stamps_description": stamps_description,
            "stamps_result": stamps_result,
            "signatures_result": signatures_result,
            "signatures_description": signatures_description,
            "verification_result": verification_result,
            "award_contributor_analysis": payload,
        }

    async def _extract_award_contributor_signatures(self, file_data: bytes) -> Dict[str, Any]:
        """主要完成人签字：统一走 SignatureExtractor。"""
        try:
            from src.common.extractors import SignatureExtractor
            from src.common.extractors.signature import normalize_signature_entries

            extractor = SignatureExtractor()
            result = await extractor.extract(file_data)
            signatures = normalize_signature_entries((result or {}).get("signatures", []))
        except Exception as exc:
            logger.warning("[REVIEW] 主要完成人签字提取失败: %s", exc)
            signatures = []

        return {"signatures": signatures}

    async def _locate_award_contributor_stamp_anchors(self, file_data: bytes) -> Dict[str, Any]:
        """主要完成人公章锚点定位。"""
        try:
            from src.common.extractors import StampExtractor

            extractor = StampExtractor()
            result = await extractor.locate_award_contributor_stamp_anchors(file_data)
        except Exception as exc:
            logger.warning("[REVIEW] 主要完成人公章锚点定位失败: %s", exc)
            result = {}

        return dict(result or {})

    async def _extract_award_contributor_stamps(
        self,
        file_data: bytes,
        anchors: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """主要完成人公章：统一走 StampExtractor。"""
        try:
            from src.common.extractors import StampExtractor

            extractor = StampExtractor()
            if anchors is None:
                result = await extractor.extract_award_contributor_stamps(file_data)
            else:
                result = await extractor.extract_award_contributor_stamps_from_anchors(file_data, anchors)
        except Exception as exc:
            logger.warning("[REVIEW] 主要完成人公章提取失败: %s", exc)
            result = {}

        if not isinstance(result, dict):
            result = {}
        return {
            "stamps": list(result.get("stamps", [])),
            "work_unit_stamp_units": list(result.get("work_unit_stamp_units", [])),
            "completion_unit_stamp_units": list(result.get("completion_unit_stamp_units", [])),
            "all_stamp_units": list(result.get("all_stamp_units", [])),
            "anchor_regions": dict(result.get("anchor_regions", {})),
            "regions": list(result.get("regions", [])),
            "raw": result.get("raw", {}),
        }

    async def _extract_award_contributor_fields_with_ocr(self, file_data: bytes, doc_type: str) -> Dict[str, str]:
        """主要完成人表单字段：定位值区域后裁剪 OCR。"""
        field_names = ["姓名", "工作单位", "完成单位"]
        try:
            from src.common.extractors import FieldExtractor

            extractor = FieldExtractor()
            fields = await extractor.extract(
                file_data=file_data,
                document_type=doc_type,
                configured_fields=field_names,
            )
        except Exception as exc:
            logger.warning("[REVIEW] 主要完成人字段 OCR 提取失败: %s", exc)
            fields = {}

        if not isinstance(fields, dict):
            fields = {}
        return {
            name: str(fields.get(name) or "").strip()
            for name in field_names
        }

    async def _do_first_contributor_commitment_llm_analysis(
        self,
        file_data: bytes,
        doc_type: str,
        metadata: Dict[str, Any],
    ) -> Dict[str, Any]:
        """第一完成人承诺书：只走底部签字专项。"""
        page_image = self._load_page_image(file_data)
        if page_image is None:
            return {"document_type_llm": doc_type, "extracted_fields": {"姓名": ""}, "stamps_description": "未检测到印章", "stamps_result": {"stamps": []}, "signatures_result": {"signatures": []}, "signatures_description": "未检测到签字", "verification_result": {}}

        signature_crop = self._crop_ratio_image(page_image, (0.28, 0.64, 0.92, 0.88))
        self._save_special_debug_crop("first_contributor_signature_crop", signature_crop)
        signature_bytes = self._image_to_png_bytes(signature_crop)
        signatures_result = await self._extract_signatures_from_image(signature_bytes)
        signature_names = self._extract_signature_names(signatures_result)
        verification_result = await self._verify_target_signature_if_needed(
            image_data=signature_bytes,
            expected_name=str(((metadata.get("reward_review_context") or {}).get("target_values") or {}).get("name") or "").strip(),
            signature_names=signature_names,
            verification_key="signature_for_name",
            task_name="第一完成人签字定向验证",
            prompt_label="第一完成人签字区域",
        )

        recognized_name = signature_names[0] if signature_names else ""
        return {
            "document_type_llm": doc_type,
            "extracted_fields": {"姓名": recognized_name},
            "stamps_description": "未检测到印章",
            "stamps_result": {"stamps": []},
            "signatures_result": signatures_result,
            "signatures_description": "；".join(signature_names) if signature_names else "未检测到签字",
            "verification_result": verification_result,
        }

    async def _do_first_completion_unit_commitment_llm_analysis(
        self,
        file_data: bytes,
        doc_type: str,
    ) -> Dict[str, Any]:
        """第一完成单位承诺书：只走底部公章专项。"""
        page_image = self._load_page_image(file_data)
        if page_image is None:
            return {"document_type_llm": doc_type, "extracted_fields": {"单位名称": ""}, "stamps_description": "未检测到印章", "stamps_result": {"stamps": []}, "signatures_result": {"signatures": []}, "signatures_description": "未检测到签字", "verification_result": {}}

        stamp_crop = self._crop_ratio_image(page_image, (0.34, 0.52, 0.82, 0.86))
        self._save_special_debug_crop("first_completion_unit_stamp_crop", stamp_crop)
        stamp_result = await self._extract_stamps_from_image(stamp_crop, debug_prefix="first_completion_unit")
        stamp_units = self._extract_stamp_units(stamp_result)

        return {
            "document_type_llm": doc_type,
            "extracted_fields": {"单位名称": stamp_units[0] if stamp_units else ""},
            "stamps_description": "；".join(stamp_units) if stamp_units else "未检测到印章",
            "stamps_result": stamp_result,
            "signatures_result": {"signatures": []},
            "signatures_description": "未检测到签字",
            "verification_result": {},
        }

    async def _do_enterprise_statement_llm_analysis(
        self,
        file_data: bytes,
        doc_type: str,
        metadata: Dict[str, Any],
    ) -> Dict[str, Any]:
        """企业声明：法定代表人签名/签章 + 企业公章专项。"""
        page_image = self._load_page_image(file_data)
        if page_image is None:
            return {"document_type_llm": doc_type, "extracted_fields": {"企业名称": "", "法定代表人": ""}, "stamps_description": "未检测到印章", "stamps_result": {"stamps": []}, "signatures_result": {"signatures": []}, "signatures_description": "未检测到签字", "verification_result": {}}

        rep_crop = self._crop_ratio_image(page_image, (0.08, 0.56, 0.56, 0.82))
        company_stamp_crop = self._crop_ratio_image(page_image, (0.45, 0.44, 0.88, 0.82))
        self._save_special_debug_crop("enterprise_legal_representative_crop", rep_crop)
        self._save_special_debug_crop("enterprise_stamp_crop", company_stamp_crop)

        rep_bytes = self._image_to_png_bytes(rep_crop)
        signatures_result = await self._extract_signatures_from_image(rep_bytes)
        signature_names = self._extract_signature_names(signatures_result)
        rep_stamp_result = await self._extract_stamps_from_image(rep_crop, debug_prefix="enterprise_legal_representative")
        representative_name = signature_names[0] if signature_names else self._pick_short_person_name_from_stamps(rep_stamp_result)
        if representative_name and not signature_names:
            signatures_result = {
                "signatures": [{"text": representative_name, "bbox": None, "confidence": 0.8}],
            }
            signature_names = [representative_name]

        company_stamp_result = await self._extract_stamps_from_image(company_stamp_crop, debug_prefix="enterprise")
        stamp_units = self._extract_company_like_stamp_units(company_stamp_result) or self._extract_stamp_units(company_stamp_result)
        verification_result = await self._verify_target_signature_if_needed(
            image_data=rep_bytes,
            expected_name=str(((metadata.get("reward_review_context") or {}).get("target_values") or {}).get("legal_representative") or "").strip(),
            signature_names=signature_names,
            verification_key="legal_representative_signature",
            task_name="企业声明法定代表人定向验证",
            prompt_label="法定代表人签名/签章区域",
        )

        return {
            "document_type_llm": doc_type,
            "extracted_fields": {
                "企业名称": stamp_units[0] if stamp_units else "",
                "法定代表人": representative_name,
            },
            "stamps_description": "；".join(stamp_units) if stamp_units else "未检测到印章",
            "stamps_result": company_stamp_result,
            "signatures_result": signatures_result,
            "signatures_description": "；".join(signature_names) if signature_names else "未检测到签字",
            "verification_result": verification_result,
        }

    async def _extract_signatures_from_image(self, image_data: bytes) -> Dict[str, Any]:
        try:
            from src.common.extractors import SignatureExtractor
            from src.common.extractors.signature import normalize_signature_entries

            extractor = SignatureExtractor()
            result = await extractor.extract(image_data)
            signatures = normalize_signature_entries((result or {}).get("signatures", []))
        except Exception as exc:
            logger.warning("[REVIEW] 专项签字提取失败: %s", exc)
            signatures = []
        return {"signatures": signatures}

    async def _extract_stamps_from_image(self, image: Any, debug_prefix: str = "") -> Dict[str, Any]:
        try:
            from src.common.extractors import StampExtractor

            image_data = self._image_to_png_bytes(image) if hasattr(image, "save") else image
            extractor = StampExtractor()
            result = await extractor.extract(image_data)
        except Exception as exc:
            logger.warning("[REVIEW] 专项公章提取失败: %s", exc)
            result = {}

        if not isinstance(result, dict):
            result = {}
        stamps = list(result.get("stamps", []))
        if debug_prefix:
            self._save_special_polar_if_exists(debug_prefix, result)
        return {"stamps": stamps, "raw": result.get("raw", "")}

    def _extract_signature_names(self, signatures_result: Dict[str, Any]) -> List[str]:
        names: List[str] = []
        for item in (signatures_result or {}).get("signatures", []):
            text = str((item or {}).get("text") or "").strip()
            if text and "不清晰" not in text and text not in names:
                names.append(text)
        return names

    def _extract_stamp_units(self, stamp_result: Dict[str, Any]) -> List[str]:
        units: List[str] = []
        for item in (stamp_result or {}).get("stamps", []):
            text = str(item.get("unit") or item.get("text") or "").strip()
            if text and text not in units:
                units.append(text)
        return units

    def _extract_company_like_stamp_units(self, stamp_result: Dict[str, Any]) -> List[str]:
        units: List[str] = []
        company_markers = ("公司", "集团", "有限", "股份", "研究所", "大学", "学院", "中心")
        for item in (stamp_result or {}).get("stamps", []):
            text = str(item.get("unit") or item.get("text") or "").strip()
            if not text or text in units:
                continue
            if len(text) >= 6 or any(marker in text for marker in company_markers):
                units.append(text)
        return units

    def _pick_short_person_name_from_stamps(self, stamp_result: Dict[str, Any]) -> str:
        for item in (stamp_result or {}).get("stamps", []):
            text = str(item.get("unit") or item.get("text") or "").strip()
            if 2 <= len(text) <= 4 and "公章" not in text and "公司" not in text:
                return text
        return ""

    async def _verify_target_signature_if_needed(
        self,
        image_data: bytes,
        expected_name: str,
        signature_names: List[str],
        verification_key: str,
        task_name: str,
        prompt_label: str,
    ) -> Dict[str, Any]:
        if not expected_name or self._award_text_matches(expected_name, signature_names):
            return {}
        multi_llm = MultimodalLLM(self.llm)
        prompt = """请只判断图中的%s里的签名/签章是否可以清晰确认是目标姓名。
目标姓名：%s

返回严格 JSON：
{"%s": {"status": "yes|no|uncertain", "reason": ""}}

规则：
1. yes 仅表示可以清晰确认是目标姓名。
2. no 表示未见对应签名/签章，或可清晰确认不是目标姓名。
3. uncertain 表示看不清或无法确认。
4. 只返回 JSON，不要解释。""" % (prompt_label, expected_name, verification_key)
        raw = await self._analyze_image_with_timeout(
            multi_llm,
            image_data,
            prompt,
            task_name,
            timeout_sec=45,
        )
        entry = self._parse_named_verification(raw, verification_key)
        return {verification_key: entry} if entry.get("status") else {}

    def _parse_named_verification(self, raw_text: str, key: str) -> Dict[str, str]:
        import json
        import re

        text = str(raw_text or "").strip()
        if text.startswith("```"):
            parts = text.split("```", 2)
            if len(parts) >= 2:
                text = parts[1]
                if text.startswith("json"):
                    text = text[4:]
        match = re.search(r"\{.*\}", text, re.DOTALL)
        try:
            payload = json.loads(match.group(0)) if match else {}
        except Exception:
            payload = {}
        entry = payload.get(key) if isinstance(payload, dict) else {}
        if isinstance(entry, str):
            status = entry.strip().lower()
            return {"status": status if status in {"yes", "no", "uncertain"} else "", "reason": ""}
        if not isinstance(entry, dict):
            return {}
        status = str(entry.get("status") or "").strip().lower()
        if status not in {"yes", "no", "uncertain"}:
            return {}
        return {"status": status, "reason": str(entry.get("reason") or "").strip()}

    async def _verify_award_contributor_signature_if_needed(
        self,
        multi_llm: MultimodalLLM,
        image_data: bytes,
        metadata: Dict[str, Any],
        payload: Dict[str, Any],
    ) -> Dict[str, str]:
        """仅在签字 raw 对比未通过时，使用目标姓名做定向兜底。"""
        reward_context = metadata.get("reward_review_context") if isinstance(metadata, dict) else {}
        target_values = reward_context.get("target_values") if isinstance(reward_context, dict) else {}
        expected_name = str((target_values or {}).get("name") or "").strip()
        if not expected_name:
            return {}

        contributor_name = str(payload.get("contributor_name") or "").strip()
        signature_names = [str(item).strip() for item in payload.get("signature_names", []) if str(item).strip()]
        if self._award_text_matches(expected_name, [contributor_name]) and self._award_text_matches(expected_name, signature_names):
            return {}

        prompt = """4 个局部图：
A 字段区
B 签名区
C 工作单位公章区
D 完成单位公章区

只判断 B 签名区里的手写签字是否可以清晰确认是目标姓名。
目标姓名：%s

返回严格 JSON：
{"signature_for_name": {"status": "yes|no|uncertain", "reason": ""}}

规则：
1. yes 仅表示 B 区手写签字可清晰确认是目标姓名。
2. no 表示 B 区未见签字，或可清晰确认不是目标姓名。
3. uncertain 表示签字存在但看不清或无法确认。
4. 不要判断 A/C/D 区，不要判断工作单位、完成单位或公章。
5. 只返回 JSON，不要解释。""" % expected_name

        raw = await self._analyze_image_with_timeout(
            multi_llm,
            image_data,
            prompt,
            "主要完成人签字定向验证",
            timeout_sec=45,
        )
        entry = self._parse_award_signature_verification(raw)
        return {"signature_for_name": entry["status"]} if entry.get("status") else {}

    def _award_text_matches(self, expected: str, candidates: List[str]) -> bool:
        """轻量文本匹配，用于决定是否需要签字兜底。"""
        import re

        def _normalize(value: str) -> str:
            return re.sub(r"[\s\u3000（）()【】\[\]：:，,。.\-_/]", "", str(value or "")).lower()

        left = _normalize(expected)
        if not left:
            return False
        for item in candidates:
            right = _normalize(item)
            if right and (left == right or left in right or right in left):
                return True
        return False

    def _parse_award_signature_verification(self, raw_text: str) -> Dict[str, str]:
        """解析签字兜底验证 JSON。"""
        import json
        import re

        text = str(raw_text or "").strip()
        if text.startswith("```"):
            parts = text.split("```", 2)
            if len(parts) >= 2:
                text = parts[1]
                if text.startswith("json"):
                    text = text[4:]
        match = re.search(r"\{.*\}", text, re.DOTALL)
        try:
            payload = json.loads(match.group(0)) if match else {}
        except Exception:
            payload = {}
        entry = payload.get("signature_for_name") if isinstance(payload, dict) else {}
        if isinstance(entry, str):
            status = entry.strip().lower()
            return {"status": status if status in {"yes", "no", "uncertain"} else "", "reason": ""}
        if not isinstance(entry, dict):
            return {}
        status = str(entry.get("status") or "").strip().lower()
        if status not in {"yes", "no", "uncertain"}:
            return {}
        return {"status": status, "reason": str(entry.get("reason") or "").strip()}

    def _parse_award_contributor_analysis(self, raw_text: str) -> Dict[str, Any]:
        """解析主要完成人情况表专项 JSON。"""
        import json
        import re

        stripped = str(raw_text or "").strip()
        if stripped.startswith("```"):
            parts = stripped.split("```", 2)
            if len(parts) >= 2:
                stripped = parts[1]
                if stripped.startswith("json"):
                    stripped = stripped[4:]
        match = re.search(r"\{.*\}", stripped, re.DOTALL)
        try:
            payload = json.loads(match.group(0)) if match else {}
        except Exception:
            payload = {}

        def _clean_text(value: Any) -> str:
            return str(value or "").replace("\n", " ").replace("\xa0", " ").strip()

        def _clean_list(value: Any) -> List[str]:
            if isinstance(value, list):
                return [_clean_text(item) for item in value if _clean_text(item)]
            text = _clean_text(value)
            return [text] if text else []

        raw_payload = payload.get("raw") if isinstance(payload.get("raw"), dict) else payload
        verify_payload = payload.get("verify") if isinstance(payload.get("verify"), dict) else {}

        def _clean_verify(value: Any) -> str:
            text = _clean_text(value).lower()
            return text if text in {"yes", "no", "uncertain"} else ""

        return {
            "contributor_name": _clean_text(raw_payload.get("contributor_name")),
            "work_unit": _clean_text(raw_payload.get("work_unit")),
            "completion_unit": _clean_text(raw_payload.get("completion_unit")),
            "signature_names": _clean_list(raw_payload.get("signature_names") or raw_payload.get("signature_name")),
            "work_unit_stamp_units": _clean_list(raw_payload.get("work_unit_stamp_units") or raw_payload.get("work_unit_stamp_unit")),
            "completion_unit_stamp_units": _clean_list(raw_payload.get("completion_unit_stamp_units") or raw_payload.get("completion_unit_stamp_unit")),
            "all_stamp_units": [],
            "verification": {
                "name": _clean_verify(verify_payload.get("name")),
                "signature_for_name": _clean_verify(verify_payload.get("signature_for_name")),
                "work_unit": _clean_verify(verify_payload.get("work_unit")),
                "completion_unit": _clean_verify(verify_payload.get("completion_unit")),
                "work_unit_stamp": _clean_verify(verify_payload.get("work_unit_stamp")),
                "completion_unit_stamp": _clean_verify(verify_payload.get("completion_unit_stamp")),
            },
            "notes": _clean_list(raw_payload.get("notes") or payload.get("notes")),
            "raw_response": raw_text,
        }

    def _load_page_image(self, file_data: bytes):
        import io
        from PIL import Image, ImageOps

        image_data = self._pdf_to_image(file_data)
        try:
            return ImageOps.exif_transpose(Image.open(io.BytesIO(image_data))).convert("RGB")
        except Exception:
            return None

    def _crop_ratio_image(self, image, box: tuple[float, float, float, float]):
        width, height = image.size
        x1 = int(max(0.0, min(1.0, box[0])) * width)
        y1 = int(max(0.0, min(1.0, box[1])) * height)
        x2 = int(max(0.0, min(1.0, box[2])) * width)
        y2 = int(max(0.0, min(1.0, box[3])) * height)
        return image.crop((x1, y1, x2, y2))

    def _image_to_png_bytes(self, image) -> bytes:
        import io

        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return buffer.getvalue()

    def _save_special_debug_crop(self, name: str, image) -> None:
        import os

        debug_dir = "/home/tdkx/workspace/tech/debug_cropped"
        os.makedirs(debug_dir, exist_ok=True)
        image.save(f"{debug_dir}/{name}.png")

    def _save_special_polar_if_exists(self, debug_prefix: str, result: Dict[str, Any]) -> None:
        return
    
    def _pdf_to_image(self, file_data: bytes) -> bytes:
        """将 PDF 转为图片（取第一页）
        
        Args:
            file_data: PDF 文件数据
            
        Returns:
            PNG 格式的图片数据
        """
        import fitz  # PyMuPDF
        
        if file_data[:4] != b'%PDF':
            # 不是 PDF，直接返回
            return file_data
        
        try:
            doc = fitz.open(stream=file_data, filetype="pdf")
            if doc.page_count == 0:
                return file_data
            
            # 渲染第一页为图片（放大3倍，提高清晰度）
            page = doc.load_page(0)
            pix = page.get_pixmap(matrix=fitz.Matrix(3, 3))  # 3x 分辨率
            img_data = pix.tobytes("png")
            doc.close()
            return img_data
        except Exception:
            return file_data
