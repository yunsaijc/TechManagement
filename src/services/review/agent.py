"""审查 Agent"""
import asyncio
import json
import logging
import os
import re
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
        if normalized_doc_type == "tjdwyj":
            return await self._do_nomination_opinion_llm_analysis(file_data, doc_type, metadata or {})

        logger.info(f"[LLM] 深度分析开始，doc_type={doc_type}")
        print(f"[LLM] 深度分析开始，doc_type={doc_type}", flush=True)

        # 1. 文档类型由请求指定，不做 LLM 分类
        doc_type_llm = doc_type

        # 2. 通用表格字段提取：统一复用 FieldExtractor 的 Qwen OCR 坐标定位 + crop 二次 OCR。
        from src.services.review.rules.config import load_llm_extract_fields

        configured_fields = load_llm_extract_fields(doc_type)

        try:
            from src.common.extractors import FieldExtractor

            extractor = FieldExtractor()
            fields_llm = await extractor.extract(
                file_data=file_data,
                document_type=doc_type,
                configured_fields=configured_fields,
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
        verification_result: Dict[str, Any] = {}
        if normalized_doc_type == "wcdw":
            signature_region = self._build_completion_unit_legal_representative_signature_region(file_data)
            self._save_special_debug_crop("completion_unit_legal_representative_signature_crop", signature_region)
            signature_region_bytes = self._image_to_png_bytes(signature_region)
            sigs_result = await self._extract_signatures_from_image(signature_region_bytes)
            signature_names = self._extract_signature_names(sigs_result)
            target_values = ((metadata or {}).get("reward_review_context") or {}).get("target_values") or {}
            verification_result = await self._verify_completion_unit_legal_representative_signature_if_needed(
                image_data=signature_region_bytes,
                expected_name=str(target_values.get("legal_representative") or "").strip(),
                signature_names=signature_names,
            )
        else:
            sigs_result = await sig_extractor.extract(file_data)
        sigs_desc = sigs_result if sigs_result else "未检测到签字"
        
        return {
            "document_type_llm": doc_type_llm.strip(),
            "extracted_fields": fields_llm,
            "stamps_description": stamps_desc,
            "stamps_result": stamps_result,  # 结构化印章数据
            "signatures_result": sigs_result,
            "signatures_description": str(sigs_desc) if sigs_desc else "未检测到签字",
            "verification_result": verification_result,
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
        payload["rank"] = field_values.get("排名", "")
        payload["work_unit"] = field_values.get("工作单位", "")
        payload["completion_unit"] = field_values.get("完成单位", "")
        payload["field_ocr_result"] = field_values
        payload["stamp_regions"] = []
        payload["stamp_anchor_regions"] = dict(stamp_anchors or {})

        signature_image_data = self._build_award_contributor_signature_region(file_data)
        stamp_result, verification_result = await asyncio.gather(
            self._extract_award_contributor_stamps(
                file_data,
                anchors=stamp_anchors,
                expected_units={
                    "work_unit": payload.get("work_unit", ""),
                    "completion_unit": payload.get("completion_unit", ""),
                },
            ),
            self._verify_award_contributor_signature_if_needed(
                multi_llm=multi_llm,
                image_data=signature_image_data,
                metadata=metadata,
                payload=payload,
            ),
        )
        payload["work_unit_stamp_units"] = list(stamp_result.get("work_unit_stamp_units", []))
        payload["completion_unit_stamp_units"] = list(stamp_result.get("completion_unit_stamp_units", []))
        payload["all_stamp_units"] = list(stamp_result.get("all_stamp_units", []))
        payload["stamp_regions"] = list(stamp_result.get("regions", []))
        payload["stamp_anchor_regions"] = dict(stamp_result.get("anchor_regions") or stamp_anchors or {})
        visual_stamp_verification = await self._verify_award_contributor_stamps_visually_if_needed(
            multi_llm=multi_llm,
            file_data=file_data,
            payload=payload,
        )
        if visual_stamp_verification:
            verification_result.update(visual_stamp_verification)

        extracted_fields = {
            "排名": payload.get("rank", ""),
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
        """主要完成人签字：只看左下签字区，避免把公章/姓名章带进去。"""
        try:
            from src.common.extractors import SignatureExtractor
            from src.common.extractors.signature import normalize_signature_entries

            extractor = SignatureExtractor()
            signature_region = self._build_award_contributor_signature_region(file_data)
            result = await extractor.extract(signature_region)
            signatures = normalize_signature_entries((result or {}).get("signatures", []))
        except Exception as exc:
            logger.warning("[REVIEW] 主要完成人签字提取失败: %s", exc)
            signatures = []

        return {"signatures": signatures}

    def _build_award_contributor_signature_region(self, file_data: bytes) -> bytes:
        """裁出主要完成人情况表底部签字带，尽量排除承诺正文和右侧公章区。"""
        import io
        from PIL import Image, ImageOps

        image_data = self._pdf_to_image(file_data)
        try:
            page = Image.open(io.BytesIO(image_data))
            page = ImageOps.exif_transpose(page).convert("RGB")
        except Exception:
            return image_data

        w, h = page.size
        box = (
            int(w * 0.05),
            int(h * 0.65),
            int(w * 0.43),
            int(h * 0.88),
        )
        crop = page.crop(box)
        buf = io.BytesIO()
        crop.save(buf, format="PNG")
        return buf.getvalue()

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
        expected_units: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """主要完成人公章：统一走 StampExtractor。"""
        try:
            from src.common.extractors import StampExtractor

            extractor = StampExtractor()
            if anchors is None:
                result = await asyncio.wait_for(
                    extractor.extract_award_contributor_stamps(file_data),
                    timeout=45,
                )
            else:
                result = await asyncio.wait_for(
                    extractor.extract_award_contributor_stamps_from_anchors(
                        file_data,
                        anchors,
                        expected_units=expected_units,
                    ),
                    timeout=45,
                )
        except asyncio.TimeoutError:
            logger.warning("[REVIEW] 主要完成人公章提取超时，降级为空结果")
            result = {"anchor_regions": anchors or {}}
        except Exception as exc:
            logger.warning("[REVIEW] 主要完成人公章提取失败: %s", exc)
            result = {"anchor_regions": anchors or {}}

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
        field_names = ["排名", "姓名", "工作单位", "完成单位"]
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
        fields = await self._fallback_award_contributor_fields_from_upper_table(
            file_data=file_data,
            fields=fields,
            field_names=field_names,
        )
        return {
            name: str(fields.get(name) or "").strip()
            for name in field_names
        }

    async def _fallback_award_contributor_fields_from_upper_table(
        self,
        file_data: bytes,
        fields: Dict[str, Any],
        field_names: List[str],
    ) -> Dict[str, Any]:
        """WCR 字段定位失败时，只用上半页主表格做保守兜底。"""
        bad_fields = [
            name
            for name in field_names
            if self._is_bad_award_contributor_field(name, str((fields or {}).get(name) or ""))
        ]
        if not bad_fields:
            return fields

        page_image = self._load_review_image(file_data)
        if page_image is None:
            return fields
        width, height = page_image.size
        upper_crop = page_image.crop((
            int(width * 0.03),
            int(height * 0.06),
            int(width * 0.97),
            int(height * 0.48),
        ))
        image_data = self._image_to_png_bytes(upper_crop)
        prompt = """这是一张“主要完成人情况表”的上半页主表格区域。只读取主表格中的四个字段值。

返回严格 JSON：
{"排名": "", "姓名": "", "工作单位": "", "完成单位": ""}

规则：
1. 只读上半页主表格，不要读取下半页声明正文、签名区、公章区。
2. 不要根据上下文补全；看不清填空字符串。
3. 只返回 JSON。"""
        try:
            raw = await self._analyze_image_with_timeout(
                MultimodalLLM(self.llm),
                image_data,
                prompt,
                "主要完成人上半页字段兜底",
                timeout_sec=35,
            )
        except Exception as exc:
            logger.warning("[REVIEW] 主要完成人字段上半页兜底失败: %s", exc)
            return fields

        fallback = self._parse_award_upper_fields_json(raw)
        if not fallback:
            return fields

        merged = dict(fields or {})
        for name in bad_fields:
            value = str(fallback.get(name) or "").strip()
            if value and not self._is_bad_award_contributor_field(name, value):
                merged[name] = value
        return merged

    def _is_bad_award_contributor_field(self, field_name: str, value: str) -> bool:
        text = str(value or "").strip()
        if not text:
            return True
        if text in {"未定位", "区域太小", "裁剪区域太小"}:
            return True
        pollution_tokens = ("声明", "本单位", "本人", "按照", "承诺", "公章", "签名", "签字")
        if any(token in text for token in pollution_tokens):
            return True
        key = str(field_name or "").strip()
        if key == "排名":
            return not bool(re.fullmatch(r"\d{1,2}", text))
        if key == "姓名":
            chinese = "".join(ch for ch in text if "\u4e00" <= ch <= "\u9fff")
            if len(chinese) < 2 or len(chinese) > 4:
                return True
            if text.endswith(("名", "姓名")) and len(chinese) > 2:
                return True
        return False

    def _parse_award_upper_fields_json(self, raw_text: str) -> Dict[str, str]:
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
        if not isinstance(payload, dict):
            return {}
        return {
            name: str(payload.get(name) or "").strip()
            for name in ("排名", "姓名", "工作单位", "完成单位")
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

        signature_crop = await self._locate_first_contributor_signature_crop(file_data, page_image)
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

    async def _locate_first_contributor_signature_crop(self, file_data: bytes, page_image) -> Any:
        """基于“第一完成人签字”锚点裁剪签字区，找不到时回退固定框。"""
        default_box = (0.28, 0.64, 0.92, 0.88)
        default_crop = self._crop_ratio_image(page_image, default_box)
        try:
            from src.common.extractors import StampExtractor

            extractor = StampExtractor()
            image_data = self._pdf_to_image(file_data)
            ocr_result = await extractor._run_qwen_ocr(
                image_data=image_data,
                prompt="请对这张第一页执行 OCR，返回所有文字及其位置。",
                debug_name="first_contributor_page_ocr",
                task="advanced_recognition",
                enable_rotate=False,
            )
            label_bbox = self._find_first_contributor_signature_label_bbox(
                words=list(ocr_result.get("words_info") or []),
                extractor=extractor,
                img_w=page_image.size[0],
                img_h=page_image.size[1],
            )
            if not label_bbox:
                return default_crop
            crop = self._crop_first_contributor_signature_from_label(page_image, label_bbox)
            self._save_special_debug_crop("first_contributor_signature_anchor_crop", crop)
            return crop
        except Exception as exc:
            logger.warning("[REVIEW] 第一完成人签字锚点定位失败: %s", exc)
            return default_crop

    def _find_first_contributor_signature_label_bbox(
        self,
        words: List[Dict[str, Any]],
        extractor: Any,
        img_w: int,
        img_h: int,
    ) -> Optional[Dict[str, float]]:
        targets = ("第一完成人签字", "第一完成人签名")
        exact: List[tuple[float, Dict[str, float]]] = []
        partial: List[tuple[float, Dict[str, float]]] = []
        for word in words:
            box = extractor._word_bbox(word)
            if box["y1"] < img_h * 0.55:
                continue
            text_norm = extractor._normalize_text(word.get("text"))
            if not text_norm:
                continue
            for target in targets:
                if target in text_norm:
                    sliced = extractor._slice_word_by_normalized_substring(word, target)
                    sliced_box = extractor._merge_word_bboxes([sliced])
                    if sliced_box:
                        score = box["y1"] - box["x1"] * 0.001
                        exact.append((score, sliced_box))
                    break
            else:
                if "第一完成人" not in text_norm:
                    continue
                tail_word = self._find_nearby_text_word(
                    words=words,
                    extractor=extractor,
                    base_word=word,
                    candidates=("签字", "签名"),
                    img_h=img_h,
                )
                merged_words = [extractor._slice_word_by_normalized_substring(word, "第一完成人")]
                if tail_word is not None:
                    tail_text = extractor._normalize_text(tail_word.get("text"))
                    tail_target = "签字" if "签字" in tail_text else "签名"
                    merged_words.append(extractor._slice_word_by_normalized_substring(tail_word, tail_target))
                merged_box = extractor._merge_word_bboxes(merged_words)
                if merged_box:
                    score = box["y1"] - box["x1"] * 0.001
                    partial.append((score, merged_box))
        if exact:
            exact.sort(key=lambda item: item[0], reverse=True)
            return exact[0][1]
        if partial:
            partial.sort(key=lambda item: item[0], reverse=True)
            return partial[0][1]
        return None

    def _find_nearby_text_word(
        self,
        words: List[Dict[str, Any]],
        extractor: Any,
        base_word: Dict[str, Any],
        candidates: tuple[str, ...],
        img_h: int,
    ) -> Optional[Dict[str, Any]]:
        base_box = extractor._word_bbox(base_word)
        base_center_y = (base_box["y1"] + base_box["y2"]) / 2.0
        matches: List[tuple[float, Dict[str, Any]]] = []
        for word in words:
            if word is base_word:
                continue
            text_norm = extractor._normalize_text(word.get("text"))
            if not text_norm or not any(target in text_norm for target in candidates):
                continue
            box = extractor._word_bbox(word)
            if box["y1"] < img_h * 0.55:
                continue
            center_y = (box["y1"] + box["y2"]) / 2.0
            if abs(center_y - base_center_y) > 48:
                continue
            gap = abs(box["x1"] - base_box["x2"])
            matches.append((gap, word))
        if not matches:
            return None
        matches.sort(key=lambda item: item[0])
        return matches[0][1]

    def _crop_first_contributor_signature_from_label(self, page_image, label_bbox: Dict[str, float]):
        img_w, img_h = page_image.size
        label_width = max(1.0, label_bbox["x2"] - label_bbox["x1"])
        label_height = max(1.0, label_bbox["y2"] - label_bbox["y1"])
        left = max(0, int(label_bbox["x2"] - label_width * 0.08))
        top = max(0, int(label_bbox["y1"] - label_height * 0.9))
        right = min(img_w, int(max(label_bbox["x2"] + img_w * 0.22, img_w * 0.92)))
        bottom = min(img_h, int(label_bbox["y2"] + label_height * 3.4))
        if right - left < 40 or bottom - top < 40:
            return self._crop_ratio_image(page_image, (0.28, 0.64, 0.92, 0.88))
        return page_image.crop((left, top, right, bottom))

    def _build_completion_unit_legal_representative_signature_region(self, file_data: bytes):
        """主要完成单位情况表底部法定代表人签名/签章区。"""
        page_image = self._load_page_image(file_data)
        if page_image is None:
            import io
            from PIL import Image

            return Image.open(io.BytesIO(self._pdf_to_image(file_data))).convert("RGB")
        return self._crop_ratio_image(page_image, (0.06, 0.66, 0.58, 0.93))

    async def _verify_completion_unit_legal_representative_signature_if_needed(
        self,
        image_data: bytes,
        expected_name: str,
        signature_names: List[str],
    ) -> Dict[str, Any]:
        """主要完成单位：只核验底部“法定代表人签名”右侧手写/签章姓名。"""
        if not expected_name or self._award_text_matches(expected_name, signature_names):
            return {}
        multi_llm = MultimodalLLM(self.llm)
        prompt = """这是“主要完成单位情况表”底部的法定代表人签名区域裁剪图。
目标姓名：%s

请只看“法定代表人签名:”右侧的手写签名或姓名签章，不要读取正文、日期、表格字段、目标姓名，也不要根据上下文猜。

返回严格 JSON：
{"legal_representative_signature": {"status": "yes|no|uncertain", "reason": ""}}

规则：
1. yes 仅表示右侧签名/签章的字形本身可以逐字清晰读成目标姓名。
2. no 表示未见签名/签章，或可见签名/签章不是目标姓名，或只能读成其他姓名，或不能逐字读成目标姓名。
3. uncertain 仅用于确有签名/签章但图像太模糊，无法判断具体姓名。
4. 严禁因为目标姓名出现在提示词或表格字段中就返回 yes；必须以签名区域字形为准。
5. 只返回 JSON，不要解释。""" % expected_name
        raw = await self._analyze_image_with_timeout(
            multi_llm,
            image_data,
            prompt,
            "主要完成单位法定代表人签名定向验证",
            timeout_sec=45,
        )
        entry = self._parse_named_verification(raw, "legal_representative_signature")
        return {"legal_representative_signature": entry} if entry.get("status") else {}

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

    async def _do_nomination_opinion_llm_analysis(
        self,
        file_data: bytes,
        doc_type: str,
        metadata: Dict[str, Any],
    ) -> Dict[str, Any]:
        """提名意见表：只裁右下提名单位公章区做红章专项核验。"""
        page_image = self._load_page_image(file_data)
        if page_image is None:
            return {"document_type_llm": doc_type, "extracted_fields": {}, "stamps_description": "未检测到印章", "stamps_result": {"stamps": []}, "signatures_result": {"signatures": []}, "signatures_description": "未检测到签字", "verification_result": {}}

        stamp_crop = self._crop_ratio_image(page_image, (0.48, 0.68, 0.96, 0.96))
        wide_crop = self._crop_ratio_image(page_image, (0.36, 0.62, 0.98, 0.98))
        enhanced_crop = self._enhance_red_stamp(stamp_crop)
        stamp_quality = self._analyze_red_stamp_quality(wide_crop)
        self._save_special_debug_crop("nomination_unit_stamp_crop", stamp_crop)
        self._save_special_debug_crop("nomination_unit_stamp_crop_wide", wide_crop)
        self._save_special_debug_crop("nomination_unit_stamp_red_enhanced", enhanced_crop)

        enhanced_result = await self._extract_stamps_from_image(enhanced_crop, debug_prefix="nomination_unit")
        stamp_units = self._extract_stamp_units(enhanced_result)
        target_values = (metadata.get("reward_review_context") or {}).get("target_values") or {}
        expected_unit = str(target_values.get("nomination_unit_name") or "").strip()
        verification_result = await self._verify_target_nomination_unit_stamp_if_needed(
            stamp_crop=stamp_crop,
            expected_unit=expected_unit,
            stamp_units=stamp_units,
        )

        if expected_unit and (verification_result.get("nomination_unit_stamp") or {}).get("status") == "yes":
            stamp_units = [expected_unit]
            enhanced_result = {
                "stamps": [
                    {
                        "text": expected_unit,
                        "unit": expected_unit,
                        "bbox": None,
                        "confidence": 0.9,
                        "location": "提名单位（公章）",
                    }
                ],
                "raw": enhanced_result.get("raw", ""),
            }

        return {
            "document_type_llm": doc_type,
            "extracted_fields": {},
            "stamps_description": "；".join(stamp_units) if stamp_units else "未检测到印章",
            "stamps_result": enhanced_result,
            "stamp_quality": stamp_quality,
            "signatures_result": {"signatures": []},
            "signatures_description": "未检测到签字",
            "verification_result": verification_result,
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
        target_values = (metadata.get("reward_review_context") or {}).get("target_values") or {}
        verification_result = await self._verify_target_signature_if_needed(
            image_data=rep_bytes,
            expected_name=str(target_values.get("legal_representative") or "").strip(),
            signature_names=signature_names,
            verification_key="legal_representative_signature",
            task_name="企业声明法定代表人定向验证",
            prompt_label="法定代表人签名/签章区域",
        )
        enterprise_stamp_verification = await self._verify_target_enterprise_stamp_if_needed(
            stamp_crop=company_stamp_crop,
            expected_unit=str(target_values.get("enterprise_name") or "").strip(),
            stamp_units=stamp_units,
        )
        if enterprise_stamp_verification:
            verification_result.update(enterprise_stamp_verification)

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

    async def _verify_target_enterprise_stamp_if_needed(
        self,
        stamp_crop,
        expected_unit: str,
        stamp_units: List[str],
    ) -> Dict[str, Any]:
        """企业声明企业公章：先 raw 比对，不通过时再做定向复核。"""
        if not expected_unit or self._text_exact_matches(expected_unit, stamp_units):
            return {}

        crop_bytes = self._image_to_png_bytes(stamp_crop)
        primary = await self._verify_target_enterprise_stamp(
            crop_bytes=crop_bytes,
            expected_unit=expected_unit,
            polar_bytes=None,
            task_name="企业声明企业公章定向验证",
        )
        if primary.get("status") in {"yes", "no"}:
            return {"enterprise_stamp": primary}

        polar_bytes = await self._build_enterprise_stamp_soft_polar_bytes(stamp_crop)
        if not polar_bytes:
            return {"enterprise_stamp": primary} if primary.get("status") else {}

        retry = await self._verify_target_enterprise_stamp(
            crop_bytes=crop_bytes,
            expected_unit=expected_unit,
            polar_bytes=polar_bytes,
            task_name="企业声明企业公章定向复核",
        )
        final_entry = retry if retry.get("status") else primary
        return {"enterprise_stamp": final_entry} if final_entry.get("status") else {}

    async def _verify_target_nomination_unit_stamp_if_needed(
        self,
        stamp_crop,
        expected_unit: str,
        stamp_units: List[str],
    ) -> Dict[str, Any]:
        """提名意见表：右下公章 crop 定向核验。"""
        if not expected_unit or self._text_exact_matches(expected_unit, stamp_units):
            return {}
        multi_llm = MultimodalLLM(self.llm)
        prompt = """你在做提名意见表公章定向核验。
目标提名单位：%s

图中是页面右下角“提名单位（公章）”附近裁剪区域。
只判断红色公章上的单位名称是否就是目标提名单位，不要根据正文、表格字段或提示词补全。

返回严格 JSON：
{"nomination_unit_stamp": {"status": "yes|no|uncertain", "reason": ""}}

规则：
1. yes 仅表示红色公章文字可以清晰确认与目标提名单位一致。
2. no 表示未见对应红章，或可清晰确认红章单位不是目标提名单位。
3. uncertain 表示确有红章但看不清。
4. 只返回 JSON，不要解释。""" % expected_unit
        raw = await self._analyze_image_with_timeout(
            multi_llm,
            self._image_to_png_bytes(stamp_crop),
            prompt,
            "提名意见表提名单位公章定向验证",
            timeout_sec=45,
        )
        entry = self._parse_named_verification(raw, "nomination_unit_stamp")
        if entry.get("status") == "no" and self._is_contradictory_nomination_stamp_no(entry):
            return {}
        return {"nomination_unit_stamp": entry} if entry.get("status") else {}

    def _is_contradictory_nomination_stamp_no(self, entry: Dict[str, str]) -> bool:
        """模型偶尔 reason 说一致但 status=no；这种 no 不能推翻 OCR。"""
        reason = str((entry or {}).get("reason") or "")
        if any(token in reason for token in ("不一致", "不相符", "不匹配", "不是目标", "无法确认")):
            return False
        positive_tokens = (
            "与目标单位一致",
            "与目标提名单位一致",
            "与目标一致",
            "单位名称一致",
            "目标单位一致",
        )
        if any(token in reason for token in positive_tokens):
            return True
        return bool(re.search(r"与目标(?:提名)?单位[^，。；;]*一致", reason))

    def _text_exact_matches(self, expected: str, candidates: List[str]) -> bool:
        import re

        def _normalize(value: str) -> str:
            return re.sub(r"[\s\u3000（）()【】\[\]：:，,。.\-_/]", "", str(value or "")).lower()

        left = _normalize(expected)
        if not left:
            return False
        return any(_normalize(item) == left for item in candidates if str(item or "").strip())

    async def _verify_target_enterprise_stamp(
        self,
        crop_bytes: bytes,
        expected_unit: str,
        polar_bytes: Optional[bytes],
        task_name: str,
    ) -> Dict[str, str]:
        import base64
        from langchain_core.messages import HumanMessage

        prompt = (
            "你在做企业公章定向核验。\n"
            f"目标单位：{expected_unit}\n"
            "图1是公章原始裁剪图。"
            + ("图2是同一枚公章的极坐标展开图。\n" if polar_bytes else "\n")
            + "只判断这枚公章中的单位名称是否就是目标单位，不要根据上下文补全，不要纠错，不要猜附近正文。\n"
            + "如果能确认完全是目标单位，返回 yes；如果能确认不是，返回 no；看不清或无法确认，返回 uncertain。\n"
            + "严格返回 JSON：{\"enterprise_stamp\": {\"status\": \"yes|no|uncertain\", \"reason\": \"\"}}"
        )
        content: List[Dict[str, Any]] = [
            {"type": "text", "text": prompt},
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{base64.b64encode(self._compress_image_for_llm(crop_bytes)).decode('utf-8')}"},
            },
        ]
        if polar_bytes:
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{base64.b64encode(self._compress_image_for_llm(polar_bytes)).decode('utf-8')}"},
                }
            )

        timeout = 45
        logger.info(f"[LLM] {task_name} 开始 (timeout={timeout}s)")
        print(f"[LLM] {task_name} 开始", flush=True)
        try:
            raw = await asyncio.wait_for(
                self.llm.ainvoke([HumanMessage(content=content)]),
                timeout=timeout,
            )
            logger.info(f"[LLM] {task_name} 完成")
            print(f"[LLM] {task_name} 完成", flush=True)
        except asyncio.TimeoutError as exc:
            msg = f"{task_name} 超时（>{timeout}s）"
            logger.error(f"[LLM] {msg}")
            print(f"[LLM] {msg}", flush=True)
            raise RuntimeError(msg) from exc

        raw_text = raw.content if hasattr(raw, "content") else str(raw)
        return self._parse_named_verification(str(raw_text), "enterprise_stamp")

    async def _build_enterprise_stamp_soft_polar_bytes(self, stamp_crop) -> Optional[bytes]:
        try:
            from PIL import Image
            import cv2
            import numpy as np
            from src.common.extractors import StampExtractor

            extractor = StampExtractor()
            tight_crop = extractor._crop_largest_red_stamp_component(stamp_crop)
            polar_raw_source = tight_crop or stamp_crop
            circles = extractor._detect_stamp_circle_candidates(polar_raw_source)
            if not circles:
                return None

            def _build_source(image: Image.Image, red_gain: float, sharpen_amount: float) -> Image.Image:
                rgb = np.array(image.convert("RGB")).astype(np.float32)
                red = rgb[:, :, 0]
                green = rgb[:, :, 1]
                blue = rgb[:, :, 2]
                dominance = np.maximum(0.0, red - np.maximum(green, blue))
                dominance = np.clip(dominance * red_gain, 0.0, 255.0)
                gray = 255.0 - dominance
                gray = cv2.medianBlur(gray.astype(np.uint8), 3)
                gray = cv2.resize(
                    gray,
                    (max(1, image.size[0] * 2), max(1, image.size[1] * 2)),
                    interpolation=cv2.INTER_CUBIC,
                )
                if sharpen_amount > 0:
                    blur = cv2.GaussianBlur(gray, (0, 0), 1.1)
                    gray = cv2.addWeighted(gray, 1.0 + sharpen_amount, blur, -sharpen_amount, 0)
                gray = cv2.copyMakeBorder(gray, 24, 24, 24, 24, cv2.BORDER_CONSTANT, value=255)
                return Image.fromarray(gray).convert("RGB")

            async def _score_candidate(candidate_name: str, polar_image: Image.Image) -> tuple[tuple[int, int, float], bytes]:
                polar_bytes = extractor._image_to_png_bytes(polar_image)
                ocr_inputs: List[tuple[str, bytes]] = [(candidate_name, polar_bytes)]
                ocr_inputs.extend(extractor._build_polar_segments(polar_image))
                results = await asyncio.gather(
                    *[
                        extractor._run_qwen_ocr(
                            image_data=image_data,
                            prompt="请对这张公章文字展开图执行 OCR，只返回图片中实际可见文字，不要纠错，不要补全。",
                            debug_name=f"enterprise_verify_{candidate_name}_{name}_ocr",
                            task="advanced_recognition",
                            enable_rotate=False,
                        )
                        for name, image_data in ocr_inputs
                    ],
                    return_exceptions=True,
                )

                full_texts: List[str] = []
                ordered_segment_texts: List[str] = []
                for (name, _), result in zip(ocr_inputs, results):
                    if isinstance(result, Exception):
                        continue
                    texts = extractor._extract_stamp_unit_texts(result, variant_name=name)
                    if name == candidate_name:
                        full_texts = [extractor._normalize_stamp_unit_text(text) for text in texts if extractor._normalize_stamp_unit_text(text)]
                    elif name.startswith("polar_upper_seg"):
                        merged = extractor._merge_ordered_stamp_texts(texts)
                        if merged:
                            ordered_segment_texts.append(merged)
                primary_text = full_texts[0] if full_texts else extractor._merge_overlapping_stamp_segments(ordered_segment_texts)
                score = (
                    len(primary_text or ""),
                    sum(1 for item in ordered_segment_texts if item),
                    1.0 - extractor._polar_edge_cut_penalty(polar_image),
                )
                return score, polar_bytes

            best_score: tuple[int, int, float] = (-1, -1, -1.0)
            best_bytes: Optional[bytes] = None
            configs = (
                ("soft_base", 2.2, 0.0),
                ("soft_sharp", 2.4, 0.55),
            )
            for source_name, red_gain, sharpen_amount in configs:
                source_image = _build_source(polar_raw_source, red_gain=red_gain, sharpen_amount=sharpen_amount)
                gray = np.array(source_image.convert("L"))
                for circle_name, circle in circles:
                    cx, cy, radius = circle
                    band = extractor._unwrap_upper_annulus(
                        gray,
                        cx * 2.0 + 24.0,
                        cy * 2.0 + 24.0,
                        radius * 2.0,
                        inner_ratio=0.37,
                        outer_ratio=0.985,
                        start_deg=-236.0,
                        end_deg=56.0,
                    )
                    if band is None:
                        continue
                    band = extractor._trim_unwrapped_band_rows(band)
                    band = extractor._trim_unwrapped_band_cols(band)
                    if band is None:
                        continue
                    band = cv2.resize(
                        band,
                        (max(1600, band.shape[1] * 2), max(320, band.shape[0] * 3)),
                        interpolation=cv2.INTER_CUBIC,
                    )
                    band = cv2.copyMakeBorder(band, 28, 28, 28, 28, cv2.BORDER_CONSTANT, value=255)
                    polar_image = Image.fromarray(band).convert("RGB")
                    score, polar_bytes = await _score_candidate(f"{source_name}_{circle_name}_soft_topsafe", polar_image)
                    if score > best_score:
                        best_score = score
                        best_bytes = polar_bytes

            if best_bytes:
                from PIL import Image
                self._save_special_debug_crop("enterprise_stamp_verify_polar", Image.open(__import__("io").BytesIO(best_bytes)).convert("RGB"))
            return best_bytes
        except Exception as exc:
            logger.warning("[REVIEW] 企业声明企业公章 polar 生成失败: %s", exc)
            return None

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
    ) -> Dict[str, Any]:
        """仅在签字 raw 对比未通过时，使用目标姓名做定向兜底。"""
        reward_context = metadata.get("reward_review_context") if isinstance(metadata, dict) else {}
        target_values = reward_context.get("target_values") if isinstance(reward_context, dict) else {}
        expected_name = str((target_values or {}).get("name") or "").strip()
        if not expected_name:
            return {}

        contributor_name = str(payload.get("contributor_name") or "").strip()
        signature_names = [str(item).strip() for item in payload.get("signature_names", []) if str(item).strip()]
        prompt = """这是一张“主要完成人情况表”的签名区裁剪图，只判断图中是否存在可清晰确认的亲笔手写签名。
目标姓名：%s

返回严格 JSON：
{"signature_for_name": {"status": "yes|no|uncertain", "kind": "handwritten|name_stamp|printed|empty|other", "reason": ""}}

规则：
1. yes 仅表示图中能看到连续笔迹形成的亲笔手写签名，而且字形本身可清晰读成目标姓名。
2. no 表示图中未见亲笔手写签名，或只有姓名章、签名章、私章、方章、红章、日期、打印字、盖章痕迹，或可清晰确认不是目标姓名。
3. uncertain 仅用于：确有亲笔手写笔迹，但看不清，无法确认是否为目标姓名。
4. 严禁根据目标姓名去猜；如果字形本身读不出来，就不能返回 yes。
5. 红色方章/姓名章/签名章绝不是亲笔签名，必须返回 no。
6. 只返回 JSON，不要解释。""" % expected_name

        raw = await self._analyze_image_with_timeout(
            multi_llm,
            image_data,
            prompt,
            "主要完成人签字定向验证",
            timeout_sec=45,
        )
        entry = self._parse_award_signature_verification(raw)
        return {"signature_for_name": entry} if entry.get("status") else {}

    async def _verify_award_contributor_stamps_visually_if_needed(
        self,
        multi_llm: MultimodalLLM,
        file_data: bytes,
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        """当公章 OCR 未直接匹配时，保守使用红章视觉复核兜底。"""
        roles = [
            ("work_unit", "work_unit_stamp", "工作单位", str(payload.get("work_unit") or "").strip()),
            ("completion_unit", "completion_unit_stamp", "完成单位", str(payload.get("completion_unit") or "").strip()),
        ]
        targets = [
            (role_key, verify_key, role_label, expected)
            for role_key, verify_key, role_label, expected in roles
            if expected
            and not self._is_composite_award_unit(expected)
            and not self._award_text_matches(expected, list(payload.get(f"{role_key}_stamp_units", []) or []))
        ]
        if not targets:
            return {}

        page_image = self._load_review_image(file_data)
        if page_image is None:
            return {}
        stamp_images = self._build_award_contributor_red_stamp_images(page_image, payload)
        if not stamp_images:
            return {}

        out: Dict[str, Any] = {}
        for role_key, verify_key, role_label, expected in targets:
            candidates = self._select_stamp_visual_candidates(role_key, stamp_images)
            for index, image_data in enumerate(candidates[:2], start=1):
                prompt = """这是一张从“主要完成人情况表”中裁出的红色公章图，只判断它是否为目标单位的公章。
目标%s：%s

返回严格 JSON：
{"status": "yes|no|uncertain", "reason": ""}

规则：
1. yes 仅表示图中红色公章文字能清楚读成目标单位全称；缺字、少字、多字、只包含上级/下级单位都不能 yes。
2. no 表示能清楚看出不是目标单位，或是姓名章/签字章/其他印章。
3. uncertain 表示公章太淡、被遮挡、被裁切、文字不完整，无法确认。
4. 不要根据目标单位补全，不要把“北京大学”和“北京大学物理学院”当作一致。
5. 只返回 JSON。""" % (role_label, expected)
                try:
                    raw = await self._analyze_image_with_timeout(
                        multi_llm,
                        image_data,
                        prompt,
                        f"主要完成人{role_label}公章视觉复核{index}",
                        timeout_sec=30,
                    )
                except Exception as exc:
                    logger.warning("[REVIEW] %s公章视觉复核失败: %s", role_label, exc)
                    continue
                entry = self._parse_status_reason_json(raw)
                if entry.get("status") == "yes" and not self._is_contradictory_visual_yes(entry):
                    entry["source"] = "red_stamp_visual_fallback"
                    out[verify_key] = entry
                    units_key = f"{role_key}_stamp_units"
                    units = [str(item).strip() for item in payload.get(units_key, []) if str(item).strip()]
                    if expected not in units:
                        units.append(expected)
                    payload[units_key] = units
                    all_units = [str(item).strip() for item in payload.get("all_stamp_units", []) if str(item).strip()]
                    if expected not in all_units:
                        all_units.append(expected)
                    payload["all_stamp_units"] = all_units
                    break
        return out

    def _is_composite_award_unit(self, text: str) -> bool:
        """复合单位要求全部覆盖，不能让视觉兜底按“匹配之一”放过。"""
        raw = str(text or "").strip()
        if not raw:
            return False
        depth = 0
        for ch in raw:
            if ch in "（(":
                depth += 1
                continue
            if ch in "）)" and depth > 0:
                depth -= 1
                continue
            if depth == 0 and ch in "/／、;；，,":
                return True
        unit_suffixes = (
            "股份有限公司",
            "有限责任公司",
            "有限公司",
            "研究所",
            "研究院",
            "大学",
            "学院",
            "医院",
            "公司",
            "中心",
            "总站",
            "集团",
            "学校",
        )
        for match in re.finditer(r"[（(]([^）)]+)[）)]", raw):
            inner = match.group(1).strip()
            before = raw[: match.start()].strip()
            after = raw[match.end() :].strip()
            if before and not after and inner.endswith(unit_suffixes):
                return True
        return False

    def _is_contradictory_visual_yes(self, entry: Dict[str, str]) -> bool:
        """模型偶尔会 status=yes 但 reason 明确说不一致，这种 yes 不能采纳。"""
        reason = str((entry or {}).get("reason") or "")
        negative_tokens = (
            "不一致",
            "不完全一致",
            "不能视为",
            "不能认为",
            "不能判定",
            "不是目标",
            "不是该目标",
            "并非目标",
            "不相符",
            "不匹配",
            "无法确认",
            "无法确定",
        )
        return any(token in reason for token in negative_tokens)

    def _load_review_image(self, file_data: bytes):
        import io
        from PIL import Image, ImageOps

        try:
            image_data = self._pdf_to_image(file_data)
            return ImageOps.exif_transpose(Image.open(io.BytesIO(image_data))).convert("RGB")
        except Exception as exc:
            logger.warning("[REVIEW] 页面图片加载失败: %s", exc)
            return None

    def _build_award_contributor_red_stamp_images(self, page_image, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        import io
        from PIL import Image

        def _crop_bbox(bbox: Dict[str, Any]):
            width, height = page_image.size
            try:
                x1 = int(max(0, float(bbox["x1"]) * width))
                y1 = int(max(0, float(bbox["y1"]) * height))
                x2 = int(min(width, float(bbox["x2"]) * width))
                y2 = int(min(height, float(bbox["y2"]) * height))
            except Exception:
                return None
            if x2 <= x1 or y2 <= y1:
                return None
            return page_image.crop((x1, y1, x2, y2))

        items: List[Dict[str, Any]] = []
        for region in payload.get("stamp_regions", []) or []:
            if not isinstance(region, dict) or not isinstance(region.get("bbox"), dict):
                continue
            crop = _crop_bbox(region["bbox"])
            red_image = self._isolate_red_stamp_object(crop) if crop is not None else None
            if red_image is None:
                continue
            buf = io.BytesIO()
            red_image.save(buf, format="PNG")
            items.append(
                {
                    "role": str(region.get("role") or ""),
                    "image": buf.getvalue(),
                    "bbox": region.get("bbox"),
                }
            )
        return items

    def _select_stamp_visual_candidates(self, role_key: str, stamp_images: List[Dict[str, Any]]) -> List[bytes]:
        exact = [item["image"] for item in stamp_images if item.get("role") == role_key and item.get("image")]
        rest = [item["image"] for item in stamp_images if item.get("role") != role_key and item.get("image")]
        return exact + rest

    def _isolate_red_stamp_object(self, image):
        if image is None:
            return None
        from PIL import Image, ImageFilter, ImageOps

        rgb = image.convert("RGB")
        width, height = rgb.size
        pixels = rgb.load()
        xs: List[int] = []
        ys: List[int] = []
        for y in range(height):
            for x in range(width):
                r, g, b = pixels[x, y]
                if r >= 105 and r >= g + 22 and r >= b + 22:
                    xs.append(x)
                    ys.append(y)
        if len(xs) < 80:
            return None
        pad_x = max(8, int(width * 0.04))
        pad_y = max(8, int(height * 0.04))
        x1 = max(0, min(xs) - pad_x)
        y1 = max(0, min(ys) - pad_y)
        x2 = min(width, max(xs) + pad_x)
        y2 = min(height, max(ys) + pad_y)
        if x2 <= x1 or y2 <= y1:
            return None
        crop = rgb.crop((x1, y1, x2, y2))
        out = Image.new("RGB", crop.size, "white")
        src = crop.load()
        dst = out.load()
        for y in range(crop.size[1]):
            for x in range(crop.size[0]):
                r, g, b = src[x, y]
                if r >= 105 and r >= g + 22 and r >= b + 22:
                    dst[x, y] = (180, 0, 0)
        out = out.filter(ImageFilter.MedianFilter(size=3))
        scale = 2
        out = out.resize((max(1, out.size[0] * scale), max(1, out.size[1] * scale)), Image.LANCZOS)
        return ImageOps.expand(out, border=24, fill="white")

    def _parse_status_reason_json(self, raw_text: str) -> Dict[str, str]:
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
        if not isinstance(payload, dict):
            return {}
        status = str(payload.get("status") or "").strip().lower()
        if status not in {"yes", "no", "uncertain"}:
            return {}
        return {"status": status, "reason": str(payload.get("reason") or "").strip()}

    def _award_text_matches(self, expected: str, candidates: List[str]) -> bool:
        """严格文本匹配，用于决定是否需要签字兜底。"""
        import re

        def _normalize(value: str) -> str:
            return re.sub(r"[\s\u3000（）()【】\[\]：:，,。.\-_/]", "", str(value or "")).lower()

        left = _normalize(expected)
        if not left:
            return False
        for item in candidates:
            right = _normalize(item)
            if right and left == right:
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

    def _enhance_red_stamp(self, image):
        """保留红章像素、弱化黑字和表格线，供公章 OCR 使用。"""
        import cv2
        import numpy as np
        from PIL import Image

        rgb = np.array(image.convert("RGB"))
        r = rgb[:, :, 0].astype(np.int16)
        g = rgb[:, :, 1].astype(np.int16)
        b = rgb[:, :, 2].astype(np.int16)
        mask = (r > 110) & (r - g > 25) & (r - b > 25)
        out = np.full_like(rgb, 255)
        out[mask] = [220, 0, 0]
        mask_u8 = (mask.astype(np.uint8) * 255)
        kernel = np.ones((2, 2), np.uint8)
        mask_u8 = cv2.morphologyEx(mask_u8, cv2.MORPH_CLOSE, kernel, iterations=1)
        mask_u8 = cv2.dilate(mask_u8, kernel, iterations=1)
        out[mask_u8 > 0] = [220, 0, 0]
        return Image.fromarray(out)

    def _analyze_red_stamp_quality(self, image) -> Dict[str, Any]:
        """估计红章是否存在，以及是否过淡到无法稳定 OCR。"""
        import numpy as np

        rgb = np.array(image.convert("RGB"))
        r = rgb[:, :, 0].astype(np.int16)
        g = rgb[:, :, 1].astype(np.int16)
        b = rgb[:, :, 2].astype(np.int16)
        loose = (r > 80) & (r - g > 8) & (r - b > 8)
        current = (r > 110) & (r - g > 25) & (r - b > 25)
        strict = (r > 140) & (r - g > 45) & (r - b > 45)
        loose_count = int(loose.sum())
        current_count = int(current.sum())
        strict_count = int(strict.sum())
        current_ratio = float(current_count / max(1, loose_count))
        strict_ratio = float(strict_count / max(1, loose_count))
        red_present = loose_count >= 1000
        low_quality = red_present and (
            current_count < 800 or current_ratio < 0.35 or strict_ratio < 0.08
        )
        return {
            "red_present": red_present,
            "low_quality": low_quality,
            "loose_red_pixels": loose_count,
            "current_red_pixels": current_count,
            "strict_red_pixels": strict_count,
            "current_to_loose_ratio": round(current_ratio, 4),
            "strict_to_loose_ratio": round(strict_ratio, 4),
        }

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
        from src.common.file_handler.pdf_renderer import render_pdf_first_page

        return render_pdf_first_page(file_data, zoom=3.0)
