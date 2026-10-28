"""Route chat requests across OpenAI-compatible providers (Gemini, Groq).

Free tiers fail in predictable ways, and each is handled differently:

  429 rate limited    rest for Retry-After (or a growing backoff); use another
  401 / 403 / 404     bad key or unknown model: disable for this run
  5xx, timeouts       short rest; use another

Healthy providers are used in turn, which spreads the free quota and varies the
writing style of the corpus. When everyone is resting, the router waits if the
wait is short and otherwise raises with the time to resume -- the generator
saves progress, so a run interrupted by a daily quota simply continues later.

Only used to build BERT's training data. Nothing at demo time calls an API.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass

import httpx

GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/openai/"
GROQ_BASE = "https://api.groq.com/openai/v1/"

PROVIDER_DEFAULTS = {
    "gemini": dict(base_url=GEMINI_BASE, key_env="GEMINI_API_KEY", model_env="GEMINI_MODEL",
                   interval_env="GEMINI_MIN_INTERVAL", min_interval=5.0,
                   prefer=("flash-lite", "flash"),
                   avoid=("embedding", "image", "tts", "audio", "live", "aqa", "vision")),
    "groq": dict(base_url=GROQ_BASE, key_env="GROQ_API_KEY", model_env="GROQ_MODEL",
                 interval_env="GROQ_MIN_INTERVAL", min_interval=3.0,
                 prefer=("gpt-oss-120b", "llama-3.3-70b", "70b", "gpt-oss"),
                 avoid=("whisper", "guard", "tts", "embed", "vision", "compound")),
}

TEMPERATURE = 0.9            # varied prose; the checker guards the facts
REQUEST_TIMEOUT = 120.0
RATE_LIMIT_BACKOFF = 30.0    # first rest after a 429 with no Retry-After; doubles
MAX_BACKOFF = 3600.0
ERROR_COOLDOWN = 15.0


@dataclass(frozen=True)
class Provider:
    name: str
    base_url: str
    api_key: str
    model: str
    min_interval: float = 0.0     # seconds between requests: the free-tier RPM limit


@dataclass(frozen=True)
class Completion:
    text: str
    provider: str
    model: str


class AllProvidersUnavailable(RuntimeError):
    def __init__(self, resume_at: float | None, detail: str):
        super().__init__(detail)
        self.resume_at = resume_at    # clock time a provider frees up; None if all disabled


@dataclass
class _State:
    cooldown_until: float = 0.0
    last_call: float = float("-inf")
    strikes: int = 0
    disabled: str | None = None


def _retry_after(response: httpx.Response) -> float | None:
    try:
        return float(response.headers["retry-after"])
    except (KeyError, ValueError):
        return None


class Router:
    def __init__(self, providers: list[Provider], client: httpx.Client | None = None,
                 clock=time.monotonic, sleep=time.sleep, max_wait: float = 120.0,
                 temperature: float = TEMPERATURE):
        if not providers:
            raise ValueError("no providers configured: set GEMINI_API_KEY and/or GROQ_API_KEY")
        self.providers = list(providers)
        self.client = client or httpx.Client(timeout=REQUEST_TIMEOUT)
        self._clock, self._sleep, self.max_wait = clock, sleep, max_wait
        self.temperature = temperature
        self._state = {p.name: _State() for p in self.providers}
        self._next = 0

    def complete(self, system: str, user: str) -> Completion:
        while True:
            n = len(self.providers)
            for k in range(n):
                i = (self._next + k) % n
                provider, state = self.providers[i], self._state[self.providers[i].name]
                now = self._clock()
                if state.disabled or now < state.cooldown_until or now < state.last_call + provider.min_interval:
                    continue
                result = self._call(provider, state, system, user, now)
                if result is not None:
                    self._next = (i + 1) % n
                    return result

            live = [(p, self._state[p.name]) for p in self.providers if not self._state[p.name].disabled]
            if not live:
                detail = "; ".join(f"{p.name}: {self._state[p.name].disabled}" for p in self.providers)
                raise AllProvidersUnavailable(None, f"every provider is disabled ({detail})")
            ready_at = min(max(s.cooldown_until, s.last_call + p.min_interval) for p, s in live)
            wait = ready_at - self._clock()
            if wait > self.max_wait:
                raise AllProvidersUnavailable(ready_at, f"all providers resting; next free in {wait / 60:.0f} min")
            self._sleep(max(wait, 0.0))

    def _call(self, p: Provider, state: _State, system: str, user: str, now: float) -> Completion | None:
        state.last_call = now
        try:
            response = self.client.post(
                p.base_url + "chat/completions",
                headers={"Authorization": f"Bearer {p.api_key}"},
                json={"model": p.model, "temperature": self.temperature,
                      "messages": [{"role": "system", "content": system},
                                   {"role": "user", "content": user}]},
            )
        except httpx.TransportError:
            state.cooldown_until = now + ERROR_COOLDOWN
            return None

        if response.status_code == 200:
            try:
                text = response.json()["choices"][0]["message"]["content"]
            except (ValueError, KeyError, IndexError, TypeError):
                state.cooldown_until = now + ERROR_COOLDOWN
                return None
            state.strikes = 0
            return Completion(text or "", p.name, p.model)
        if response.status_code == 429:
            state.strikes += 1
            backoff = min(RATE_LIMIT_BACKOFF * 2 ** (state.strikes - 1), MAX_BACKOFF)
            state.cooldown_until = now + (_retry_after(response) or backoff)
            return None
        if response.status_code in (401, 403, 404):
            state.disabled = f"HTTP {response.status_code} (bad key or unknown model)"
            return None
        state.cooldown_until = now + ERROR_COOLDOWN
        return None


def parse_batch(text: str) -> dict[int, str]:
    """{project_id: proposal} from a JSON array, tolerating prose or a code
    fence around it. Anything malformed is dropped, never raised."""
    if not text:
        return {}
    start, end = text.find("["), text.rfind("]")
    if start < 0 or end <= start:
        return {}
    try:
        items = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return {}
    out: dict[int, str] = {}
    for item in items if isinstance(items, list) else []:
        if isinstance(item, dict) and isinstance(item.get("proposal"), str):
            try:
                out[int(item["id"])] = item["proposal"]
            except (KeyError, TypeError, ValueError):
                continue
    return out


def discover_model(client: httpx.Client, base_url: str, api_key: str,
                   prefer: tuple[str, ...], avoid: tuple[str, ...]) -> str:
    """Pick a chat model from the provider's own list, so a renamed model does
    not break the run. Numbered stable releases beat previews and moving
    "-latest" aliases (which the provider can repoint); newer versions win."""
    response = client.get(base_url + "models", headers={"Authorization": f"Bearer {api_key}"})
    response.raise_for_status()
    ids = [m["id"].removeprefix("models/") for m in response.json().get("data", [])]
    ids = [i for i in ids if not any(a in i for a in avoid)]
    for wanted in prefer:
        matches = [i for i in ids if wanted in i]
        stable = [i for i in matches if not any(tag in i for tag in ("preview", "exp", "latest"))]
        if stable or matches:
            return max(stable or matches)
    raise RuntimeError(f"no model matching {prefer} at {base_url}; set the model in .env")


def providers_from_env(env: dict[str, str], client: httpx.Client, warn=print) -> list[Provider]:
    """A provider for every key that is set. Models come from .env when given,
    otherwise from the provider's model list. A provider that cannot be set
    up -- a wrong key, an unreachable model list -- is skipped with a warning
    so the others still run."""
    providers = []
    for name, d in PROVIDER_DEFAULTS.items():
        key = (env.get(d["key_env"]) or "").strip()
        if not key:
            continue
        model = (env.get(d["model_env"]) or "").strip()
        if not model:
            try:
                model = discover_model(client, d["base_url"], key, d["prefer"], d["avoid"])
            except (httpx.HTTPError, RuntimeError, ValueError, KeyError) as err:
                warn(f"skipping {name}: could not choose a model ({err}). "
                     f"Check {d['key_env']}, or set {d['model_env']} in .env.")
                continue
        interval = float(env.get(d["interval_env"]) or d["min_interval"])
        providers.append(Provider(name, d["base_url"], key, model, interval))
    return providers
