"""审查 Agent"""
import asyncio
import logging
import os
import time
from typing import Any, Dict, List, Optional

from src.common.llm import get_default_llm_client
from src.common.models import CheckResult, CheckStatus, ReviewResult
from src.common.vision.multimodal import MultimodalLLM
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
        self.llm = llm or get_default_llm_client()
        self.parser = document_parser
        self.rule_registry = rule_registry
        self.extractor = DocumentExtractor(self.llm)
        self._last_raw_type = ""  # 保存原始分类结果
        self._last_ocr_text = ""  # 保存 OCR 文字

    async def process(
        self,
        file_data: bytes,
        file_type: str,
        document_type: str,
        check_items: Optional[List[str]] = None,
        enable_llm_analysis: bool = False,
        **kwargs,
    ) -> ReviewResult:
        """执行审查

        Args:
            file_data: 文件数据
            file_type: 文件类型
            document_type: 文档类型（必填，由调用方指定）
            check_items: 检查项列表（可选）
            enable_llm_analysis: 是否启用 LLM 深度分析

        Returns:
            ReviewResult: 审查结果
        """
        start_time = time.time()
        logger.info("[REVIEW] 开始处理请求")
        print("[REVIEW] 开始处理请求", flush=True)

        # 1. 文档类型由请求指定，不再进行 LLM 分类
        if not document_type:
            raise ValueError("document_type 为必填参数")
        if document_type not in DOCUMENT_CONFIG:
            raise ValueError(f"不支持的 document_type: {document_type}")
        self._last_raw_type = document_type
        logger.info(f"[REVIEW] Step1 使用请求指定类型: {document_type}")
        print(f"[REVIEW] Step1 使用请求指定类型: {document_type}", flush=True)

        from src.services.review.extractor import ExtractedContent
        extracted = ExtractedContent()

        # 3. LLM 深度分析（可选，提前到规则之前，用于规则使用）
        llm_analysis = None
        if enable_llm_analysis:
            logger.info("[REVIEW] Step2.5 LLM深度分析开始（提前到规则前）")
            print("[REVIEW] Step2.5 LLM深度分析开始（提前到规则前）", flush=True)
            llm_analysis = await self._do_llm_analysis(file_data, extracted, document_type)
            # 存到 extracted 里，供规则使用
            extracted.set("llm_analysis", llm_analysis)
            logger.info("[REVIEW] Step2.5 LLM深度分析完成")
            print("[REVIEW] Step2.5 LLM深度分析完成", flush=True)

        # 4. 构建审查上下文
        context = ReviewContext(
            file_data=file_data,
            file_type=file_type,
            document_type=document_type,
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

        # 7. 如果是 unknown 类型，添加警告并提示管理员
        if document_type == "unknown":
            all_results.append(CheckResult(
                item="document_type",
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
            id=f"review_{int(time.time() * 1000)}",
            document_type=document_type,
            document_type_raw=self._last_raw_type,
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
            (document_type, extracted_content)
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
        rule_names = load_rules(context.document_type)
        
        # 创建规则实例
        rules = []
        for name in rule_names:
            rule_class = self.rule_registry.get_rule(name)
            if rule_class:
                rules.append(rule_class())
        
        # 如果没有配置规则，使用 registry 的默认链
        if not rules:
            rules = self.rule_registry.create_chain(context.document_type)

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
        document_type: str = "unknown",
    ) -> Dict[str, Any]:
        """LLM 深度分析（用于调试 OCR 效果）
        
        Args:
            file_data: 文件数据
            extracted: OCR 提取的内容
            document_type: 文档类型
            
        Returns:
            LLM 分析结果
        """
        multi_llm = MultimodalLLM(self.llm)
        logger.info(f"[LLM] 深度分析开始，document_type={document_type}")
        print(f"[LLM] 深度分析开始，document_type={document_type}", flush=True)
        
        # 将 PDF 转为图片（取第一页）
        image_data = self._pdf_to_image(file_data)
        
        ocr_text = extracted.get("text", "") or ""
        
        # 1. 文档类型由请求指定，不做 LLM 分类
        doc_type_llm = document_type
        
        # 2. LLM 通用表格内容提取（一次调用，原文照抄）
        import re
        from src.services.review.rules.config import load_llm_extract_fields
        from PIL import Image
        import io
        
        # 尝试从配置中获取关键字段
        configured_fields = load_llm_extract_fields(document_type)
        
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
