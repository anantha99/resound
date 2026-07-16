"""Gateway tests — covers the testStrategy from subtasks 1.1-1.6.

Layout:
    1. base.py                  — ABC + LLMResponse + exception hierarchy
    2. models_config.py         — YAML load, merge, defaults, errors
    3. openrouter.py            — retry, fallback, timeout, JSON mode, cost
    4. __init__.py / exports    — public API + build_gateway
"""

from __future__ import annotations

import logging
import time
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    RateLimitError,
)

import resound.gateway as gateway_pkg
from resound.classifiers.openrouter import parse_classification_response_strict
from resound.gateway import (
    DEMO_POPULATION_MODEL_PROFILE,
    DEMO_POPULATION_MODEL_PROFILES,
    DEMO_POPULATION_RELIABLE_MODEL_PROFILE,
    LLMGateway,
    LLMGatewayAuthError,
    LLMGatewayConfigError,
    LLMGatewayError,
    LLMGatewayExhaustedError,
    LLMGatewayParseError,
    LLMGatewayTimeoutError,
    LLMResponse,
    ModelsConfig,
    OpenRouterGateway,
    StageConfig,
    build_gateway,
    load_models_config,
)

# =============================================================================
# Helpers — fake OpenAI client + exception factories
# =============================================================================

_REQ = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")


def _status_error(code: int, msg: str = "boom") -> APIStatusError:
    response = httpx.Response(code, request=_REQ)
    return APIStatusError(msg, response=response, body=None)


def _rate_limit() -> RateLimitError:
    response = httpx.Response(429, request=_REQ)
    return RateLimitError("rate limited", response=response, body=None)


def _timeout() -> APITimeoutError:
    return APITimeoutError(request=_REQ)


def _conn_error() -> APIConnectionError:
    return APIConnectionError(request=_REQ)


def _ok_response(
    content: str = '{"ok": true}',
    prompt_tokens: int = 10,
    completion_tokens: int = 20,
    cost: float | None = 0.000123,
) -> Any:
    """Mimic an openai.ChatCompletion enough for the gateway."""
    usage_attrs: dict[str, Any] = {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
    }
    if cost is not None:
        usage_attrs["cost"] = cost
    usage = SimpleNamespace(**usage_attrs)
    msg = SimpleNamespace(content=content)
    choice = SimpleNamespace(message=msg)
    return SimpleNamespace(
        choices=[choice],
        usage=usage,
        model_dump=lambda: {
            "choices": [{"message": {"content": content}}],
            "usage": usage_attrs,
        },
    )


class FakeClient:
    """Stand-in for ``openai.OpenAI``. Each call pops the next behavior:
    if it's an exception, it's raised; otherwise it's returned."""

    def __init__(self, behaviors: list[Any]):
        self._behaviors = list(behaviors)
        self.calls: list[dict] = []
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(create=self._create)
        )

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        if not self._behaviors:
            raise AssertionError("FakeClient ran out of scripted behaviors")
        b = self._behaviors.pop(0)
        if isinstance(b, BaseException):
            raise b
        return b


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch):
    """Backoff still computes correctly but doesn't actually wait."""
    monkeypatch.setattr(time, "sleep", lambda _s: None)


def _stage_cfg(
    model: str = "primary/m",
    fallbacks: list[str] | None = None,
    timeout_s: float = 30.0,
) -> StageConfig:
    return StageConfig(
        model=model,
        temperature=0.0,
        max_tokens=128,
        fallbacks=fallbacks or [],
        timeout_s=timeout_s,
    )


def _models_config(stage_cfg: StageConfig, stage: str = "classify") -> ModelsConfig:
    return ModelsConfig(stages={stage: stage_cfg})


# =============================================================================
# 1. base.py — ABC + LLMResponse + exception hierarchy (subtask 1.1)
# =============================================================================


class TestBase:
    def test_llmresponse_all_fields(self):
        r = LLMResponse(
            content="hi",
            model_used="m/x",
            tokens_in=5,
            tokens_out=7,
            cost_usd=0.001,
            latency_ms=12.5,
            raw_response={"a": 1},
        )
        assert r.content == "hi"
        assert r.model_used == "m/x"
        assert r.tokens_in == 5
        assert r.tokens_out == 7
        assert r.cost_usd == 0.001
        assert r.latency_ms == 12.5
        assert r.raw_response == {"a": 1}

    def test_llmresponse_cost_optional(self):
        # Per design #7, cost is None when OpenRouter omits usage.cost.
        r = LLMResponse(
            content="x",
            model_used="m",
            tokens_in=1,
            tokens_out=1,
            latency_ms=1.0,
        )
        assert r.cost_usd is None

    def test_llmgateway_is_abstract(self):
        with pytest.raises(TypeError):
            LLMGateway()  # type: ignore[abstract]

    def test_subclass_must_implement_complete(self):
        class Incomplete(LLMGateway):
            pass

        with pytest.raises(TypeError):
            Incomplete()  # type: ignore[abstract]

        class Concrete(LLMGateway):
            def complete(self, stage, prompt, response_schema=None):
                return LLMResponse(
                    content="ok", model_used="m",
                    tokens_in=0, tokens_out=0, latency_ms=0.0,
                )

        assert Concrete().complete("classify", "hi").content == "ok"

    def test_exception_hierarchy(self):
        # All recoverable + fatal errors share the LLMGatewayError root.
        for cls in (
            LLMGatewayConfigError,
            LLMGatewayAuthError,
            LLMGatewayExhaustedError,
            LLMGatewayTimeoutError,
            LLMGatewayParseError,
        ):
            assert issubclass(cls, LLMGatewayError)

    def test_exhausted_carries_attempts(self):
        err = LLMGatewayExhaustedError("done", attempts=7)
        assert err.attempts == 7

    def test_parse_error_carries_raw_text(self):
        err = LLMGatewayParseError("no json", raw_text="prose only")
        assert err.raw_text == "prose only"


# =============================================================================
# 2. models_config.py — YAML load + merge + defaults + errors (subtask 1.2)
# =============================================================================


class TestModelsConfig:
    def test_builtin_defaults_when_no_yaml(self, tmp_path):
        cfg = load_models_config(
            config_dir=tmp_path / "missing", brands_dir=tmp_path / "missing"
        )
        # Built-ins cover the core stages.
        assert {"filter", "classify", "routing_tiebreaker", "route", "memory_query"} <= set(
            cfg.stages
        )
        assert cfg.stages["classify"].model == "anthropic/claude-sonnet-4-6"
        assert cfg.stages["filter"].timeout_s == 5.0

    def test_global_yaml_overrides_builtin(self, tmp_path):
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "models.yaml").write_text(
            "defaults:\n"
            "  filter:\n"
            "    model: x/yz\n"
            "    fallbacks: [a/a, b/b, c/c]\n"
        )
        cfg = load_models_config(
            config_dir=config_dir, brands_dir=tmp_path / "no-brands"
        )
        # Field-level merge: model overridden, the rest inherit.
        assert cfg.stages["filter"].model == "x/yz"
        assert cfg.stages["filter"].temperature == 0.0  # inherited
        assert cfg.stages["filter"].fallbacks == ["a/a", "b/b", "c/c"]

    def test_brand_override_field_level(self, tmp_path):
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "models.yaml").write_text(
            "defaults:\n  classify:\n    model: g/global\n    temperature: 0.2\n"
        )
        brands_dir = tmp_path / "brands"
        (brands_dir / "acme").mkdir(parents=True)
        # Brand override only changes model — temperature should inherit from global.
        (brands_dir / "acme" / "models.yaml").write_text(
            "classify:\n  model: b/brand\n"
        )
        cfg = load_models_config(
            brand_slug="acme", config_dir=config_dir, brands_dir=brands_dir
        )
        assert cfg.stages["classify"].model == "b/brand"
        assert cfg.stages["classify"].temperature == 0.2

    def test_brand_override_replaces_fallback_list(self, tmp_path):
        # Per design #16: list fields replace whole, never concat.
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "models.yaml").write_text(
            "defaults:\n"
            "  classify:\n"
            "    model: m/m\n"
            "    fallbacks: [g/1, g/2, g/3]\n"
        )
        brands_dir = tmp_path / "brands"
        (brands_dir / "acme").mkdir(parents=True)
        (brands_dir / "acme" / "models.yaml").write_text(
            "classify:\n  fallbacks: [b/only]\n"
        )
        cfg = load_models_config(
            brand_slug="acme", config_dir=config_dir, brands_dir=brands_dir
        )
        assert cfg.stages["classify"].fallbacks == ["b/only"]

    def test_profile_applies_after_brand_override(self, tmp_path):
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "models.yaml").write_text(
            "defaults:\n  classify:\n    model: g/global\n    temperature: 0.2\n"
            "profiles:\n  demo:\n    classify:\n      model: p/profile\n"
            "      fallbacks: [p/fallback]\n"
        )
        brands_dir = tmp_path / "brands"
        (brands_dir / "acme").mkdir(parents=True)
        (brands_dir / "acme" / "models.yaml").write_text(
            "classify:\n  model: b/brand\n  fallbacks: [b/fallback]\n"
        )

        cfg = load_models_config(
            brand_slug="acme",
            profile="demo",
            config_dir=config_dir,
            brands_dir=brands_dir,
        )

        assert cfg.stages["classify"].model == "p/profile"
        assert cfg.stages["classify"].fallbacks == ["p/fallback"]
        assert cfg.stages["classify"].temperature == 0.2

    def test_unknown_profile_raises_config_error(self, tmp_path):
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "models.yaml").write_text("profiles:\n  demo: {}\n")

        with pytest.raises(LLMGatewayConfigError, match="Unknown model profile"):
            load_models_config(profile="missing", config_dir=config_dir)

    def test_get_stage_config_unknown_raises_config_error(self, tmp_path):
        cfg = load_models_config(
            config_dir=tmp_path / "missing", brands_dir=tmp_path / "missing"
        )
        with pytest.raises(LLMGatewayConfigError, match="Unknown stage"):
            cfg.get_stage_config("nonexistent_stage")

    def test_malformed_yaml_raises_config_error(self, tmp_path):
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "models.yaml").write_text("defaults:\n  filter: [\n  unbal:")
        with pytest.raises(LLMGatewayConfigError, match="Malformed YAML"):
            load_models_config(
                config_dir=config_dir, brands_dir=tmp_path / "no-brands"
            )

    def test_invalid_stage_field_types_raise_config_error(self, tmp_path):
        # Pydantic catches type errors at load time, not mid-call.
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "models.yaml").write_text(
            "defaults:\n  filter:\n    temperature: not-a-float\n"
        )
        with pytest.raises(LLMGatewayConfigError, match="Invalid stage configuration"):
            load_models_config(
                config_dir=config_dir, brands_dir=tmp_path / "no-brands"
            )

    def test_repo_config_loads_clean(self):
        # Locks the actual config/models.yaml into the test surface (subtask 1.6).
        cfg = load_models_config()
        for stage in ("filter", "classify", "routing_tiebreaker", "route", "memory_query"):
            sc = cfg.stages[stage]
            assert sc.model
            assert sc.timeout_s > 0
            assert sc.max_tokens > 0

    @pytest.mark.parametrize("brand_slug", ["notion", "liquiddeath"])
    def test_demo_population_profile_has_approved_models(self, brand_slug):
        cfg = load_models_config(
            brand_slug=brand_slug,
            profile=DEMO_POPULATION_MODEL_PROFILE,
        )

        expected = {
            "filter": (
                "google/gemini-3.1-flash-lite",
                ["openai/gpt-5.4-nano", "anthropic/claude-haiku-4-5"],
            ),
            "classify": (
                "openai/gpt-5-mini",
                ["anthropic/claude-sonnet-5", "google/gemini-3.1-flash-lite"],
            ),
            "routing_tiebreaker": (
                "google/gemini-3.1-flash-lite",
                ["openai/gpt-5.4-nano"],
            ),
            "route": (
                "google/gemini-3.1-flash-lite",
                ["openai/gpt-5.4-nano"],
            ),
            "memory_query": (
                "google/gemini-3.1-flash-lite",
                ["openai/gpt-5.4-nano"],
            ),
        }
        assert {
            stage: (cfg.stages[stage].model, cfg.stages[stage].fallbacks)
            for stage in expected
        } == expected

    def test_demo_profile_is_opt_in_and_bypasses_notion_qwen(self):
        normal = load_models_config(brand_slug="notion")
        demo = load_models_config(
            brand_slug="notion",
            profile=DEMO_POPULATION_MODEL_PROFILE,
        )

        assert normal.stages["classify"].model == "qwen/qwen3-235b-a22b-2507"
        assert demo.stages["classify"].model == "openai/gpt-5-mini"
        assert all(
            "qwen" not in model and "opus" not in model
            for stage in demo.stages.values()
            for model in [stage.model, *stage.fallbacks]
        )

    def test_demo_profile_stage_configs_are_identical_for_both_brands(self):
        notion = load_models_config(
            brand_slug="notion", profile=DEMO_POPULATION_MODEL_PROFILE
        )
        liquiddeath = load_models_config(
            brand_slug="liquiddeath", profile=DEMO_POPULATION_MODEL_PROFILE
        )

        assert notion == liquiddeath

    def test_reliable_demo_profile_promotes_sonnet_and_preserves_fast_stages(self):
        assert DEMO_POPULATION_MODEL_PROFILES == {
            DEMO_POPULATION_MODEL_PROFILE,
            DEMO_POPULATION_RELIABLE_MODEL_PROFILE,
        }
        default = load_models_config(
            brand_slug="notion", profile=DEMO_POPULATION_MODEL_PROFILE
        )
        reliable_notion = load_models_config(
            brand_slug="notion", profile=DEMO_POPULATION_RELIABLE_MODEL_PROFILE
        )
        reliable_liquiddeath = load_models_config(
            brand_slug="liquiddeath", profile=DEMO_POPULATION_RELIABLE_MODEL_PROFILE
        )

        assert reliable_notion == reliable_liquiddeath
        assert reliable_notion.stages["classify"].model == "anthropic/claude-sonnet-5"
        assert reliable_notion.stages["classify"].fallbacks == [
            "openai/gpt-5-mini",
            "google/gemini-3.1-flash-lite",
        ]
        for stage in ("filter", "routing_tiebreaker", "route", "memory_query"):
            assert reliable_notion.stages[stage] == default.stages[stage]


# =============================================================================
# 3. openrouter.py — retry / fallback / JSON mode / cost / timeout (1.3, 1.4)
# =============================================================================


class TestOpenRouterGateway:
    # ---- happy path -----------------------------------------------------

    def test_happy_path_returns_llmresponse(self):
        client = FakeClient([_ok_response('{"foo": 1}', cost=0.0042)])
        gw = OpenRouterGateway(
            config=_models_config(_stage_cfg(model="primary/m")),
            client=client,
        )
        out = gw.complete("classify", "hi")
        assert isinstance(out, LLMResponse)
        assert out.content == '{"foo": 1}'
        assert out.model_used == "primary/m"
        assert out.tokens_in == 10
        assert out.tokens_out == 20
        assert out.cost_usd == 0.0042
        assert out.latency_ms >= 0

    def test_classification_validation_uses_sonnet_reliability_fallback(self):
        cfg = load_models_config(
            brand_slug="notion",
            profile=DEMO_POPULATION_MODEL_PROFILE,
        )
        valid = (
            '{"is_about_brand": true, "area": "product", '
            '"sentiment": "negative", "severity": "medium", '
            '"action_class": "sprint", "summary": "AI pricing concern", '
            '"confidence": 0.9}'
        )
        client = FakeClient([
            _ok_response("not JSON", cost=0.10),
            _ok_response(valid, cost=0.20),
        ])
        gw = OpenRouterGateway(config=cfg, client=client)

        out = gw.complete_validated(
            "classify",
            "classify this",
            response_schema={},
            validator=parse_classification_response_strict,
        )

        assert [call["model"] for call in client.calls] == [
            "openai/gpt-5-mini",
            "anthropic/claude-sonnet-5",
        ]
        assert out.model_used == "anthropic/claude-sonnet-5"
        assert out.was_fallback is True
        assert out.attempt_count == 2
        assert out.cost_usd == pytest.approx(0.30)
        assert out.tokens_in == 20
        assert out.tokens_out == 40

    def test_all_schema_invalid_classifiers_exhaust_in_profile_order(self):
        cfg = load_models_config(
            brand_slug="liquiddeath",
            profile=DEMO_POPULATION_MODEL_PROFILE,
        )
        client = FakeClient(
            [
                _ok_response("not JSON", cost=0.10),
                _ok_response("{}", cost=0.20),
                _ok_response("{bad JSON}", cost=0.30),
            ]
        )
        gw = OpenRouterGateway(config=cfg, client=client)

        with pytest.raises(LLMGatewayExhaustedError) as exc_info:
            gw.complete_validated(
                "classify",
                "classify this",
                response_schema={},
                validator=parse_classification_response_strict,
            )

        assert [call["model"] for call in client.calls] == [
            "openai/gpt-5-mini",
            "anthropic/claude-sonnet-5",
            "google/gemini-3.1-flash-lite",
        ]
        assert exc_info.value.attempts == 3
        assert exc_info.value.cost_usd == pytest.approx(0.60)
        assert exc_info.value.tokens_in == 30
        assert exc_info.value.tokens_out == 60

    # ---- retry / backoff ------------------------------------------------

    def test_429_triggers_backoff_retry_then_succeeds(self, monkeypatch):
        sleeps: list[float] = []
        monkeypatch.setattr(time, "sleep", lambda s: sleeps.append(s))
        client = FakeClient([_rate_limit(), _ok_response()])
        gw = OpenRouterGateway(
            config=_models_config(_stage_cfg()), client=client
        )
        gw.complete("classify", "hi")
        assert len(client.calls) == 2
        assert sleeps == [2.0]  # exp backoff: 2^1 between attempt 1 and 2

    def test_5xx_retries_up_to_three_then_fallbacks(self, monkeypatch):
        sleeps: list[float] = []
        monkeypatch.setattr(time, "sleep", lambda s: sleeps.append(s))
        # 3 attempts on primary all 500, then fallback succeeds.
        client = FakeClient([
            _status_error(500), _status_error(500), _status_error(500),
            _ok_response(),
        ])
        gw = OpenRouterGateway(
            config=_models_config(_stage_cfg(fallbacks=["fb/1"])),
            client=client,
        )
        out = gw.complete("classify", "hi")
        assert out.model_used == "fb/1"
        assert len(client.calls) == 4  # 3 on primary + 1 on fallback
        assert sleeps == [2.0, 4.0]    # backoffs only between the 3 primary attempts

    def test_timeout_and_connection_errors_retry(self):
        client = FakeClient([_timeout(), _conn_error(), _ok_response()])
        gw = OpenRouterGateway(
            config=_models_config(_stage_cfg()), client=client
        )
        out = gw.complete("classify", "hi")
        assert out.content
        assert len(client.calls) == 3

    # ---- fallback chain -------------------------------------------------

    def test_404_skips_to_next_model(self):
        client = FakeClient([_status_error(404, "model not found"), _ok_response()])
        gw = OpenRouterGateway(
            config=_models_config(_stage_cfg(fallbacks=["fb/1"])),
            client=client,
        )
        out = gw.complete("classify", "hi")
        assert out.model_used == "fb/1"
        assert len(client.calls) == 2  # no retries on 404 — straight to fallback

    def test_no_provider_marker_falls_through(self):
        client = FakeClient([
            _status_error(503, "no available provider for model"),
            _ok_response(),
        ])
        gw = OpenRouterGateway(
            config=_models_config(_stage_cfg(fallbacks=["fb/1"])),
            client=client,
        )
        out = gw.complete("classify", "hi")
        assert out.model_used == "fb/1"

    def test_each_fallback_gets_fresh_retry_budget(self, monkeypatch):
        monkeypatch.setattr(time, "sleep", lambda _s: None)
        # Primary: 3x 500 (full budget burned). Fallback: 2x 500 + ok.
        client = FakeClient([
            _status_error(500), _status_error(500), _status_error(500),
            _status_error(500), _status_error(500), _ok_response(),
        ])
        gw = OpenRouterGateway(
            config=_models_config(_stage_cfg(fallbacks=["fb/1"])),
            client=client,
        )
        out = gw.complete("classify", "hi")
        assert out.model_used == "fb/1"
        assert len(client.calls) == 6

    def test_all_models_exhausted_raises(self):
        client = FakeClient([
            _status_error(500), _status_error(500), _status_error(500),
            _status_error(500), _status_error(500), _status_error(500),
        ])
        gw = OpenRouterGateway(
            config=_models_config(_stage_cfg(fallbacks=["fb/1"])),
            client=client,
        )
        with pytest.raises(LLMGatewayExhaustedError) as ei:
            gw.complete("classify", "hi")
        assert ei.value.attempts == 6

    # ---- fatal errors ---------------------------------------------------

    def test_401_is_fatal_and_does_not_fallback(self):
        client = FakeClient([_status_error(401, "bad key")])
        gw = OpenRouterGateway(
            config=_models_config(_stage_cfg(fallbacks=["fb/1"])),
            client=client,
        )
        with pytest.raises(LLMGatewayAuthError):
            gw.complete("classify", "hi")
        assert len(client.calls) == 1  # no retry, no fallback

    def test_400_non_json_mode_is_fatal(self):
        # Plain bad-request (no response_format hint) → fatal config error.
        client = FakeClient([_status_error(400, "missing required field")])
        gw = OpenRouterGateway(
            config=_models_config(_stage_cfg()), client=client
        )
        with pytest.raises(LLMGatewayConfigError):
            gw.complete("classify", "hi")

    def test_unknown_stage_is_fatal(self):
        client = FakeClient([])  # never called
        gw = OpenRouterGateway(
            config=_models_config(_stage_cfg(), stage="classify"),
            client=client,
        )
        with pytest.raises(LLMGatewayConfigError, match="Unknown stage"):
            gw.complete("nonexistent_stage", "hi")
        assert client.calls == []

    def test_missing_api_key_raises_config_error(self, monkeypatch):
        # Without a client OR an api_key, construction must raise.
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        with pytest.raises(LLMGatewayConfigError, match="OPENROUTER_API_KEY"):
            OpenRouterGateway(config=_models_config(_stage_cfg()))

    # ---- timeout cap ----------------------------------------------------

    def test_stage_wallclock_cap_raises_timeout(self, monkeypatch):
        # Real backoff would be 2s. Tight 1s stage cap → should bail before retry.
        # We need real sleep here so the deadline actually progresses.
        monkeypatch.setattr(time, "sleep", lambda s: None)
        # Force perf_counter to advance past the deadline between attempts.
        ticks = iter([0.0, 0.5, 2.0, 2.0, 2.0])  # last two for safety
        monkeypatch.setattr(time, "perf_counter", lambda: next(ticks))

        client = FakeClient([_status_error(500)])  # would normally retry
        gw = OpenRouterGateway(
            config=_models_config(_stage_cfg(timeout_s=1.0)), client=client
        )
        with pytest.raises(LLMGatewayTimeoutError):
            gw.complete("classify", "hi")

    # ---- JSON mode ------------------------------------------------------

    def test_json_mode_requested_when_schema_provided(self):
        client = FakeClient([_ok_response('{"x": 1}')])
        gw = OpenRouterGateway(
            config=_models_config(_stage_cfg()), client=client
        )
        gw.complete("classify", "hi", response_schema={"type": "object"})
        kwargs = client.calls[0]
        assert kwargs["response_format"] == {"type": "json_object"}
        # Cost-tracking flag always set, per design #7.
        assert kwargs["extra_body"] == {"usage": {"include": True}}

    def test_json_mode_omitted_when_no_schema(self):
        client = FakeClient([_ok_response("plain text")])
        gw = OpenRouterGateway(
            config=_models_config(_stage_cfg()), client=client
        )
        gw.complete("classify", "hi")
        assert "response_format" not in client.calls[0]

    def test_json_mode_unsupported_caches_and_retries_with_suffix(
        self, monkeypatch, caplog
    ):
        caplog.set_level(logging.WARNING, logger="resound.gateway.openrouter")
        # First call: 400 with response_format hint (model rejects JSON mode).
        # Second call: model returns valid JSON inside prose.
        client = FakeClient([
            _status_error(
                400,
                "Invalid argument: response_format json_object not supported",
            ),
            _ok_response("Sure: {\"foo\": 1} thanks"),
        ])
        gw = OpenRouterGateway(
            config=_models_config(_stage_cfg(model="primary/m")),
            client=client,
        )
        out = gw.complete("classify", "hi", response_schema={})
        # Cache should now mark the model as JSON-mode-incompatible.
        assert "primary/m" in gw._no_json_mode_models
        # First attempt had response_format; retry must NOT have it but should
        # carry the prompt suffix.
        assert "response_format" in client.calls[0]
        assert "response_format" not in client.calls[1]
        suffix = "Respond with JSON only, no additional prose."
        assert suffix in client.calls[1]["messages"][0]["content"]
        # Regex extraction strips the prose.
        assert out.content == '{"foo": 1}'
        # Warning was logged.
        assert any("does not support" in r.message for r in caplog.records)

    def test_cached_model_skips_native_json_mode(self):
        client = FakeClient([_ok_response('{"a": 2}')])
        gw = OpenRouterGateway(
            config=_models_config(_stage_cfg(model="primary/m")),
            client=client,
        )
        # Pretend we already learned this model lacks JSON mode.
        gw._no_json_mode_models.add("primary/m")
        gw.complete("classify", "hi", response_schema={})
        assert "response_format" not in client.calls[0]
        suffix = "Respond with JSON only, no additional prose."
        assert suffix in client.calls[0]["messages"][0]["content"]

    # ---- regex extraction ----------------------------------------------

    def test_regex_extracts_json_from_prose(self):
        # Defensive extraction runs even on JSON-mode success (design #6).
        client = FakeClient([_ok_response('Here you go: {"k": "v"} cheers')])
        gw = OpenRouterGateway(
            config=_models_config(_stage_cfg()), client=client
        )
        out = gw.complete("classify", "hi", response_schema={})
        assert out.content == '{"k": "v"}'

    def test_regex_failure_raises_parse_error(self):
        client = FakeClient([_ok_response("no json object here, sorry")])
        gw = OpenRouterGateway(
            config=_models_config(_stage_cfg()), client=client
        )
        with pytest.raises(LLMGatewayParseError) as ei:
            gw.complete("classify", "hi", response_schema={})
        assert ei.value.raw_text == "no json object here, sorry"

    # ---- cost handling --------------------------------------------------

    def test_cost_is_none_when_usage_cost_missing(self, caplog):
        caplog.set_level(logging.WARNING, logger="resound.gateway.openrouter")
        client = FakeClient([_ok_response('{"x": 1}', cost=None)])
        gw = OpenRouterGateway(
            config=_models_config(_stage_cfg()), client=client
        )
        out = gw.complete("classify", "hi")
        assert out.cost_usd is None
        # Per design #7: warn loudly so audit gaps are noticed.
        assert any("no usage.cost" in r.message for r in caplog.records)


# =============================================================================
# 4. __init__.py — public exports + build_gateway (subtask 1.5)
# =============================================================================


class TestExports:
    EXPECTED = {
        "LLMGateway", "LLMResponse", "OpenRouterGateway",
        "load_models_config", "StageConfig", "ModelsConfig",
        "DEMO_POPULATION_MODEL_PROFILE",
        "DEMO_POPULATION_RELIABLE_MODEL_PROFILE",
        "DEMO_POPULATION_MODEL_PROFILES",
        "build_gateway",
        "JSON_MODE",
        "LLMGatewayError", "LLMGatewayConfigError", "LLMGatewayAuthError",
        "LLMGatewayExhaustedError", "LLMGatewayTimeoutError",
        "LLMGatewayParseError",
    }

    def test_all_matches_expected(self):
        assert set(gateway_pkg.__all__) == self.EXPECTED

    def test_every_export_is_resolvable(self):
        for name in gateway_pkg.__all__:
            assert hasattr(gateway_pkg, name), f"{name} missing from gateway"

    def test_build_gateway_returns_concrete_openrouter(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        gw = build_gateway("demo")
        assert isinstance(gw, OpenRouterGateway)
        # Fresh per-instance cache.
        assert gw._no_json_mode_models == set()
        # Config was populated from config/models.yaml.
        assert "classify" in gw.config.stages

    def test_build_gateway_accepts_demo_population_profile(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")

        gw = build_gateway("notion", profile=DEMO_POPULATION_MODEL_PROFILE)

        assert gw.config.stages["classify"].model == "openai/gpt-5-mini"
        assert gw.config.stages["classify"].fallbacks == [
            "anthropic/claude-sonnet-5",
            "google/gemini-3.1-flash-lite",
        ]

    def test_module_has_docstring(self):
        assert gateway_pkg.__doc__ and "Gateway" in gateway_pkg.__doc__
