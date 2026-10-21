"""Router across OpenAI-compatible providers (Gemini, Groq), tested against a
fake HTTP transport and a fake clock: real request code, no network, no quota."""

import json

import httpx
import pytest

from textgen.router import (AllProvidersUnavailable, Provider, Router, discover_model,
                            parse_batch, providers_from_env)


class FakeClock:
    def __init__(self):
        self.now = 1000.0
        self.slept = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds


def _ok(text):
    return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": text}}]})


def _router(script, providers=("gemini", "groq"), min_interval=0.0, clock=None):
    """script: provider name -> list of responses, consumed in order (last repeats)."""
    calls = []

    def handler(request):
        name = "gemini" if "googleapis" in request.url.host else "groq"
        calls.append((name, request))
        queue = script[name]
        return queue.pop(0) if len(queue) > 1 else queue[0]

    hosts = {"gemini": "https://generativelanguage.googleapis.com/v1beta/openai/",
             "groq": "https://api.groq.com/openai/v1/"}
    ps = [Provider(n, hosts[n], f"key-{n}", f"model-{n}", min_interval) for n in providers]
    clock = clock or FakeClock()
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return Router(ps, client=client, clock=clock, sleep=clock.sleep, max_wait=120.0), calls, clock


def test_sends_an_openai_style_request_with_the_providers_key_and_model():
    router, calls, _ = _router({"gemini": [_ok("hi")], "groq": [_ok("hi")]}, providers=("gemini",))
    router.complete("system text", "user text")
    _, request = calls[0]
    assert request.url.path == "/v1beta/openai/chat/completions"
    assert request.headers["authorization"] == "Bearer key-gemini"
    body = json.loads(request.content)
    assert body["model"] == "model-gemini"
    assert body["messages"] == [{"role": "system", "content": "system text"},
                                {"role": "user", "content": "user text"}]


def test_falls_back_to_the_next_provider_when_one_is_rate_limited():
    router, _, _ = _router({"gemini": [httpx.Response(429)], "groq": [_ok("from groq")]})
    result = router.complete("s", "u")
    assert (result.text, result.provider, result.model) == ("from groq", "groq", "model-groq")


def test_a_rate_limited_provider_rests_for_its_retry_after():
    router, calls, clock = _router({
        "gemini": [httpx.Response(429, headers={"Retry-After": "60"}), _ok("gemini back")],
        "groq": [_ok("groq")],
    })
    router.complete("s", "u")
    router.complete("s", "u")
    assert [n for n, _ in calls].count("gemini") == 1      # still resting
    clock.now += 61
    router.complete("s", "u")
    assert [n for n, _ in calls].count("gemini") == 2


def test_spreads_requests_across_healthy_providers():
    # Alternating spreads free-tier quota and varies the writing style.
    router, _, _ = _router({"gemini": [_ok("a")], "groq": [_ok("b")]})
    served = [router.complete("s", "u").provider for _ in range(4)]
    assert served == ["gemini", "groq", "gemini", "groq"]


def test_a_rejected_key_disables_that_provider_for_good():
    router, calls, clock = _router({"gemini": [httpx.Response(401)], "groq": [_ok("b")]})
    router.complete("s", "u")
    clock.now += 100_000
    for _ in range(3):
        assert router.complete("s", "u").provider == "groq"
    assert [n for n, _ in calls].count("gemini") == 1


def test_server_errors_and_timeouts_fall_through_to_the_next_provider():
    router, _, _ = _router({"gemini": [httpx.Response(503)], "groq": [_ok("b")]})
    assert router.complete("s", "u").provider == "groq"


def test_waits_briefly_when_every_provider_is_resting():
    router, _, clock = _router({
        "gemini": [httpx.Response(429, headers={"Retry-After": "30"}), _ok("a")],
        "groq": [httpx.Response(429, headers={"Retry-After": "30"}), _ok("b")],
    })
    result = router.complete("s", "u")
    assert result.text in ("a", "b")
    assert clock.slept and max(clock.slept) <= 30.0


def test_gives_up_with_a_resume_time_when_daily_quota_is_gone():
    router, _, clock = _router({
        "gemini": [httpx.Response(429, headers={"Retry-After": "7200"})],
        "groq": [httpx.Response(429, headers={"Retry-After": "7200"})],
    })
    with pytest.raises(AllProvidersUnavailable) as err:
        router.complete("s", "u")
    assert err.value.resume_at == pytest.approx(clock.now + 7200)
    assert all(s <= 120.0 for s in clock.slept)


def test_respects_each_providers_minimum_interval():
    router, _, clock = _router({"gemini": [_ok("a")], "groq": [_ok("b")]}, providers=("gemini",),
                               min_interval=4.0)
    router.complete("s", "u")
    router.complete("s", "u")
    assert clock.slept == [pytest.approx(4.0)]


def test_parses_a_json_array_even_inside_a_code_fence():
    text = 'Here you go:\n```json\n[{"id": "17", "proposal": "Text A"}, {"id": 18, "proposal": "Text B"}]\n```'
    assert parse_batch(text) == {17: "Text A", 18: "Text B"}


def test_unparseable_output_yields_nothing_rather_than_crashing():
    assert parse_batch("Sorry, I cannot help with that.") == {}
    assert parse_batch('[{"id": 1}]') == {}


def test_discovers_a_preferred_chat_model_from_the_models_list():
    def handler(request):
        assert request.url.path.endswith("/models")
        return httpx.Response(200, json={"data": [
            {"id": "models/embedding-001"}, {"id": "models/gemini-3.8-flash"},
            {"id": "models/gemini-3.8-flash-lite"}, {"id": "models/gemini-3.8-flash-image"},
        ]})
    client = httpx.Client(transport=httpx.MockTransport(handler))
    model = discover_model(client, "https://generativelanguage.googleapis.com/v1beta/openai/", "k",
                           prefer=("flash-lite", "flash"), avoid=("embedding", "image"))
    assert model == "gemini-3.8-flash-lite"


def test_builds_providers_only_for_keys_that_are_set():
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    env = {"GROQ_API_KEY": "g", "GROQ_MODEL": "chosen-model", "GEMINI_API_KEY": ""}
    providers = providers_from_env(env, client)
    assert [(p.name, p.model) for p in providers] == [("groq", "chosen-model")]


def test_one_providers_bad_key_does_not_stop_the_others():
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(401)))
    env = {"GEMINI_API_KEY": "wrong", "GROQ_API_KEY": "g", "GROQ_MODEL": "chosen-model"}
    warnings = []
    providers = providers_from_env(env, client, warn=warnings.append)
    assert [p.name for p in providers] == ["groq"]
    assert len(warnings) == 1 and "gemini" in warnings[0]


def test_prefers_a_pinned_version_over_a_moving_latest_alias():
    # "-latest" can be repointed by the provider at any time; a numbered
    # version keeps the corpus reproducible.
    def handler(request):
        return httpx.Response(200, json={"data": [
            {"id": "models/gemini-flash-lite-latest"}, {"id": "models/gemini-3.8-flash-lite"},
            {"id": "models/gemini-3.6-flash-lite"},
        ]})
    client = httpx.Client(transport=httpx.MockTransport(handler))
    model = discover_model(client, "https://generativelanguage.googleapis.com/v1beta/openai/", "k",
                           prefer=("flash-lite",), avoid=())
    assert model == "gemini-3.8-flash-lite"
