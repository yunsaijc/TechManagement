"""多模态 LLM 封装"""
from typing import Any

from langchain_core.messages import HumanMessage


class MultimodalLLM:
    """多模态 LLM 封装 - 基于 LangChain"""

    def __init__(self, llm: Any):
        """初始化

        Args:
            llm: LangChain ChatModel 实例
        """
        self.llm = llm

    async def analyze_image(
        self,
        image_data: bytes,
        prompt: str,
        **kwargs,
    ) -> str:
        """分析图像

        Args:
            image_data: 图像数据
            prompt: 提示词
            **kwargs: 其他参数

        Returns:
            分析结果
        """
        import base64

        # 转换为 base64
        b64_image = base64.b64encode(image_data).decode("utf-8")
        image_url = f"data:image/png;base64,{b64_image}"

        # 构建多模态消息
        message = HumanMessage(
            content=[
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": image_url}},
            ]
        )

        response = await self.llm.ainvoke([message], **kwargs)
        return response.content

    async def describe_document(
        self,
        image_data: bytes,
        **kwargs,
    ) -> str:
        """描述文档内容

        Args:
            image_data: 图像数据
            **kwargs: 其他参数

        Returns:
            文档描述
        """
        prompt = """请详细描述这张文档图片的内容，包括：
1. 文档类型
2. 主要文字内容
3. 是否有签名、印章
4. 版式结构
"""
        return await self.analyze_image(image_data, prompt, **kwargs)

    async def verify_signature(
        self,
        document_image: bytes,
        signature_image: bytes,
        **kwargs,
    ) -> str:
        """验证签名

        Args:
            document_image: 文档中的签名区域图像
            signature_image: 参考签名图像
            **kwargs: 其他参数

        Returns:
            验证结果
        """
        import base64

        b64_doc = base64.b64encode(document_image).decode("utf-8")
        b64_sig = base64.b64encode(signature_image).decode("utf-8")

        prompt = """比较这两张图片：
- 图1：文档中的签名区域
- 图2：参考签名

请判断是否为同一人签名，置信度如何？"""

        message = HumanMessage(
            content=[
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64_doc}"}},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64_sig}"}},
            ]
        )

        response = await self.llm.ainvoke([message], **kwargs)
        return response.content
