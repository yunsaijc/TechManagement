"""枚举定义"""
from enum import Enum


class DocumentType(str, Enum):
    """文档类型"""
    PATENT_CERTIFICATE = "patent_certificate"  # 专利证书
    PATENT_APPLICATION = "patent_application"  # 专利申请
    ACCEPTANCE_REPORT = "acceptance_report"  # 验收报告
    LICENSE = "license"  # 行政许可
    RETRIEVAL_REPORT = "retrieval_report"  # 检索报告
    AWARD_CERTIFICATE = "award_certificate"  # 奖励证书
    CONTRACT = "contract"  # 合同
    OTHER = "other"


class CheckItem(str, Enum):
    """检查项"""
    SIGNATURE = "signature"  # 签字检查
    STAMP = "stamp"  # 盖章检查
    PREREQUISITE = "prerequisite"  # 前置条件
    CONSISTENCY = "consistency"  # 一致性检查
    COMPLETENESS = "completeness"  # 完整性检查
    FORMAT = "format"  # 格式检查
