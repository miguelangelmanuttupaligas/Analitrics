from __future__ import annotations

from typing import Any

from .control_plane import CatalogRepository
from .models import AgentRequest


STEP_BY_TYPE = {
    "concept": 1,
    "business_concept": 1,
    "metric": 2,
    "indicator": 2,
    "dimension": 3,
    "business_rule": 4,
    "rule": 4,
    "correction": 5,
    "interpretation_correction": 5,
    "business_definition": 6,
    "definition": 6,
}


class CatalogFeedbackApplier:
    def __init__(self, catalog_repository: CatalogRepository) -> None:
        self._catalog_repository = catalog_repository

    def apply_if_confirmed(self, request: AgentRequest, proposal: dict[str, Any] | None) -> dict[str, Any] | None:
        applied = self.apply_many_if_confirmed(request, [proposal] if proposal else [])
        return applied[0] if applied else None

    def apply_many_if_confirmed(self, request: AgentRequest, proposals: list[dict[str, Any] | None]) -> list[dict[str, Any]]:
        applied: list[dict[str, Any]] = []
        for proposal in proposals:
            saved = self._apply_one_if_confirmed(request, proposal)
            if saved:
                applied.append(saved)
        return applied

    def _apply_one_if_confirmed(self, request: AgentRequest, proposal: dict[str, Any] | None) -> dict[str, Any] | None:
        if not self._should_apply(proposal):
            return None
        assert proposal is not None
        content = str(proposal.get("content") or "").strip()
        if not content:
            return None
        saved = self._catalog_repository.save_feedback(
            tenant_id=request.tenant_id,
            user_id=request.user_id or "anonymous",
            conversation_id=request.conversation_id or "",
            source_file_id=self._optional_str(proposal.get("source_file_id")),
            source_filename=self._optional_str(proposal.get("source_filename")),
            step=self._step_for(proposal),
            label=self._label_for(proposal),
            content=content,
        )
        return {
            **proposal,
            "applied": True,
            "feedback_id": saved.get("feedbackId"),
            "step": saved.get("step"),
            "label": saved.get("label"),
            "content": saved.get("content"),
            "source_file_id": saved.get("sourceFileId"),
            "source_filename": saved.get("sourceFilename"),
            "updated_at": saved.get("updatedAt"),
        }

    def _should_apply(self, proposal: dict[str, Any] | None) -> bool:
        if not isinstance(proposal, dict):
            return False
        if not proposal.get("auto_apply"):
            return False
        return proposal.get("requires_user_confirmation") is False

    def _step_for(self, proposal: dict[str, Any]) -> int:
        explicit_step = proposal.get("step")
        try:
            step = int(explicit_step)
        except (TypeError, ValueError):
            step = STEP_BY_TYPE.get(str(proposal.get("type") or "").lower(), 5)
        return min(6, max(1, step))

    def _label_for(self, proposal: dict[str, Any]) -> str:
        label = str(proposal.get("label") or "").strip()
        if label:
            return label[:120]
        proposal_type = str(proposal.get("type") or "").lower()
        if proposal_type in {"business_definition", "definition"}:
            return "Definición registrada desde el chat"
        if proposal_type in {"business_rule", "rule"}:
            return "Regla registrada desde el chat"
        return "Corrección registrada desde el chat"

    def _optional_str(self, value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None
