from __future__ import annotations

from copy import deepcopy
from decimal import Decimal

import pytest

from resound.config import BrandConfig
from resound.memory import SqlMemory
from resound.social.config import approval_envelope_fingerprint
from resound.social.contracts import (
    ResolvedProcessingConfigSnapshot,
    SelectedPathInput,
    SourceLimitOverrides,
    SourceSyncInput,
)
from resound.social.resolver import parse_cli_request, resolve_public_listening_request

HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64


def _approved_source(*, source: str = "reddit") -> dict:
    config = {
        "enabled": True,
        "preflight_required": False,
        "manifest_version": "test-1",
        "search_terms": ["Acme"],
        "paths": {
            "official_discovery": {"enabled": True, "selectors": ["https://acme.test"]},
            "mention_discovery": {"enabled": True, "selectors": ["Acme"]},
        },
        "limits": {
            "max_signals_per_source": 100,
            "max_items_per_path": 25,
            "max_parents_per_path": 10,
            "max_comments_per_parent": 5,
            "max_comments_per_path": 25,
            "max_comments_per_source": 50,
            "max_runs_per_source": 10,
            "max_cost_usd_per_source": "1.00",
            "page_size": 100,
            "deadline_reserve_seconds": 30,
        },
        "provider_evidence": [
            {
                "actor_id": f"owner/{source}",
                "build_id": "build-id",
                "build_number": "1.2.3",
                "provider_declared_input_schema_reference": "provider://input",
                "provider_declared_input_schema_sha256": HASH_A,
                "provider_declared_output_schema_reference": "provider://output",
                "provider_declared_output_schema_sha256": HASH_B,
                "fixture_derived_shape_reference": "fixtures/shape.json",
                "fixture_derived_shape_sha256": HASH_C,
                "canary_required": False,
                "charge_quantum_usd": "0.001",
                "minimum_call_charge_usd": "0.01",
                "conservative_request_cost_usd": "0.05",
            }
        ],
    }
    config["approved_envelope_fingerprint"] = approval_envelope_fingerprint(config)
    return config


def _brand(source_config: dict) -> BrandConfig:
    return BrandConfig(
        slug="acme",
        sources=source_config,
        routing={"rules": [{"area": "support"}]},
        people={"people": {"owner": {"name": "A"}}},
        understanding="Acme makes reliable products.",
    )


class MemorySpy:
    def __init__(self) -> None:
        self.calls: list[tuple[int, int, dict]] = []

    def replace_brand_source_config(self, organization_id, brand_id, source_config):
        self.calls.append((organization_id, brand_id, source_config))


def _request(**kwargs) -> SourceSyncInput:
    return SourceSyncInput(brand_id="acme", internal_brand_id=7, **kwargs)


def test_resolver_allocates_signal_cap_and_materializes_complete_request() -> None:
    memory = MemorySpy()
    request = _request(
        limits=SourceLimitOverrides(max_signals_per_source=9),
    )

    resolved = resolve_public_listening_request(
        request,
        brand_config=_brand({"reddit": _approved_source()}),
        memory=memory,
        organization_id=3,
        workflow_job_id=11,
        owner_token="owner-token",
        environment={},
    )

    assert resolved.organization_id == 3
    assert resolved.brand_id == 7
    assert resolved.brand_slug == "acme"
    assert resolved.workflow_job_id == 11
    assert resolved.owner_token == "owner-token"
    assert [path.requested_row_maximum for path in resolved.sources[0].paths] == [5, 4]
    assert sum(path.requested_row_maximum for path in resolved.sources[0].paths) == 9
    assert resolved.fingerprints["reddit"] == resolved.sources[0].approval_fingerprint
    assert memory.calls == [(3, 7, _brand({"reddit": _approved_source()}).sources)]


def test_changed_provider_or_processing_values_change_execution_fingerprint() -> None:
    base = _brand({"reddit": _approved_source()})
    first = resolve_public_listening_request(_request(), brand_config=base, environment={})
    changed = deepcopy(base.sources)
    changed["reddit"]["provider_evidence"][0]["build_number"] = "1.2.4"
    changed["reddit"]["approved_envelope_fingerprint"] = approval_envelope_fingerprint(
        changed["reddit"]
    )
    second = resolve_public_listening_request(
        _request(), brand_config=_brand(changed), environment={}
    )
    context_changed = _brand({"reddit": _approved_source()})
    context_changed.understanding = "Changed context"
    third = resolve_public_listening_request(
        _request(), brand_config=context_changed, environment={}
    )

    assert first.fingerprints["reddit"].value != second.fingerprints["reddit"].value
    assert first.fingerprints["reddit"].value != third.fingerprints["reddit"].value


def test_manual_boolean_bypass_and_stale_yaml_do_not_refresh_database() -> None:
    memory = MemorySpy()
    config = _approved_source()
    config["search_terms"] = ["changed after approval"]

    with pytest.raises(ValueError, match="manually clearing"):
        resolve_public_listening_request(
            _request(),
            brand_config=_brand({"reddit": config}),
            memory=memory,
            organization_id=3,
            environment={},
        )

    assert memory.calls == []


def test_alias_duplicates_upward_limits_and_infeasible_caps_are_rejected() -> None:
    config = _approved_source(source="youtube")
    brand = _brand({"youtube": config})
    with pytest.raises(ValueError, match="duplicate source aliases"):
        resolve_public_listening_request(
            _request(selected_sources=("youtube", "youtube_comments")),
            brand_config=brand,
            environment={},
        )
    with pytest.raises(ValueError, match="may only lower"):
        resolve_public_listening_request(
            _request(limits=SourceLimitOverrides(max_signals_per_source=101)),
            brand_config=_brand({"reddit": _approved_source()}),
            environment={},
        )
    with pytest.raises(ValueError, match="cannot allocate one row"):
        resolve_public_listening_request(
            _request(limits=SourceLimitOverrides(max_signals_per_source=1)),
            brand_config=_brand({"reddit": _approved_source()}),
            environment={},
        )


def test_path_dependencies_and_instagram_free_text_capability() -> None:
    instagram = _approved_source(source="instagram")
    instagram["search_terms"] = ["caption phrase"]
    instagram["approved_envelope_fingerprint"] = approval_envelope_fingerprint(instagram)
    with pytest.raises(ValueError, match="does not support free-text"):
        resolve_public_listening_request(
            _request(selected_sources=("instagram",)),
            brand_config=_brand({"instagram": instagram}),
            environment={},
        )

    dependency_config = _approved_source(source="instagram")
    dependency_config.pop("search_terms")
    dependency_config["hashtags"] = ["acme"]
    dependency_config["paths"]["official_comments"] = {"enabled": True}
    dependency_config["approved_envelope_fingerprint"] = approval_envelope_fingerprint(
        dependency_config
    )
    with pytest.raises(ValueError, match="official_comments requires"):
        resolve_public_listening_request(
            _request(
                selected_sources=("instagram",),
                selected_paths=(
                    SelectedPathInput(source="instagram", paths=("official_comments",)),
                )
            ),
            brand_config=_brand({"instagram": dependency_config}),
            environment={},
        )


def test_cli_and_api_request_models_serialize_identically() -> None:
    api = SourceSyncInput(
        brand_id="acme",
        internal_brand_id=7,
        selected_sources=("reddit",),
        selected_paths=(
            SelectedPathInput(source="reddit", paths=("mention_discovery",)),
        ),
        limits=SourceLimitOverrides(
            max_signals_per_source=12,
            max_cost_usd_per_source=Decimal("0.50"),
        ),
    )
    cli = parse_cli_request(
        brand_id="acme",
        internal_brand_id=7,
        sources=["reddit"],
        paths=["reddit:mention_discovery"],
        max_signals_per_source=12,
        max_cost_usd_per_source=Decimal("0.50"),
    )
    assert cli.model_dump_json() == api.model_dump_json()


def test_approved_yaml_replaces_the_single_brandrow_source_copy(tmp_path) -> None:
    memory = SqlMemory(f"sqlite:///{tmp_path / 'resolver.db'}")
    organization_id = memory.ensure_organization("acme-org", "Acme Org")
    brand_row = memory.ensure_brand(
        organization_id,
        "acme",
        "Acme",
        source_config={"reddit": {"stale": True}},
    )
    brand = _brand({"reddit": _approved_source()})

    resolve_public_listening_request(
        SourceSyncInput(brand_id="acme", internal_brand_id=brand_row.id),
        brand_config=brand,
        memory=memory,
        organization_id=organization_id,
        environment={},
    )

    refreshed = next(row for row in memory.list_brands_for_tenant(_tenant(organization_id)))
    assert refreshed.source_config == brand.sources


def test_processing_snapshot_is_deeply_immutable_and_bounded() -> None:
    routing = {"rules": [{"area": "support"}]}
    snapshot = ResolvedProcessingConfigSnapshot.create(
        brand_context="Acme",
        routing_config=routing,
        people_config={},
        model_profile="demo_population",
    )
    routing["rules"].append({"area": "sales"})

    assert len(snapshot.routing_config["rules"]) == 1
    with pytest.raises(TypeError):
        snapshot.routing_config["rules"] = ()
    with pytest.raises(ValueError, match="16384"):
        ResolvedProcessingConfigSnapshot.create(
            brand_context="x" * (16 * 1024 + 1),
            routing_config={},
            people_config={},
            model_profile=None,
        )
    with pytest.raises(ValueError, match="secret"):
        ResolvedProcessingConfigSnapshot.create(
            brand_context="Acme",
            routing_config={},
            people_config={},
            model_profile="sk-secret-value",
        )


def _tenant(organization_id):
    from resound.tenancy import TenantContext

    return TenantContext(organization_id, "acme-org", team_id=None, user_id=None)

