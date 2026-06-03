"""政策沙盘（Step4/Step5）模型侧统一策略。

- 分角色超参：简报（短输出、低温度）与 GraphRAG（较长输出、略高温度）。
- OpenAI 兼容端点可启用 response_format=json_object，减少无效文本与解析失败。
- 进程内客户端复用，避免重复握手。
- GraphRAG 上下文按字符预算截断，控制 prompt 体积与延迟。
"""

from __future__ import annotations

import hashlib
import os
from typing import Any, Literal

try:
    from src.common.llm.config import llm_config
    from src.common.llm.factory import get_llm_client
except ModuleNotFoundError:
    llm_config = None  # type: ignore[assignment]
    get_llm_client = None  # type: ignore[assignment]

SandboxRole = Literal["brief", "graphrag", "narrative"]

_JSON_COMPAT_PROVIDERS = frozenset({"openai", "qwen", "azure", "minimax"})

# (role, provider, model, max_tokens, temperature, json_mode_flag, base_url, key_fp)
_LLM_CACHE: dict[tuple[Any, ...], Any] = {}


def _api_key_fingerprint(api_key: str) -> str:
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:16]


def _resolve_params(role: SandboxRole) -> tuple[str, int, float]:
    assert llm_config is not None
    default_model = (llm_config.model or "").strip()
    if role == "brief":
        model = (os.getenv("LLM_SANDBOX_BRIEF_MODEL", default_model) or default_model).strip()
        max_tokens = int(os.getenv("LLM_SANDBOX_BRIEF_MAX_TOKENS", "1024"))
        temperature = float(os.getenv("LLM_SANDBOX_BRIEF_TEMPERATURE", "0.25"))
    elif role == "narrative":
        model = (os.getenv("LLM_SANDBOX_NARRATIVE_MODEL", default_model) or default_model).strip()
        max_tokens = int(os.getenv("LLM_SANDBOX_NARRATIVE_MAX_TOKENS", "900"))
        temperature = float(os.getenv("LLM_SANDBOX_NARRATIVE_TEMPERATURE", "0.35"))
    else:
        model = (os.getenv("LLM_SANDBOX_GRAPHRAG_MODEL", default_model) or default_model).strip()
        max_tokens = int(os.getenv("LLM_SANDBOX_GRAPHRAG_MAX_TOKENS", "3072"))
        temperature = float(os.getenv("LLM_SANDBOX_GRAPHRAG_TEMPERATURE", "0.42"))
    max_tokens = max(256, min(max_tokens, 32000))
    temperature = max(0.0, min(temperature, 1.5))
    return model, max_tokens, temperature


def build_sandbox_llm(role: SandboxRole) -> Any | None:
    """构建沙箱步骤用 LLM；同一配置在进程内复用。"""
    if llm_config is None or get_llm_client is None:
        return None
    if not llm_config.provider or not llm_config.api_key:
        return None

    provider = (llm_config.provider or "").strip().lower()
    model, max_tokens, temperature = _resolve_params(role)

    json_mode = os.getenv("LLM_SANDBOX_JSON_MODE", "true").strip().lower() in {"1", "true", "yes", "on"}
    extra: dict[str, Any] = {}
    if json_mode and provider in _JSON_COMPAT_PROVIDERS:
        extra["model_kwargs"] = {"response_format": {"type": "json_object"}}

    base_url = (llm_config.base_url or "").strip()
    cache_key = (
        role,
        provider,
        model,
        max_tokens,
        round(temperature, 4),
        json_mode and provider in _JSON_COMPAT_PROVIDERS,
        base_url,
        _api_key_fingerprint(llm_config.api_key),
    )
    if cache_key in _LLM_CACHE:
        return _LLM_CACHE[cache_key]

    try:
        client = get_llm_client(
            provider=provider,
            model=model,
            api_key=llm_config.api_key,
            base_url=llm_config.base_url,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=float(llm_config.timeout),
            max_retries=int(llm_config.max_retries),
            **extra,
        )
        _LLM_CACHE[cache_key] = client
        return client
    except Exception as exc:
        print(f"[WARN] sandbox LLM 初始化失败 role={role}: {exc}")
        return None


def sandbox_llm_meta(role: SandboxRole) -> dict[str, Any]:
    """写入步骤产物 meta，便于排查「实际走的模型/参数」。"""
    if llm_config is None:
        return {"role": role, "provider": "unknown", "model": "unknown", "jsonMode": False}

    provider = (llm_config.provider or "").strip().lower()
    model, max_tokens, temperature = _resolve_params(role)
    json_mode = os.getenv("LLM_SANDBOX_JSON_MODE", "true").strip().lower() in {"1", "true", "yes", "on"}
    return {
        "role": role,
        "provider": provider,
        "model": model,
        "maxTokens": max_tokens,
        "temperature": temperature,
        "jsonMode": bool(json_mode and provider in _JSON_COMPAT_PROVIDERS),
    }


def truncate_graph_context(context_text: str, max_chars: int | None = None) -> str:
    """限制 GraphRAG 送入模型的上下文长度，降低延迟与费用。"""
    if max_chars is None:
        max_chars = int(os.getenv("LLM_SANDBOX_GRAPHRAG_MAX_CONTEXT_CHARS", "14000"))
    if max_chars <= 0 or len(context_text) <= max_chars:
        return context_text
    reserve = 120
    head = max_chars - reserve
    if head < 512:
        head = min(len(context_text), 512)
    return (
        context_text[:head]
        + "\n\n[图上下文已按 LLM_SANDBOX_GRAPHRAG_MAX_CONTEXT_CHARS 截断；前段为管理层/知识层优先内容]\n"
    )
