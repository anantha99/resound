from resound.social.contracts import (
    AdapterResult,
    ApprovedSourceConfigFingerprint,
    canonical_public_source,
    public_source_aliases,
)


def test_public_source_alias_helpers_canonicalize_known_aliases_only() -> None:
    assert canonical_public_source(" Twitter ") == "x"
    assert canonical_public_source("x_public") == "x"
    assert canonical_public_source("youtube_comments") == "youtube"
    assert canonical_public_source("g2") == "g2"
    assert set(public_source_aliases("x")) == {"twitter", "x", "x_public"}
    assert set(public_source_aliases("youtube_comments")) == {
        "youtube",
        "youtube_comments",
    }
    assert public_source_aliases("g2") == ("g2",)


def test_adapter_result_canonicalizes_legacy_runtime_platform() -> None:
    fingerprint = ApprovedSourceConfigFingerprint(
        value="a" * 64,
        approval_envelope_value="b" * 64,
        manifest_version="test-1",
    )

    result = AdapterResult(
        source="youtube",
        platform="youtube_comments",
        status="ok",
        paths=(),
        max_signals_per_source=1,
        config_fingerprint=fingerprint,
    )

    assert result.platform == "youtube"
