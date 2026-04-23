"""项目画像测试"""

from src.common.models.evaluation import EvaluationDimension
from src.services.evaluation.profile import (
    PROFILE_DEMONSTRATION,
    PROFILE_GENERIC,
    PROFILE_PLATFORM,
    PROFILE_SCIENCE_POPULARIZATION,
    PROFILE_TECH_RND,
    ProjectProfiler,
)


def test_project_profiler_identifies_science_popularization_profile():
    """科普实施类项目应识别为科普画像，并给出维度放宽配置"""
    profiler = ProjectProfiler()

    result = profiler.infer(
        {
            "项目简介": "围绕基层健康科普，开展线上直播、线下活动和公众号传播。",
            "科普内容产出": "制作系列科普作品，建设资源库。",
            "科普活动开展": "开展义诊与专题展览活动。",
        }
    )

    assert result.project_profile == PROFILE_SCIENCE_POPULARIZATION
    assert result.confidence >= 0.7
    assert EvaluationDimension.FEASIBILITY.value in result.dimension_overrides


def test_project_profiler_identifies_platform_profile():
    """平台建设类项目应识别为平台画像"""
    profiler = ProjectProfiler()

    result = profiler.infer(
        {
            "建设目标": "建设区域公共服务平台和共享数据库。",
            "核心建设内容": "完善平台基础设施和资源平台能力。",
            "项目组织实施机制": "形成平台运营机制。",
        }
    )

    assert result.project_profile == PROFILE_PLATFORM


def test_project_profiler_falls_back_to_generic_when_evidence_is_weak():
    """画像证据不足时应回退到通用口径"""
    profiler = ProjectProfiler()

    result = profiler.infer({"项目简介": "项目围绕综合能力提升开展相关工作。"})

    assert result.project_profile == PROFILE_GENERIC
    assert result.dimension_overrides == {}


def test_project_profiler_identifies_tech_rnd_profile():
    """技术研发类项目应识别为技术研发画像"""
    profiler = ProjectProfiler()

    result = profiler.infer(
        {
            "技术路线": "通过算法模型和传感器开展系统研发。",
            "研究内容": "围绕关键机理与模型优化展开研究。",
        }
    )

    assert result.project_profile == PROFILE_TECH_RND


def test_project_profiler_identifies_demonstration_profile_with_overrides():
    """示范应用类项目应识别为示范画像，并携带维度放宽配置"""
    profiler = ProjectProfiler()

    result = profiler.infer(
        {
            "应用示范方案": "围绕低空巡检场景开展应用示范与推广应用。",
            "推广应用": "形成示范场景并逐步产业化落地。",
            "项目实施的预期经济社会效益目标": "通过示范带动区域应用。",
        }
    )

    assert result.project_profile == PROFILE_DEMONSTRATION
    assert EvaluationDimension.OUTCOME.value in result.dimension_overrides
