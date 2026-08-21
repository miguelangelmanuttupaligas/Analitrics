from __future__ import annotations

import json
from typing import Any

from openai import OpenAI

from .config import env
from .tracing import set_span_attrs


class JsonLlmClient:
    def __init__(self, tracer: Any) -> None:
        self._tracer = tracer
        self._client: OpenAI | None = None

    @property
    def client(self) -> OpenAI:
        if self._client is None:
            self._client = OpenAI(api_key=env("OPENAI_API_KEY"))
        return self._client

    def complete_json(
        self,
        system: str,
        payload: dict[str, Any],
        model_env: str,
        default_model: str,
    ) -> dict[str, Any]:
        model = env(model_env, env("ANALITRICS_NL_SQL_MODEL", default_model))
        with self._tracer.start_as_current_span("llm_json") as span:
            set_span_attrs(
                span,
                {
                    "llm.model": model,
                    "llm.model_env": model_env,
                    "llm.payload_summary": {
                        "keys": sorted(payload.keys()),
                        "question": payload.get("question"),
                    },
                },
            )
            request: dict[str, Any] = {
                "model": model,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False, indent=2)},
                ],
            }
            if not model.startswith("gpt-5."):
                request["temperature"] = 0
            response = self.client.chat.completions.create(**request)
            parsed = json.loads(response.choices[0].message.content or "{}")
            set_span_attrs(span, {"llm.output_keys": sorted(parsed.keys())})
            return parsed
