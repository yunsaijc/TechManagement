"""字段提取器（Layer 4）

职责：从文档中提取表格/表单字段的值
流程：Step1 识别字段 → Step2 定位 bbox → Step3 OCR 转写
"""
import io
import logging
import os
import re
from typing import Dict, List, Optional, Any

from PIL import Image
import numpy as np

from src.common.llm import get_default_llm_client
from src.common.vision import MultimodalLLM

logger = logging.getLogger(__name__)


class FieldExtractor:
    """字段提取器 - 先定位 bbox 再 OCR 转写"""

    def __init__(self):
        self._paddle_ocr = None
        self._llm_client = None

    async def extract(
        self,
        file_data: bytes,
        document_type: Optional[str] = None,
        configured_fields: Optional[List[str]] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        提取字段内容

        Args:
            file_data: PDF/图片 bytes
            document_type: 文档类型（用于加载配置字段）
            configured_fields: 配置的关键字段列表

        Returns:
            字段字典 {"__fields": [...], "字段名": "值", ...}，提取失败返回 None
        """
        try:
            # 1. PDF 转图片
            image_data = self._pdf_to_image(file_data)
            img = Image.open(io.BytesIO(image_data))
            img_w, img_h = img.size

            # 2. Step1: 识别表格字段
            field_names = await self._detect_fields(image_data, document_type, configured_fields)
            if not field_names:
                logger.warning("[FieldExtractor] 未能识别到表格字段")
                return None

            # 3. Step2: 定位字段值区域 (bbox)
            field_coords = await self._locate_fields(image_data, field_names)
            if not field_coords:
                logger.warning("[FieldExtractor] 未能定位到字段区域")
                return None

            # 4. Step3: 裁剪 + OCR 转写
            fields = await self._extract_values(img, img_w, img_h, field_names, field_coords)

            logger.info(f"[FieldExtractor] 字段提取完成，共 {len(fields)} 个字段")
            return fields

        except Exception as e:
            logger.error(f"[FieldExtractor] 字段提取失败: {e}")
            return None

    async def extract_with_coords(
        self,
        file_data: bytes,
        field_coords: Dict[str, tuple],
        field_names: List[str],
    ) -> Dict[str, Any]:
        """使用已知坐标提取字段值（跳过 LLM 定位步骤）"""
        try:
            # PDF 转图片
            image_data = self._pdf_to_image(file_data)
            img = Image.open(io.BytesIO(image_data))
            img_w, img_h = img.size
            
            # 直接用已知坐标提取
            fields = await self._extract_values(img, img_w, img_h, field_names, field_coords)
            
            logger.info(f"[FieldExtractor] 字段提取完成，共 {len(fields)} 个字段")
            return fields
            
        except Exception as e:
            logger.error(f"[FieldExtractor] 字段提取失败: {e}")
            return {"__fields": field_names, "error": str(e)}

    def _pdf_to_image(self, file_data: bytes) -> bytes:
        """PDF 转图片（取第一页，fitz 放大3倍）"""
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
        except Exception as e:
            logger.warning(f"[FieldExtractor] PDF 转图片失败: {e}")
            return file_data

    async def _detect_fields(
        self,
        image_data: bytes,
        document_type: Optional[str],
        configured_fields: Optional[List[str]],
    ) -> Optional[List[str]]:
        """Step1: 识别表格字段"""
        # 优先使用配置字段
        if configured_fields:
            logger.info(f"[FieldExtractor] 使用配置的关键字段: {configured_fields}")
            return configured_fields

        # 从配置加载字段
        if document_type:
            from src.services.review.rules.config import load_llm_extract_fields
            configured = load_llm_extract_fields(document_type)
            if configured:
                logger.info(f"[FieldExtractor] 使用配置的关键字段: {configured}")
                return configured

        # 自动识别字段
        llm = self._get_llm()
        multi_llm = MultimodalLLM(llm)

        prompt = """请仔细看图，列出这个表格/表单的所有字段名（只返回字段名列表，每行一个）。

只输出字段名，不要其他内容。"""

        try:
            result = await multi_llm.analyze_image(image_data, prompt)
            field_names = [line.strip() for line in result.strip().split('\n') if line.strip() and len(line.strip()) > 1]
            
            max_fields = int(os.getenv("LLM_MAX_FIELDS", "25"))
            if len(field_names) > max_fields:
                logger.warning(f"[FieldExtractor] 字段数过多({len(field_names)})，仅保留前{max_fields}个")
                field_names = field_names[:max_fields]
            
            return field_names if field_names else None
        except Exception as e:
            logger.error(f"[FieldExtractor] Step1 字段识别失败: {e}")
            return None

    async def _locate_fields(self, image_data: bytes, field_names: List[str]) -> Optional[Dict[str, tuple]]:
        """Step2: 定位字段值区域"""
        llm = self._get_llm()
        multi_llm = MultimodalLLM(llm)

        prompt = f"""请在图片中找出以下字段的【填写内容】区域（不是字段名，是实际填写文字的区域，要尽量小，只包含文字）：

{chr(10).join(field_names)}

返回格式（每行）：
字段名: x1,y1,x2,y2 （归一化坐标0-1）"""

        try:
            result_text = await multi_llm.analyze_image(image_data, prompt)

            # 解析坐标
            field_coords = {}
            for line in result_text.strip().split('\n'):
                match = re.match(r'(.+?):\s*([\d.]+),([\d.]+),([\d.]+),([\d.]+)', line)
                if match:
                    fname = match.group(1).strip()
                    x1, y1, x2, y2 = float(match.group(2)), float(match.group(3)), float(match.group(4)), float(match.group(5))
                    field_coords[fname] = (x1, y1, x2, y2)

            logger.info(f"[FieldExtractor] 定位到 {len(field_coords)} 个字段区域")
            return field_coords if field_coords else None
        except Exception as e:
            logger.error(f"[FieldExtractor] Step2 字段定位失败: {e}")
            return None

    async def _extract_values(
        self,
        img: Image.Image,
        img_w: int,
        img_h: int,
        field_names: List[str],
        field_coords: Dict[str, tuple],
    ) -> Dict[str, Any]:
        """Step3: 裁剪 + OCR 转写"""
        import logging as _logging
        _logging.getLogger("ppocr").setLevel(_logging.ERROR)

        from paddleocr import PaddleOCR

        if self._paddle_ocr is None:
            # 使用默认参数
            self._paddle_ocr = PaddleOCR(use_angle_cls=True, lang='ch')

        fields = {"__fields": field_names}
        llm = self._get_llm()
        multi_llm = MultimodalLLM(llm)

        for i, fname in enumerate(field_names):
            if fname not in field_coords:
                fields[fname] = "未定位"
                continue

            x1, y1, x2, y2 = field_coords[fname]
            
            # 扩展边距（按 bbox 宽度的比例）
            margin_ratio = 0.10  # 10% 宽度
            width = x2 - x1
            height = y2 - y1
            margin_x = width * margin_ratio
            margin_y = height * margin_ratio
            x1, y1 = max(0, x1 - margin_x), max(0, y1 - margin_y)
            x2, y2 = min(1, x2 + margin_x), min(1, y2 + margin_y)

            # 检查区域是否有效
            if x2 - x1 < 0.005 or y2 - y1 < 0.005:
                logger.warning(f"[FieldExtractor] 字段{fname}区域太小，跳过")
                fields[fname] = "区域太小"
                continue

            # 裁剪坐标
            left = int(x1 * img_w)
            top = int(y1 * img_h)
            right = int(x2 * img_w)
            bottom = int(y2 * img_h)

            if right - left < 5 or bottom - top < 5:
                logger.warning(f"[FieldExtractor] 字段{fname}裁剪区域太小")
                fields[fname] = "裁剪区域太小"
                continue

            # 裁剪
            cropped_img = img.crop((left, top, right, bottom))
            
            # 放大
            size_ratio = 1
            cropped_img = cropped_img.resize(
                (cropped_img.width * size_ratio, cropped_img.height * size_ratio), Image.LANCZOS
            )
            
            # 四周加白色 padding（帮助 OCR 识别边缘，按图片尺寸比例）
            from PIL import ImageOps
            pad_ratio = 0.15  # 15% 边距
            padding = int(min(cropped_img.width, cropped_img.height) * pad_ratio)
            cropped_img = ImageOps.expand(cropped_img, border=padding, fill='white')
            
            # 保存裁剪图片用于调试（保存放大后的）
            debug_dir = "/home/tdkx/workspace/tech/debug_cropped"
            os.makedirs(debug_dir, exist_ok=True)
            debug_path = f"{debug_dir}/{fname}_{i+1}.png"
            cropped_img.save(debug_path)
            
            # OCR 转写 - 根据配置决定是否使用 OCR
            use_ocr = os.getenv("LLM_USE_OCR_FOR_FIELDS", "true").lower() == "true"
            
            trans = ""
            if use_ocr:
                try:
                    cropped_np = np.array(cropped_img)
                    ocr_result = self._paddle_ocr.ocr(cropped_np)
                    
                    # 兼容 PaddleOCR 不同版本的返回格式
                    if ocr_result and ocr_result[0]:
                        first_page = ocr_result[0]
                        first_item = first_page[0] if isinstance(first_page, list) and first_page else first_page
                        
                        # v5 常见格式: {'rec_texts': [...]} / {'text': ...}
                        if isinstance(first_item, dict):
                            rec_texts = first_item.get("rec_texts") or first_item.get("text") or []
                            if isinstance(rec_texts, list):
                                trans = rec_texts[0] if rec_texts else ""
                            else:
                                trans = str(rec_texts).strip()
                        # 旧格式常见: [[box], ('text', score)]
                        elif (
                            isinstance(first_item, (list, tuple))
                            and len(first_item) >= 2
                            and isinstance(first_item[1], (list, tuple))
                            and len(first_item[1]) >= 1
                        ):
                            trans = str(first_item[1][0]).strip()
                        
                        logger.info(f"[OCR] 字段{i+1}/{len(field_names)}: {fname} -> {trans[:20]}...")
                except Exception as e:
                    logger.warning(f"[FieldExtractor] OCR 识别失败: {e}")

            # OCR 失败则用 LLM
            if not trans.strip():
                trans = await self._llm_transcribe(multi_llm, cropped_img, i, len(field_names), fname)

            fields[fname] = trans.strip()

        return fields

    async def _llm_transcribe(
        self,
        multi_llm: MultimodalLLM,
        cropped_img: Image.Image,
        index: int,
        total: int,
        fname: str,
    ) -> str:
        """LLM 转写（OCR 失败时的后备）"""
        prompt = """【重要】请原封不动抄写图中文字，不要纠正任何错误！

即使看到错别字也要原样抄写。
直接返回文字，不要其他内容。"""

        try:
            # 转 base64
            buf = io.BytesIO()
            cropped_img.save(buf, format="PNG")
            img_base64 = base64.b64encode(buf.getvalue()).decode()

            result = await multi_llm.generate([
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_base64}"}},
                {"type": "text", "text": prompt}
            ])
            return result.content if hasattr(result, 'content') else str(result)
        except Exception as e:
            logger.warning(f"[FieldExtractor] LLM 转写失败: {e}")
            return ""

    def _get_llm(self):
        """获取 LLM 客户端（temperature=0.5.5 稳定输出）"""
        if self._llm_client is None:
            from src.common.llm import get_llm_client, llm_config
            self._llm_client = get_llm_client(
                provider=llm_config.provider or "openai",
                model=llm_config.model or None,
                api_key=llm_config.api_key or None,
                base_url=llm_config.base_url or None,
                temperature=0.5,  # 固定为 0，bbox 提取更稳定
                max_tokens=llm_config.max_tokens,
            )
        return self._llm_client


# 兼容旧代码
import base64
