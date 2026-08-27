from __future__ import annotations

import json
import sys
import time
from typing import Any

from openai import OpenAI

from .config import bool_env, env
from .tracing import set_span_attrs


class JsonLlmClient:
    def __init__(self, tracer: Any) -> None:
        self._tracer = tracer
        self._clients: dict[str, OpenAI] = {}

    def _provider(self) -> str:
        return env("ANALITRICS_LLM_PROVIDER", "openai").strip().lower()

    def _client(self) -> OpenAI:
        provider = self._provider()
        if provider not in {"openai", "local"}:
            raise RuntimeError("ANALITRICS_LLM_PROVIDER must be 'openai' or 'local'")
        if provider in self._clients:
            return self._clients[provider]
        timeout_seconds = self._timeout_seconds()
        if provider == "local":
            client = OpenAI(
                api_key=env("ANALITRICS_LOCAL_API_KEY", "local-not-required"),
                base_url=env("ANALITRICS_LOCAL_BASE_URL", "http://host.docker.internal:11434/v1"),
                timeout=timeout_seconds,
            )
        else:
            client = OpenAI(api_key=env("OPENAI_API_KEY"), timeout=timeout_seconds)
        self._clients[provider] = client
        return client

    def _timeout_seconds(self) -> float:
        raw = env("ANALITRICS_LLM_TIMEOUT_SECONDS", "120")
        try:
            timeout = float(raw)
        except ValueError as exc:
            raise RuntimeError("ANALITRICS_LLM_TIMEOUT_SECONDS must be numeric") from exc
        if timeout <= 0:
            raise RuntimeError("ANALITRICS_LLM_TIMEOUT_SECONDS must be greater than zero")
        return timeout

    def _model(self, model_env: str, default_model: str) -> str:
        if self._provider() == "local":
            local_override = f"{model_env}_LOCAL"
            return env(local_override, env("ANALITRICS_LOCAL_MODEL"))
        return env(model_env, env("ANALITRICS_NL_SQL_MODEL", default_model))

    def complete_json(
        self,
        system: str,
        payload: dict[str, Any],
        model_env: str,
        default_model: str,
    ) -> dict[str, Any]:
        provider = self._provider()
        model = self._model(model_env, default_model)
        payload_stats = self._payload_stats(system, payload)
        with self._tracer.start_as_current_span("llm_json") as span:
            set_span_attrs(
                span,
                {
                    "llm.model": model,
                    "llm.model_env": model_env,
                    "llm.provider": provider,
                    "llm.prompt_chars.system": payload_stats["system_chars"],
                    "llm.prompt_chars.payload_total": payload_stats["payload_total_chars"],
                    "llm.prompt_chars.by_key": payload_stats["payload_key_chars"],
                    "llm.payload_summary": {
                        "keys": sorted(payload.keys()),
                        "question": payload.get("question"),
                    },
                },
            )
            request: dict[str, Any] = {
                "model": model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False, indent=2)},
                ],
            }
            if provider == "openai" or bool_env("ANALITRICS_LOCAL_USE_RESPONSE_FORMAT", False):
                request["response_format"] = {"type": "json_object"}
            if not model.startswith("gpt-5."):
                request["temperature"] = 0
            started = time.perf_counter()
            response = self._client().chat.completions.create(**request)
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            parsed = self._parse_json_response(response.choices[0].message.content or "{}")
            usage = self._usage(response)
            set_span_attrs(
                span,
                {
                    "llm.output_keys": sorted(parsed.keys()),
                    "llm.duration_ms": duration_ms,
                    "llm.usage.prompt_tokens": usage["prompt_tokens"],
                    "llm.usage.completion_tokens": usage["completion_tokens"],
                    "llm.usage.total_tokens": usage["total_tokens"],
                },
            )
            self._debug_llm_stats("json", model_env, model, provider, duration_ms, payload_stats, usage)
            return parsed

    def complete_text(
        self,
        system: str,
        payload: dict[str, Any],
        model_env: str,
        default_model: str,
    ) -> str:
        provider = self._provider()
        model = self._model(model_env, default_model)
        payload_stats = self._payload_stats(system, payload)
        with self._tracer.start_as_current_span("llm_text") as span:
            set_span_attrs(
                span,
                {
                    "llm.model": model,
                    "llm.model_env": model_env,
                    "llm.provider": provider,
                    "llm.prompt_chars.system": payload_stats["system_chars"],
                    "llm.prompt_chars.payload_total": payload_stats["payload_total_chars"],
                    "llm.prompt_chars.by_key": payload_stats["payload_key_chars"],
                    "llm.payload_summary": {
                        "keys": sorted(payload.keys()),
                        "question": payload.get("question"),
                    },
                },
            )
            request: dict[str, Any] = {
                "model": model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False, indent=2)},
                ],
            }
            if not model.startswith("gpt-5."):
                request["temperature"] = 0
            started = time.perf_counter()
            response = self._client().chat.completions.create(**request)
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            content = response.choices[0].message.content or ""
            usage = self._usage(response)
            set_span_attrs(
                span,
                {
                    "llm.output_chars": len(content),
                    "llm.duration_ms": duration_ms,
                    "llm.usage.prompt_tokens": usage["prompt_tokens"],
                    "llm.usage.completion_tokens": usage["completion_tokens"],
                    "llm.usage.total_tokens": usage["total_tokens"],
                },
            )
            self._debug_llm_stats("text", model_env, model, provider, duration_ms, payload_stats, usage)
            return content

    def _parse_json_response(self, content: str) -> dict[str, Any]:
        text = content.strip()
        try:
            parsed = json.loads(text)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            pass
        if text.startswith("```"):
            lines = text.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            text = "\n".join(lines).strip()
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            parsed = json.loads(text[start : end + 1])
            return parsed if isinstance(parsed, dict) else {}
        raise ValueError("LLM did not return a valid JSON object")

    def _payload_stats(self, system: str, payload: dict[str, Any]) -> dict[str, Any]:
        payload_key_chars = {
            key: len(json.dumps(value, ensure_ascii=False, default=str))
            for key, value in payload.items()
        }
        return {
            "system_chars": len(system),
            "payload_total_chars": sum(payload_key_chars.values()),
            "payload_key_chars": payload_key_chars,
        }

    def _usage(self, response: Any) -> dict[str, Any]:
        usage = getattr(response, "usage", None)
        return {
            "prompt_tokens": getattr(usage, "prompt_tokens", None),
            "completion_tokens": getattr(usage, "completion_tokens", None),
            "total_tokens": getattr(usage, "total_tokens", None),
        }

    def _debug_llm_stats(
        self,
        kind: str,
        model_env: str,
        model: str,
        provider: str,
        duration_ms: float,
        payload_stats: dict[str, Any],
        usage: dict[str, Any],
    ) -> None:
        if not bool_env("ANALITRICS_DEBUG_LLM_STATS", False):
            return
        key_stats = ", ".join(
            f"{key}={value}"
            for key, value in sorted((payload_stats.get("payload_key_chars") or {}).items())
        )
        print(
            "[llm_stats] "
            f"kind={kind} model_env={model_env} model={model} provider={provider} "
            f"duration_ms={duration_ms} system_chars={payload_stats.get('system_chars')} "
            f"payload_chars={payload_stats.get('payload_total_chars')} "
            f"prompt_tokens={usage.get('prompt_tokens')} completion_tokens={usage.get('completion_tokens')} "
            f"total_tokens={usage.get('total_tokens')} sections={{ {key_stats} }}",
            file=sys.stderr,
            flush=True,
        )
