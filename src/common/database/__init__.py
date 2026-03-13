"""
数据库模块

提供对奖励评审和项目评审数据库的访问能力。

Usage:
    # 方式1: 直接使用 Repository
    from src.common.database import ExpertRepository
    
    repo = ExpertRepository()
    experts = repo.list_by_subject("010101")
    
    # 方式2: 使用便捷函数
    from src.common.database import get_expert_repo
    
    repo = get_expert_repo()
    experts = repo.list_all()
"""
from src.common.database.config import db_settings
from src.common.database.connection import (
    get_reward_connection,
    get_project_connection,
    reward_execute,
    project_execute,
)
from src.common.database.models import (
    Expert,
    WorkUnit,
    RecommendUnit,
    Subject,
    Project,
    ProjectPerson,
    ProjectUnit,
    ReviewResult,
    ProjectReview,
    ExpertLogin,
    ExpertScore,
)
from src.common.database.repositories import (
    ExpertRepository,
    WorkUnitRepository,
    RecommendUnitRepository,
    SubjectRepository,
)


# ============== 便捷函数 ==============

def get_expert_repo() -> ExpertRepository:
    """获取专家仓库实例"""
    return ExpertRepository()


def get_work_unit_repo() -> WorkUnitRepository:
    """获取工作单位仓库实例"""
    return WorkUnitRepository()


def get_recommend_unit_repo() -> RecommendUnitRepository:
    """获取推荐单位仓库实例"""
    return RecommendUnitRepository()


def get_subject_repo() -> SubjectRepository:
    """获取学科仓库实例"""
    return SubjectRepository()


__all__ = [
    # 配置
    "db_settings",
    # 连接
    "get_reward_connection",
    "get_project_connection",
    "reward_execute",
    "project_execute",
    # 模型
    "Expert",
    "WorkUnit",
    "RecommendUnit",
    "Subject",
    "Project",
    "ProjectPerson",
    "ProjectUnit",
    "ReviewResult",
    "ProjectReview",
    "ExpertLogin",
    "ExpertScore",
    # 仓库
    "ExpertRepository",
    "WorkUnitRepository",
    "RecommendUnitRepository",
    "SubjectRepository",
    # 便捷函数
    "get_expert_repo",
    "get_work_unit_repo",
    "get_recommend_unit_repo",
    "get_subject_repo",
]
