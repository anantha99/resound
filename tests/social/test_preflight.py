from pathlib import Path

import pytest
from pydantic import ValidationError

from resound.social.contracts import ProviderEvidenceManifest, ProviderEvidenceRecord
from resound.social.preflight import (
    PreflightError,
    build_approval_patch,
    load_evidence_manifest,
    validate_manifest_entry,
)
from resound.social.registry import ACTOR_REGISTRY


def test_manifest_truthfully_scaffolds_fourteen_incomplete_path_captures() -> None:
    manifest = load_evidence_manifest(Path("tests/fixtures/apify/manifest.json"))

    assert len(manifest.entries) == 14
    assert not any(entry.approval_ready for entry in manifest.entries)
    reddit = next(
        entry for entry in manifest.entries if entry.actor_id == "solidcode/reddit-scraper"
    )
    assert reddit.build_id == "LxJ3Vm9RHSEJcQEYK"
    assert reddit.build_number == "1.1.31"
    assert reddit.provider_declared_input_schema_sha256 == (
        "58ea3036200e494ef3e8405b8de3db9fe8b47abab4c3216e8d460c95ff33ddca"
    )
    assert reddit.provider_declared_output_schema_reference is None
    assert reddit.canary_required is True
    assert reddit.sanitized_input == {"subreddits": [], "searches": [], "startUrls": []}


def test_fixture_shape_is_not_accepted_as_formal_output_or_canary() -> None:
    entry = load_evidence_manifest(Path("tests/fixtures/apify/manifest.json")).entries[0]
    with pytest.raises(PreflightError, match="not approval-ready"):
        validate_manifest_entry(entry)


def test_replacement_x_and_source_specific_url_evidence_are_recorded() -> None:
    entries = load_evidence_manifest(Path("tests/fixtures/apify/manifest.json")).entries
    x = next(entry for entry in entries if entry.actor_id == "apidojo/twitter-scraper-lite")
    youtube = next(entry for entry in entries if entry.actor_id == "streamers/youtube-scraper")
    tiktok = next(entry for entry in entries if entry.actor_id == "clockworks/tiktok-scraper")

    assert (x.build_id, x.build_number) == ("NqWYV0k5wlJ9R5bi6", "0.0.935")
    assert x.canary_required is True
    assert youtube.input_url_shape == "request_object"
    assert tiktok.minimum_call_charge_usd == 0.50


def test_formal_output_fixture_and_pricing_evidence_build_deterministic_patch() -> None:
    actor = ACTOR_REGISTRY["x_discovery"]
    entry = ProviderEvidenceRecord(
        source="x",
        actor_role="discovery",
        actor_id=actor.actor_id,
        build_id=actor.build_id,
        build_number=actor.build_number,
        path="mention_discovery",
        sanitized_input={"searchTerms": ["Acme"]},
        input_url_shape="string",
        provider_declared_input_schema_reference="provider://input",
        provider_declared_input_schema_sha256="a" * 64,
        provider_declared_output_schema_reference="provider://output",
        provider_declared_output_schema_sha256="b" * 64,
        fixture_path="tests/fixtures/apify/actor.json",
        fixture_sha256="c" * 64,
        fixture_derived_shape_reference="tests/fixtures/apify/actor.shape.json",
        fixture_derived_shape_sha256="d" * 64,
        charge_quantum_usd="0.001",
        minimum_call_charge_usd="0.01",
        conservative_request_cost_usd="0.05",
        pricing_evidence_reference="provider://pricing",
        canary_required=False,
    )
    manifest = ProviderEvidenceManifest(manifest_version="test-1", entries=(entry,))
    source = {
        "paths": {"mention_discovery": {"enabled": True}},
        "search_terms": ["Acme"],
    }
    first = build_approval_patch(source="x", source_config=source, manifest=manifest)
    second = build_approval_patch(source="x", source_config=source, manifest=manifest)

    assert first == second
    assert first["preflight_required"] is False
    assert len(first["approved_envelope_fingerprint"]) == 64


def test_manifest_identity_never_matches_same_named_path_from_another_source() -> None:
    actor = ACTOR_REGISTRY["youtube_discovery"]
    entry = ProviderEvidenceRecord(
        source="youtube",
        actor_role="discovery",
        actor_id=actor.actor_id,
        build_id=actor.build_id,
        build_number=actor.build_number,
        path="mention_discovery",
        sanitized_input={"searchQueries": ["Acme"]},
        input_url_shape="request_object",
        provider_declared_input_schema_reference="provider://input",
        provider_declared_input_schema_sha256="a" * 64,
        provider_declared_output_schema_reference="provider://output",
        provider_declared_output_schema_sha256="b" * 64,
        fixture_path="tests/fixtures/apify/actor.json",
        fixture_sha256="c" * 64,
        fixture_derived_shape_reference="tests/fixtures/apify/actor.shape.json",
        fixture_derived_shape_sha256="d" * 64,
        charge_quantum_usd="0.001",
        minimum_call_charge_usd="0.01",
        conservative_request_cost_usd="0.05",
        pricing_evidence_reference="provider://pricing",
        canary_required=False,
    )
    manifest = ProviderEvidenceManifest(manifest_version="test-1", entries=(entry,))

    with pytest.raises(PreflightError, match="x/mention_discovery/discovery; found 0"):
        build_approval_patch(
            source="x",
            source_config={
                "paths": {"mention_discovery": {"enabled": True}},
                "search_terms": ["Acme"],
            },
            manifest=manifest,
        )


def test_manifest_rejects_duplicate_identity_and_wrong_registered_actor() -> None:
    actor = ACTOR_REGISTRY["x_discovery"]
    base = ProviderEvidenceRecord(
        source="x",
        actor_role="discovery",
        actor_id=actor.actor_id,
        build_id=actor.build_id,
        build_number=actor.build_number,
        path="mention_discovery",
        sanitized_input={"searchTerms": ["Acme"]},
        input_url_shape="string",
        provider_declared_input_schema_reference="provider://input",
        provider_declared_input_schema_sha256="a" * 64,
        provider_declared_output_schema_reference="provider://output",
        provider_declared_output_schema_sha256="b" * 64,
        fixture_path="tests/fixtures/apify/actor.json",
        fixture_sha256="c" * 64,
        fixture_derived_shape_reference="tests/fixtures/apify/actor.shape.json",
        fixture_derived_shape_sha256="d" * 64,
        charge_quantum_usd="0.001",
        minimum_call_charge_usd="0.01",
        conservative_request_cost_usd="0.05",
        pricing_evidence_reference="provider://pricing",
        canary_required=False,
    )
    with pytest.raises(ValidationError, match="duplicate source/path/actor-role"):
        ProviderEvidenceManifest(manifest_version="test-1", entries=(base, base))

    wrong = base.model_copy(update={"build_id": "wrong-build"})
    with pytest.raises(PreflightError, match="actor/build mismatch"):
        build_approval_patch(
            source="x",
            source_config={
                "paths": {"mention_discovery": {"enabled": True}},
                "search_terms": ["Acme"],
            },
            manifest=ProviderEvidenceManifest(manifest_version="test-1", entries=(wrong,)),
        )

