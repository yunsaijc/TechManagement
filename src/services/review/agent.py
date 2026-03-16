"""审查 Agent"""
import time
from typing import Any, Dict, List, Optional

from src.common.llm import get_default_llm_client
from src.common.models import CheckResult, CheckStatus, ReviewResult
from src.common.vision import MultimodalLLM
from src.services.review.extractor import DocumentExtractor
from src.services.review.rules import ReviewContext, RuleRegistry
from src.services.review.rules.config import load_rules


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
        document_type: str = None,
        check_items: Optional[List[str]] = None,
        enable_llm_analysis: bool = False,
        **kwargs,
    ) -> ReviewResult:
        """执行审查

        Args:
            file_data: 文件数据
            file_type: 文件类型
            document_type: 文档类型（可选，自动识别）
            check_items: 检查项列表（可选）
            enable_llm_analysis: 是否启用 LLM 深度分析

        Returns:
            ReviewResult: 审查结果
        """
        start_time = time.time()

        # 1. 文档分类（直接用 LLM，不依赖 OCR）
        if not document_type:
            document_type, extracted = await self._classify_document(file_data)
        else:
            # 指定了文档类型，不需要 OCR
            from src.services.review.extractor import ExtractedContent
            extracted = ExtractedContent()

        # 3. 构建审查上下文
        context = ReviewContext(
            file_data=file_data,
            file_type=file_type,
            document_type=document_type,
            extracted=extracted,
            metadata=kwargs.get("metadata", {}),
        )

        # 4. 加载并运行规则
        rule_results = await self._run_rules(context, check_items)

        # 5. LLM 补充（可选）
        llm_results = await self._llm_check(context, check_items)

        # 6. LLM 深度分析（可选，用于调试）
        llm_analysis = None
        if enable_llm_analysis:
            llm_analysis = await self._do_llm_analysis(file_data, extracted, document_type)

        # 7. 结果聚合
        all_results = rule_results + llm_results

        # 7. 如果是 unknown 类型，添加警告并提示管理员
        if document_type == "unknown":
            all_results.append(CheckResult(
                item="document_type",
                status=CheckStatus.WARNING,
                message=f"无法识别文档类型（LLM原始结果：{self._last_raw_type}），请管理员新增类别后重新审查",
                evidence={"raw_type": self._last_raw_type},
                confidence=1.0,
            ))
            summary = "审查中断：文档类型无法识别，请管理员新增类别"
            suggestions = ["请管理员在系统中新增文档类型后重新提交审查"]

        else:
            summary = self._generate_summary(all_results)
            suggestions = self._generate_suggestions(all_results)

        return ReviewResult(
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

    async def _classify_document(self, file_data: bytes) -> tuple[str, Any]:
        """文档分类 - 直接用 LLM 识别（不依赖 OCR）
        
        Returns:
            (document_type, extracted_content)
        """
        from src.common.vision import MultimodalLLM
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
            result = await multi_llm.analyze_image(image_data, prompt)
            doc_type = self._match_document_type(result)
            self._last_raw_type = result.strip()
        except Exception:
            doc_type = "unknown"
            self._last_raw_type = "LLM分类失败"
        
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
        llm_items = ["consistency", "completeness"]
        if check_items:
            llm_items = [i for i in llm_items if i in check_items]

        results = []

        if "consistency" in llm_items:
            result = await self._check_consistency(context)
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
            result = await multi_llm.analyze_image(context.file_data, prompt)

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
        from src.common.vision import MultimodalLLM
        
        multi_llm = MultimodalLLM(self.llm)
        
        # 将 PDF 转为图片（取第一页）
        image_data = self._pdf_to_image(file_data)
        
        ocr_text = extracted.get("text", "") or ""
        
        # 1. LLM 文档类型识别（从配置读取标签）
        from src.services.review.rules.config import get_type_labels_for_llm
        labels_text = get_type_labels_for_llm()
        prompt_type = f"""请识别这个文档的类型（直接返回中文名称，不要其他内容）：
{labels_text}

直接返回上述类型名称之一。如果不在上述类型中，请返回"未知"。"""
        
        doc_type_llm = ""
        try:
            doc_type_llm = await multi_llm.analyze_image(image_data, prompt_type)
        except Exception:
            doc_type_llm = "LLM分析失败"
        
        # 2. LLM 通用表格内容提取（一次调用，原文照抄）
        import logging
        logger = logging.getLogger(__name__)
        
        import re
        logger = logging.getLogger(__name__)
        
        # Step1: 识别表格字段
        logger.info("[LLM] Step1: 识别表格字段...")
        prompt_detect = """请仔细看图，列出这个表格/表单的所有字段名（只返回字段名列表，每行一个）。

只输出字段名，不要其他内容。"""

        try:
            cols_result = await multi_llm.analyze_image(image_data, prompt_detect)
            field_names = [line.strip() for line in cols_result.strip().split('\n') if line.strip() and len(line.strip()) > 1]
            logger.info(f"[LLM] 识别到字段: {field_names[:5]}...")
            
            if not field_names:
                raise Exception("未能识别到表格字段")
            
            # Step2: 定位每个字段的值区域
            logger.info("[LLM] Step2: 定位字段值区域...")
            prompt_locate = f"""请在图片中找出以下字段的值填写区域位置（不是字段名，是填写内容的区域）：

{chr(10).join(field_names)}

返回格式（每行）：
字段名: x1,y1,x2,y2 （归一化坐标0-1）"""

            locate_result = await multi_llm.analyze_image(image_data, prompt_locate)
            
            # 解析坐标
            field_coords = {}
            for line in locate_result.strip().split('\n'):
                match = re.match(r'(.+?):\s*([\d.]+),([\d.]+),([\d.]+),([\d.]+)', line)
                if match:
                    fname = match.group(1).strip()
                    x1, y1, x2, y2 = float(match.group(2)), float(match.group(3)), float(match.group(4)), float(match.group(5))
                    field_coords[fname] = (x1, y1, x2, y2)
            
            logger.info(f"[LLM] 定位到 {len(field_coords)} 个字段区域")
            
            # Step3: 裁剪放大+转写
            logger.info("[LLM] Step3: 裁剪放大转写...")
            from PIL import Image
            import io
            
            # 从PNG数据加载图片
            img = Image.open(io.BytesIO(image_data))
            img_w, img_h = img.size
            
            fields_llm = {"__fields": field_names}
            
            for i, fname in enumerate(field_names):
                if fname not in field_coords:
                    fields_llm[fname] = "未定位"
                    continue
                
                x1, y1, x2, y2 = field_coords[fname]
                # 扩展边距
                margin = 0.02
                x1, y1 = max(0, x1-margin), max(0, y1-margin)
                x2, y2 = min(1, x2+margin), min(1, y2+margin)
                
                # 检查区域是否有效
                if x2 - x1 < 0.01 or y2 - y1 < 0.01:
                    logger.warning(f"[LLM] 字段{fname}区域太小，跳过: {(x1,y1,x2,y2)}")
                    fields_llm[fname] = "区域太小"
                    continue
                
                # 裁剪坐标
                left = int(x1 * img_w)
                top = int(y1 * img_h)
                right = int(x2 * img_w)
                bottom = int(y2 * img_h)
                
                if right - left < 5 or bottom - top < 5:
                    logger.warning(f"[LLM] 字段{fname}裁剪区域太小")
                    fields_llm[fname] = "裁剪区域太小"
                    continue
                
                # 裁剪
                cropped_img = img.crop((left, top, right, bottom))
                # 放大5倍
                cropped_img = cropped_img.resize((cropped_img.width * 5, cropped_img.height * 5), Image.LANCZOS)
                
                # 转bytes
                buf = io.BytesIO()
                cropped_img.save(buf, format='PNG')
                cropped = buf.getvalue()
                
                # 转写（禁止纠错）
                prompt_trans = """【重要】请原封不动抄写图中文字，不要纠正任何错误！

即使看到错别字也要原样抄写。
直接返回文字，不要其他内容。"""
                
                try:
                    trans = await multi_llm.analyze_image(cropped, prompt_trans)
                    fields_llm[fname] = trans.strip()
                    logger.info(f"[LLM] 字段{i+1}/{len(field_names)}: {fname}")
                except Exception as ex:
                    fields_llm[fname] = f"错误: {str(ex)}"
            
            logger.info("[LLM] 表格提取完成")
            
        except Exception as e:
            logger.error(f"[LLM] 表格提取失败: {e}")
            fields_llm = {"error": str(e)}
        
        # 3. LLM 印章描述
        prompt_stamps = """请描述页面中所有印章的位置和内容。
只返回描述，不要其他内容。"""
        
        stamps_desc = ""
        try:
            stamps_desc = await multi_llm.analyze_image(image_data, prompt_stamps)
        except Exception:
            stamps_desc = "LLM分析失败"
        
        # 4. LLM 签字描述
        prompt_sigs = """请描述页面中所有签字/签名的位置。
只返回描述，不要其他内容。"""
        
        sigs_desc = ""
        try:
            sigs_desc = await multi_llm.analyze_image(image_data, prompt_sigs)
        except Exception:
            sigs_desc = "LLM分析失败"
        
        return {
            "document_type_llm": doc_type_llm.strip(),
            "extracted_fields": fields_llm,
            "stamps_description": stamps_desc.strip(),
            "signatures_description": sigs_desc.strip(),
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
            
            # 渲染第一页为图片
            page = doc.load_page(0)
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))  # 2x 分辨率
            img_data = pix.tobytes("png")
            doc.close()
            return img_data
        except Exception:
            return file_data