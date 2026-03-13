"""文档解析器"""
from src.common.file_handler import get_parser
from src.common.models import DocumentContent


class DocumentParser:
    """文档解析器

    协调 PDF/图片解析，提供统一的文档内容提取接口。
    """

    def __init__(self):
        """初始化解析器"""
        self._parsers = {}

    async def parse(
        self,
        file_data: bytes,
        file_type: str,
        **kwargs,
    ):
        """解析文档

        Args:
            file_data: 文件数据
            file_type: 文件类型 (pdf, image, jpg, png)
            **kwargs: 其他参数

        Returns:
            解析结果
        """
        # 标准化文件类型
        ft = file_type.lower()
        if ft == "jpeg":
            ft = "jpg"

        # 获取解析器
        if ft not in self._parsers:
            self._parsers[ft] = get_parser(ft)

        parser = self._parsers[ft]
        return await parser.parse(file_data, **kwargs)

    async def extract_images(self, file_data: bytes, file_type: str):
        """提取图片

        Args:
            file_data: 文件数据
            file_type: 文件类型

        Returns:
            图片列表
        """
        ft = file_type.lower()
        if ft == "jpeg":
            ft = "jpg"

        if ft not in self._parsers:
            self._parsers[ft] = get_parser(ft)

        parser = self._parsers[ft]
        return await parser.extract_images(file_data)
