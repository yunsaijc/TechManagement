"""规则引擎模块"""
from src.services.review.rules.base import BaseRule, CheckResult, ReviewContext
from src.services.review.rules.checkers import (
    PrerequisiteCheckRule,
    SignatureCheckRule,
    StampCheckRule,
)
from src.services.review.rules.config import RULES_BY_DOCUMENT, load_rules, get_all_document_types
from src.services.review.rules.registry import RuleRegistry

__all__ = [
    "BaseRule",
    "CheckResult",
    "ReviewContext",
    "RuleRegistry",
    "SignatureCheckRule",
    "StampCheckRule",
    "PrerequisiteCheckRule",
    "RULES_BY_DOCUMENT",
    "load_rules",
    "get_all_document_types",
]
