#!/usr/bin/env python3
"""第四步：简报编排层（Python/LangChain）。

目标：
1. 聚合第二步热点迁移与第三步宏观研判的结构化输出。
2. 生成可直接展示的领导视角简报 JSON。
3. 在可用时使用 LangChain + LLM 进行自然语言增强；不可用时退化为规则模板。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    from dotenv import load_dotenv
except ModuleNotFoundError:
    def load_dotenv(*args: Any, **kwargs: Any) -> bool:
        return False

try:
    from src.common.llm.config import llm_config
    from src.common.llm.factory import get_llm_client
except ModuleNotFoundError:
    llm_config = None  # type: ignore[assignment]
    get_llm_client = None  # type: ignore[assignment]

try:
    from langchain_core.prompts import ChatPromptTemplate
except ModuleNotFoundError:
    ChatPromptTemplate = None  # type: ignore[assignment]

try:
    from langchain_openai import ChatOpenAI
except ModuleNotFoundError:
    ChatOpenAI = None  # type: ignore[assignment]

try:
    from langchain_anthropic import ChatAnthropic
except ModuleNotFoundError:
    ChatAnthropic = None  # type: ignore[assignment]

load_dotenv(Path(__file__).resolve().parents[3] / ".env")

SANDBOX_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT_DIR = SANDBOX_DIR / "output"

DEFAULT_STEP2_PATH = str(DEFAULT_OUTPUT_DIR / "step2" / "hotspot_migration_real_schema_2023_to_2024.json")
DEFAULT_STEP3_PATH = "debug_sandbox/macro_insight_2023_2023_to_2024_2024.json"
DEFAULT_OUTPUT_PATH = "debug_sandbox/leadership_brief_step4.json"
DEFAULT_TOP_MOVEMENTS = 5


@dataclass
class BriefingConfig:
    step2_path: str
    step3_path: str
    output_path: str
    top_movements: int


def build_config() -> BriefingConfig:
    return BriefingConfig(
        step2_path=os.getenv("BRIEFING_STEP2_PATH", DEFAULT_STEP2_PATH),
        step3_path=os.getenv("BRIEFING_STEP3_PATH", DEFAULT_STEP3_PATH),
        output_path=os.getenv("BRIEFING_OUTPUT_PATH", DEFAULT_OUTPUT_PATH),
        top_movements=int(os.getenv("BRIEFING_TOP_MOVEMENTS", str(DEFAULT_TOP_MOVEMENTS))),
    )


def load_json(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def ensure_output_dir(path: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)


def summarize_movements(step2: dict[str, Any], top_n: int) -> list[dict[str, Any]]:
    links = step2.get("sankey", {}).get("links", [])
    sorted_links = sorted(
        links,
        key=lambda x: float(x.get("value", 0.0)),
        reverse=True,
    )
    top_links = sorted_links[:top_n]

    result: list[dict[str, Any]] = []
    for item in top_links:
        result.append(
            {
                "from": item.get("source", "未知来源"),
                "to": item.get("target", "未知去向"),
                "value": item.get("value", 0),
            }
        )
    return result


def summarize_findings(step3: dict[str, Any]) -> dict[str, Any]:
    summary = step3.get("summary", {})
    findings = step3.get("findings", [])

    high = [f for f in findings if f.get("severity") == "high"]
    medium = [f for f in findings if f.get("severity") == "medium"]

    return {
        "counts": {
            "totalFindings": int(summary.get("totalFindings", len(findings))),
            "highRisk": int(summary.get("highRisk", len(high))),
            "mediumRisk": int(summary.get("mediumRisk", len(medium))),
        },
        "topHighRiskTopics": [f.get("topic", "未知主题") for f in high[:5]],
        "topMediumRiskTopics": [f.get("topic", "未知主题") for f in medium[:5]],
        "briefing": step3.get("briefing", {}),
    }


def build_rule_brief(step2: dict[str, Any], step3: dict[str, Any], cfg: BriefingConfig) -> dict[str, Any]:
    movements = summarize_movements(step2, cfg.top_movements)
    findings_summary = summarize_findings(step3)

    counts = findings_summary["counts"]
    if counts["highRisk"] > 0:
        headline = f"当前存在 {counts['highRisk']} 个高风险主题，建议优先处理增长快但转化弱的方向。"
    elif counts["mediumRisk"] > 0:
        headline = f"当前存在 {counts['mediumRisk']} 个中风险主题，应优先补齐人才与协作短板。"
    else:
        headline = "当前未发现明显高风险主题，建议持续跟踪热点迁移与转化效率。"

    key_messages = []
    if movements:
        key_messages.append(f"热点迁移主路径数量：{len(movements)}，需关注流入规模最大的主题承接能力。")
    if counts["highRisk"] > 0:
        key_messages.append("高风险主题已出现，建议压降低效扩张并提高中期验收约束。")
    if counts["mediumRisk"] > 0:
        key_messages.append("部分主题存在人才结构偏弱或协作不足，建议推动跨团队联合机制。")
    if not key_messages:
        key_messages.append("整体表现平稳，可保持当前资源配置并监测下一周期变化。")

    return {
        "headline": headline,
        "keyMessages": key_messages,
        "topMovements": movements,
        "riskSnapshot": findings_summary,
    }


def _build_llm() -> Any | None:
    if llm_config is None or get_llm_client is None:
        return None

    provider = llm_config.provider
    model = llm_config.model
    api_key = llm_config.api_key
    if not provider or not api_key:
        return None

    try:
        return get_llm_client(
            provider=provider,
            model=model,
            api_key=api_key,
            base_url=llm_config.base_url,
            temperature=float(llm_config.temperature),
            max_tokens=int(llm_config.max_tokens),
            timeout=float(llm_config.timeout),
            max_retries=int(llm_config.max_retries),
        )
    except Exception as exc:
        print(f"[WARN] Step4 初始化 LLM 客户端失败: {exc}")
        return None


def _active_llm_meta() -> dict[str, str]:
    if llm_config is None:
        return {"provider": "unknown", "model": "unknown"}
    return {
        "provider": str(llm_config.provider or "unknown"),
        "model": str(llm_config.model or "unknown"),
    }


def _llm_config_ready() -> bool:
    if llm_config is None:
        return False
    return bool(llm_config.provider and llm_config.api_key)


def _llm_dependency_ready() -> bool:
    if ChatPromptTemplate is None:
        return False
    provider = (_active_llm_meta().get("provider") or "").lower()
    if provider in {"openai", "qwen", "azure", "minimax"}:
        return ChatOpenAI is not None
    if provider == "anthropic":
        return ChatAnthropic is not None
    return False


def llm_enhance_brief(rule_brief: dict[str, Any], step2_meta: dict[str, Any], step3_meta: dict[str, Any]) -> dict[str, Any] | None:
    if ChatPromptTemplate is None:
        return None

    llm = _build_llm()
    if llm is None:
        return None

    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                "你是科技管理领导简报助手。请基于输入生成简洁、可执行的管理简报，"
                "输出严格为 JSON，包含: headline, keyMessages, actions。",
            ),
            (
                "human",
                "规则简报: {rule_brief}\n"
                "迁移元信息: {step2_meta}\n"
                "研判元信息: {step3_meta}\n"
                "请输出 JSON。",
            ),
        ]
    )

    chain = prompt | llm
    response = chain.invoke(
        {
            "rule_brief": json.dumps(rule_brief, ensure_ascii=False),
            "step2_meta": json.dumps(step2_meta, ensure_ascii=False),
            "step3_meta": json.dumps(step3_meta, ensure_ascii=False),
        }
    )

    content = getattr(response, "content", "")
    if isinstance(content, list):
        content = "\n".join(str(c) for c in content)

    text = str(content).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None

    try:
        return json.loads(text[start : end + 1])
    except Exception as exc:
        print(f"[WARN] Step4 LLM 输出 JSON 解析失败: {exc}")
        return None


def run(cfg: BriefingConfig) -> dict[str, Any]:
    step2 = load_json(cfg.step2_path)
    step3 = load_json(cfg.step3_path)

    rule_brief = build_rule_brief(step2, step3, cfg)
    llm_brief = llm_enhance_brief(
        rule_brief=rule_brief,
        step2_meta=step2.get("meta", {}),
        step3_meta=step3.get("meta", {}),
    )

    final_brief = llm_brief if isinstance(llm_brief, dict) else rule_brief
    llm_meta = _active_llm_meta()
    llm_ready = _llm_config_ready()
    llm_dependency = _llm_dependency_ready()

    return {
        "meta": {
            "step2Path": cfg.step2_path,
            "step3Path": cfg.step3_path,
            "llmProvider": llm_meta["provider"],
            "llmModel": llm_meta["model"],
            "llmConfigured": llm_ready,
            "llmDependencyReady": llm_dependency,
            "llmEnhanced": isinstance(llm_brief, dict),
        },
        "brief": final_brief,
        "ruleBrief": rule_brief,
        "step2": {
            "meta": step2.get("meta", {}),
            "projection": step2.get("projection", {}),
            "insightDraft": step2.get("insightDraft", {}),
        },
        "step3": {
            "meta": step3.get("meta", {}),
            "summary": step3.get("summary", {}),
            "briefing": step3.get("briefing", {}),
        },
    }


def main() -> int:
    try:
        cfg = build_config()
        result = run(cfg)
        ensure_output_dir(cfg.output_path)
        with open(cfg.output_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        print("[SUCCESS] 第四步完成：简报编排层已生成领导视角输出")
        print(f"[OUTPUT] {cfg.output_path}")
        print(
            f"[LLM] configured={result['meta']['llmConfigured']} dependency={result['meta']['llmDependencyReady']} "
            f"enhanced={result['meta']['llmEnhanced']} provider={result['meta']['llmProvider']} model={result['meta']['llmModel']}"
        )
        return 0
    except FileNotFoundError as exc:
        print(f"[ERROR] 输入文件不存在: {exc}")
        print("请先运行第二步与第三步，或通过 BRIEFING_STEP2_PATH/BRIEFING_STEP3_PATH 指定文件。")
        return 2
    except Exception as exc:
        print(f"[ERROR] 运行失败: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
