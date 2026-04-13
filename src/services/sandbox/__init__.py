"""Sandbox 服务模块。"""


def run_neo4j_gds_preflight() -> None:
    from .neo4j_gds_preflight import main

    main()


def run_hotspot_migration_step2() -> None:
    from .hotspot_migration_step2 import main

    main()


def run_macro_insight_step3() -> None:
    from .macro_insight_step3 import main

    main()


def run_briefing_orchestrator_step4() -> None:
    from .briefing_orchestrator_step4 import main

    main()


def run_graph_rag_step5() -> None:
    from .graph_rag_step5 import main

    main()


def run_leadership_sandbox() -> None:
    from .leadership_sandbox_orchestrator import run_leadership_sandbox

    run_leadership_sandbox()


__all__ = [
    "run_neo4j_gds_preflight",
    "run_hotspot_migration_step2",
    "run_macro_insight_step3",
    "run_briefing_orchestrator_step4",
    "run_graph_rag_step5",
    "run_leadership_sandbox",
]
