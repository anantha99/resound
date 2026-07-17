"""No-write/no-LLM provider evidence validation and deterministic approval patches."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from resound.social.config import approval_envelope_fingerprint, normalize_selectors
from resound.social.contracts import ProviderEvidenceManifest, ProviderEvidenceRecord


class PreflightError(ValueError):
    pass


def load_evidence_manifest(path: Path) -> ProviderEvidenceManifest:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return ProviderEvidenceManifest.model_validate(payload)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise PreflightError(f"invalid provider evidence manifest: {exc}") from exc


def validate_manifest_entry(entry: ProviderEvidenceRecord) -> None:
    if entry.provider_declared_output_schema_reference is None and not entry.canary_required:
        raise PreflightError("missing formal output schema requires a bounded live canary")
    if not entry.approval_ready:
        raise PreflightError(
            f"actor {entry.actor_id} build {entry.build_number} is not approval-ready: "
            "fixture/shape/formal-output-or-canary evidence is incomplete"
        )


def build_approval_patch(
    *,
    source: str,
    source_config: dict[str, Any],
    manifest: ProviderEvidenceManifest,
) -> dict[str, Any]:
    """Return a patch only from already-captured evidence; never starts an actor."""

    paths = source_config.get("paths", {"mention_discovery": {"enabled": True}})
    selected = [
        key
        for key, value in paths.items()
        if isinstance(value, dict) and value.get("enabled", True)
    ]
    for path in selected:
        normalize_selectors(source, source_config, path)
    entries = [entry for entry in manifest.entries if entry.path.value in selected]
    if not entries:
        raise PreflightError(f"manifest has no evidence for selected {source} paths")
    for entry in entries:
        validate_manifest_entry(entry)
    patched = dict(source_config)
    patched["manifest_version"] = manifest.manifest_version
    patched["provider_evidence"] = [_resolved_evidence(entry) for entry in entries]
    patched["preflight_required"] = False
    patched["approved_envelope_fingerprint"] = approval_envelope_fingerprint(patched)
    return patched


def _resolved_evidence(entry: ProviderEvidenceRecord) -> dict[str, Any]:
    return {
        "actor_id": entry.actor_id,
        "build_id": entry.build_id,
        "build_number": entry.build_number,
        "provider_declared_input_schema_reference": entry.provider_declared_input_schema_reference,
        "provider_declared_input_schema_sha256": entry.provider_declared_input_schema_sha256,
        "provider_declared_output_schema_reference": (
            entry.provider_declared_output_schema_reference
        ),
        "provider_declared_output_schema_sha256": entry.provider_declared_output_schema_sha256,
        "fixture_derived_shape_reference": entry.fixture_derived_shape_reference,
        "fixture_derived_shape_sha256": entry.fixture_derived_shape_sha256,
        "canary_required": entry.canary_required,
        "canary_evidence_reference": entry.canary_evidence_reference,
        "canary_evidence_sha256": entry.canary_evidence_sha256,
        "charge_quantum_usd": entry.charge_quantum_usd,
        "minimum_call_charge_usd": entry.minimum_call_charge_usd,
        "conservative_request_cost_usd": entry.conservative_request_cost_usd,
    }

