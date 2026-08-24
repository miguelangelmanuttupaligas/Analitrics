from __future__ import annotations

import json
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
        if provider == "local":
            client = OpenAI(
                api_key=env("ANALITRICS_LOCAL_API_KEY", "local-not-required"),
                base_url=env("ANALITRICS_LOCAL_BASE_URL", "http://host.docker.internal:11434/v1"),
            )
        else:
            client = OpenAI(api_key=env("OPENAI_API_KEY"))
        self._clients[provider] = client
        return client

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
        with self._tracer.start_as_current_span("llm_json") as span:
            set_span_attrs(
                span,
                {
                    "llm.model": model,
                    "llm.model_env": model_env,
                    "llm.provider": provider,
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
            response = self._client().chat.completions.create(**request)
            parsed = self._parse_json_response(response.choices[0].message.content or "{}")
            set_span_attrs(
                span,
                {
                    "llm.output_keys": sorted(parsed.keys()),
                    "llm.usage.prompt_tokens": getattr(response.usage, "prompt_tokens", None),
                    "llm.usage.completion_tokens": getattr(response.usage, "completion_tokens", None),
                    "llm.usage.total_tokens": getattr(response.usage, "total_tokens", None),
                },
            )
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
        with self._tracer.start_as_current_span("llm_text") as span:
            set_span_attrs(
                span,
                {
                    "llm.model": model,
                    "llm.model_env": model_env,
                    "llm.provider": provider,
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
            response = self._client().chat.completions.create(**request)
            content = response.choices[0].message.content or ""
            set_span_attrs(
                span,
                {
                    "llm.output_chars": len(content),
                    "llm.usage.prompt_tokens": getattr(response.usage, "prompt_tokens", None),
                    "llm.usage.completion_tokens": getattr(response.usage, "completion_tokens", None),
                    "llm.usage.total_tokens": getattr(response.usage, "total_tokens", None),
                },
            )
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
