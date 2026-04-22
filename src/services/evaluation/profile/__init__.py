"""项目画像模块"""

from .profile_config import (
    PROFILE_DEMONSTRATION,
    PROFILE_GENERIC,
    PROFILE_PLATFORM,
    PROFILE_SCIENCE_POPULARIZATION,
    PROFILE_TECH_RND,
)
from .project_profiler import ProjectProfileResult, ProjectProfiler
from .rubric_manager import RubricManager

__all__ = [
    "PROFILE_DEMONSTRATION",
    "PROFILE_GENERIC",
    "PROFILE_PLATFORM",
    "PROFILE_SCIENCE_POPULARIZATION",
    "PROFILE_TECH_RND",
    "ProjectProfileResult",
    "ProjectProfiler",
    "RubricManager",
]
