"""Per-stage LLM model configuration with brand overrides.

Brand overrides and explicitly selected profiles merge field-by-field over
global defaults; list fields (``fallbacks``) replace whole — they do **not**
concat. Missing fields inherit from the level below. Profiles are applied last
so an explicit run profile can reliably bypass brand overrides.

See ``docs/design_decisions.md`` decisions #15-17 for the locked rationale.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, ValidationError

from resound.gateway.base import LLMGatewayConfigError

DEMO_POPULATION_MODEL_PROFILE = "demo_population"
"""Explicit model profile used by the bounded demo-population workflow."""

DEMO_POPULATION_RELIABLE_MODEL_PROFILE = "demo_population_reliable"
"""Demo profile promoting Sonnet 5 after semantic benchmark review."""

DEMO_POPULATION_MODEL_PROFILES = frozenset(
    {DEMO_POPULATION_MODEL_PROFILE, DEMO_POPULATION_RELIABLE_MODEL_PROFILE}
)


class StageConfig(BaseModel):
    """Configuration for one logical LLM stage (filter / classify / ...).

    Pydantic gives free YAML-load validation: type errors surface at startup
    rather than mid-pipeline.
    """

    model: str
    temperature: float
    max_tokens: int
    fallbacks: list[str] = Field(default_factory=list)
    timeout_s: float  # per-stage wall-clock cap for complete()


class ModelsConfig(BaseModel):
    """Resolved stage→config mapping after global+brand merge."""

    stages: dict[str, StageConfig]

    def get_stage_config(self, stage: str) -> StageConfig:
        """Look up a stage's config. Raises on unknown stage (fatal)."""
        try:
            return self.stages[stage]
        except KeyError:
            known = ", ".join(sorted(self.stages.keys())) or "(none)"
            raise LLMGatewayConfigError(
                f"Unknown stage {stage!r}. Known stages: {known}"
            ) from None


# Demo-provisional defaults used when ``config/models.yaml`` is absent or
# silent on a stage. Revisit at demo time per decision #17 (see also
# `feedback_demo_model_selection.md` in user memory).
_BUILTIN_DEFAULTS: dict[str, dict[str, Any]] = {
    "filter": {
        "model": "openai/gpt-4.1-mini",
        "temperature": 0.0,
        "max_tokens": 64,
        "timeout_s": 5.0,
        "fallbacks": ["anthropic/claude-haiku-4-5"],
    },
    "classify": {
        "model": "anthropic/claude-sonnet-4-6",
        "temperature": 0.1,
        "max_tokens": 1024,
        "timeout_s": 30.0,
        "fallbacks": ["openai/gpt-4.1"],
    },
    "routing_tiebreaker": {
        "model": "openai/gpt-4.1-mini",
        "temperature": 0.0,
        "max_tokens": 128,
        "timeout_s": 10.0,
        "fallbacks": ["anthropic/claude-haiku-4-5"],
    },
    "route": {
        "model": "openai/gpt-4.1-mini",
        "temperature": 0.0,
        "max_tokens": 256,
        "timeout_s": 10.0,
        "fallbacks": ["anthropic/claude-haiku-4-5"],
    },
    "memory_query": {
        "model": "openai/gpt-4.1-mini",
        "temperature": 0.0,
        "max_tokens": 256,
        "timeout_s": 10.0,
        "fallbacks": ["anthropic/claude-haiku-4-5"],
    },
}


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with path.open() as f:
            data = yaml.safe_load(f) or {}
    except yaml.YAMLError as exc:
        raise LLMGatewayConfigError(
            f"Malformed YAML in {path}: {exc}"
        ) from exc
    if not isinstance(data, dict):
        raise LLMGatewayConfigError(
            f"{path} must be a mapping at the top level, got {type(data).__name__}"
        )
    return data


def _extract_stages(raw: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Pull the stage map out of a YAML doc.

    Accepts either the global format with a ``defaults:`` wrapper:

        defaults:
          filter: {...}

    or a brand-style file with stage configs at the top level:

        filter: {...}
    """
    if "defaults" in raw and isinstance(raw["defaults"], dict):
        return raw["defaults"]
    return raw


def _merge_stages(
    base: dict[str, dict[str, Any]],
    override: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Field-level merge of ``override`` on top of ``base``.

    Per decision #16: missing fields inherit; list fields (notably
    ``fallbacks``) replace whole — never concat.
    """
    merged = {stage: dict(cfg) for stage, cfg in base.items()}
    for stage, override_cfg in override.items():
        if not isinstance(override_cfg, dict):
            raise LLMGatewayConfigError(
                f"Stage {stage!r} override must be a mapping, "
                f"got {type(override_cfg).__name__}"
            )
        if stage in merged:
            merged[stage].update(override_cfg)  # field-level overwrite
        else:
            merged[stage] = dict(override_cfg)
    return merged


def load_models_config(
    brand_slug: str | None = None,
    config_dir: Path | None = None,
    brands_dir: Path | None = None,
    profile: str | None = None,
) -> ModelsConfig:
    """Load models.yaml, optionally merging a brand override and named profile.

    Layering (top wins): selected profile → ``brands/<slug>/models.yaml`` →
    global defaults → built-in defaults. Applying the profile last is
    intentional: run-scoped profiles must not inherit a conflicting brand model.

    Args:
        brand_slug: If given, merge ``brands/<slug>/models.yaml`` on top.
        profile: If given, merge that named ``profiles`` entry on top of global
            and brand configuration.
        config_dir: Directory holding the global ``models.yaml``. Defaults to
            ``./config``.
        brands_dir: Directory holding brand subdirectories. Defaults to
            ``./brands``.

    Raises:
        LLMGatewayConfigError: malformed YAML, non-mapping override, or stage
            config that fails Pydantic validation.
    """
    config_dir = config_dir or Path("config")
    brands_dir = brands_dir or Path("brands")

    global_raw = _load_yaml(config_dir / "models.yaml")
    merged = _merge_stages(_BUILTIN_DEFAULTS, _extract_stages(global_raw))

    if brand_slug is not None:
        brand_raw = _load_yaml(brands_dir / brand_slug / "models.yaml")
        merged = _merge_stages(merged, _extract_stages(brand_raw))

    if profile is not None:
        profiles = global_raw.get("profiles", {})
        if not isinstance(profiles, dict):
            raise LLMGatewayConfigError("models.yaml 'profiles' must be a mapping")
        profile_raw = profiles.get(profile)
        if profile_raw is None:
            known = ", ".join(sorted(profiles)) or "(none)"
            raise LLMGatewayConfigError(
                f"Unknown model profile {profile!r}. Known profiles: {known}"
            )
        if not isinstance(profile_raw, dict):
            raise LLMGatewayConfigError(
                f"Model profile {profile!r} must be a mapping, "
                f"got {type(profile_raw).__name__}"
            )
        merged = _merge_stages(merged, _extract_stages(profile_raw))

    try:
        stages = {name: StageConfig(**cfg) for name, cfg in merged.items()}
    except ValidationError as exc:
        raise LLMGatewayConfigError(
            f"Invalid stage configuration: {exc}"
        ) from exc

    return ModelsConfig(stages=stages)
