"""
Model router + key health engine for JARVIS one-shot calls (actions/*.py).

NOT for the Live audio session: this module never imports main.py, never opens a
Live session, never touches its quota pool. One-shot text in, text out.

    call(prompt, task="fast", system="", model=None) -> str      ("" if all failed)
    as_json(prompt, task="fast", system="")          -> dict     ({} if all failed)
    status()                                         -> dict     (key health, for UI/debug)

Neither raises. Every failure is logged (keys shown as abcd...wxyz only).

config/api_keys.json (all optional; missing provider = its steps are skipped):
    "gemini_api_key":     "AQ...",              # single key, tried first
    "gemini_api_keys":    ["AQ...", "AQ..."],   # spares
    "openrouter_api_key": "sk-or-...",          # str or list
    "groq_api_key":       "gsk_...",            # str or list
    "routing_rules": {                          # per task, tried left to right
        "coding": [{"provider": "openrouter", "model": "deepseek/deepseek-r1:free"},
                   "gemini:gemini-2.5-flash"]   # "provider:model" shorthand also ok
    }
The file is re-read when it changes, so a pasted key works without a restart.
Model names drift; check them against each provider's model list.
"""
from __future__ import annotations

import json
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

if getattr(sys, "frozen", False):
    _BASE = Path(sys.executable).parent
else:
    _BASE = Path(__file__).resolve().parent.parent
_KEY_FILE = _BASE / "config" / "api_keys.json"

DEFAULT_RULES: dict[str, list[tuple[str, str]]] = {
    "coding":  [("openrouter", "deepseek/deepseek-r1:free"),
                ("gemini", "gemini-2.5-flash")],
    "writing": [("groq", "llama-3.3-70b-versatile"),
                ("openrouter", "meta-llama/llama-3.3-70b-instruct:free"),
                ("gemini", "gemini-2.5-flash")],
    "fast":    [("gemini", "gemini-2.5-flash-lite"),
                ("groq", "llama-3.1-8b-instant"),
                ("openrouter", "meta-llama/llama-3.3-70b-instruct:free")],
}

_ENDPOINTS = {"openrouter": "https://openrouter.ai/api/v1",
              "groq": "https://api.groq.com/openai/v1"}

_TIMEOUT = 30.0              # seconds per attempt (Gemini's floor is 10; R1 is slow)
_BASE_COOLDOWN = 60.0        # 429 -> 60s, 120s, 240s ... capped below
_MAX_COOLDOWN = 3600.0
_AUTH_COOLDOWN = 600.0       # rejected key: set aside, retried after a typo fix
_TRANSIENT_COOLDOWN = 30.0   # 5xx / timeout: brief rest
_GONE_COOLDOWN = 1800.0      # model missing: rested for ALL keys


# --------------------------------------------------------------------------- keys

@dataclass
class KeyRecord:
    key: str
    fails: int = 0
    cooldown_until: float = 0.0
    last_used: float = 0.0       # timestamp, for status
    seq: int = 0                 # use order; clock ticks can tie (coarse on Windows), this cannot

    @property
    def label(self) -> str:
        k = self.key
        return k if len(k) <= 12 else f"{k[:4]}...{k[-4:]}"


class _Pool:
    """Keys for one provider. Every read/write of a record holds the pool lock."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counter = 0
        self.records: list[KeyRecord] = []

    def sync(self, keys: list[str]) -> None:
        """Adopt a new key list, keeping the health of keys already known."""
        with self._lock:
            old = {r.key: r for r in self.records}
            self.records = [old.get(k) or KeyRecord(k) for k in keys]

    def acquire(self) -> KeyRecord | None:
        """Least-recently-used key that is not cooling, or None."""
        now = time.monotonic()
        with self._lock:
            ready = [r for r in self.records if r.cooldown_until <= now]
            if not ready:
                return None
            rec = min(ready, key=lambda r: r.seq)
            self._counter += 1
            rec.seq, rec.last_used = self._counter, now
            return rec

    def ok(self, rec: KeyRecord) -> None:
        with self._lock:
            rec.fails = 0
            rec.cooldown_until = 0.0

    def fail(self, rec: KeyRecord, kind: str) -> float:
        """Record a failure; returns the cooldown applied (0 for model-level)."""
        with self._lock:
            if kind == "quota":
                rec.fails += 1
                secs = min(_BASE_COOLDOWN * 2 ** (rec.fails - 1), _MAX_COOLDOWN)
            elif kind == "auth":
                rec.fails += 1
                secs = _AUTH_COOLDOWN
            elif kind == "transient":
                rec.fails += 1
                secs = _TRANSIENT_COOLDOWN
            else:
                return 0.0
            rec.cooldown_until = time.monotonic() + secs
            return secs

    def snapshot(self) -> list[dict]:
        now = time.monotonic()
        with self._lock:
            return [{"key": r.label, "fails": r.fails,
                     "cooling_s": max(0, round(r.cooldown_until - now))}
                    for r in self.records]


_pools = {"gemini": _Pool(), "openrouter": _Pool(), "groq": _Pool()}
_rules: dict[str, list[tuple[str, str]]] = dict(DEFAULT_RULES)
_cfg_lock = threading.Lock()
_cfg_mtime = -1.0
_state_lock = threading.Lock()
_resting_models: dict[tuple[str, str], float] = {}


def _as_list(*vals) -> list[str]:
    out: list[str] = []
    for v in vals:
        for item in (v if isinstance(v, (list, tuple)) else [v]):
            for piece in str(item or "").replace(",", " ").split():
                if piece not in out:
                    out.append(piece)
    return out


def _norm_step(step) -> tuple[str, str] | None:
    if isinstance(step, str):
        prov, _, mdl = step.partition(":")
    elif isinstance(step, dict):
        prov, mdl = step.get("provider", ""), step.get("model", "")
    else:
        return None
    prov, mdl = str(prov).strip().lower(), str(mdl).strip()
    return (prov, mdl) if prov in _pools and mdl else None


def _refresh() -> None:
    """Reload keys and rules if the file changed. Health of known keys survives."""
    global _cfg_mtime, _rules
    with _cfg_lock:
        try:
            mtime = _KEY_FILE.stat().st_mtime
        except OSError:
            mtime = 0.0
        if mtime == _cfg_mtime:
            return
        try:
            data = json.loads(_KEY_FILE.read_text(encoding="utf-8")) if mtime else {}
        except Exception as e:                                   # noqa: BLE001
            print(f"[Router] cannot read {_KEY_FILE.name}: {e}")
            return                       # keep the last good config; retry on next edit
        _cfg_mtime = mtime
        _pools["gemini"].sync(_as_list(data.get("gemini_api_key"), data.get("gemini_api_keys")))
        _pools["openrouter"].sync(_as_list(data.get("openrouter_api_key"), data.get("openrouter_api_keys")))
        _pools["groq"].sync(_as_list(data.get("groq_api_key"), data.get("groq_api_keys")))
        rules = dict(DEFAULT_RULES)
        user = data.get("routing_rules")
        if isinstance(user, dict):
            for task, chain in user.items():
                steps = [s for s in map(_norm_step, chain if isinstance(chain, list) else []) if s]
                if steps:
                    rules[str(task)] = steps
        _rules = rules


# ----------------------------------------------------------------- error handling

class _HTTPFail(Exception):
    def __init__(self, status: int, body: str):
        super().__init__(f"{status} {body[:200]}")
        self.status = status


def _classify(e: BaseException) -> str:
    """quota | auth | gone | transient | other"""
    s = str(e).lower()
    status = getattr(e, "status", None) or getattr(e, "code", None)
    if not isinstance(status, int):
        m = re.match(r"\s*(\d{3})\b", s)          # genai errors start "429 RESOURCE_..."
        status = int(m.group(1)) if m else None
    if status in (429, 402) or any(t in s for t in (
            "resource_exhausted", "quota", "rate limit", "rate_limit")):
        return "quota"
    if status in (401, 403) or any(t in s for t in (
            "api key not valid", "api_key_invalid", "invalid api key",
            "permission_denied", "unauthorized")):
        return "auth"
    if status == 404 or any(t in s for t in (
            "not found", "no endpoints", "model_not_found", "not a valid model")):
        return "gone"
    if status in (408, 500, 502, 503, 504) or isinstance(e, (TimeoutError, OSError)) \
            or any(t in s for t in ("unavailable", "deadline", "timed out", "timeout")):
        return "transient"
    return "other"


def _model_resting(provider: str, model: str) -> bool:
    with _state_lock:
        until = _resting_models.get((provider, model), 0.0)
        if until and time.monotonic() < until:
            return True
        _resting_models.pop((provider, model), None)
        return False


def _rest_model(provider: str, model: str) -> None:
    with _state_lock:
        _resting_models[(provider, model)] = time.monotonic() + _GONE_COOLDOWN


# -------------------------------------------------------------------- adapters

def _gemini(key: str, model: str, prompt: str, system: str, json_mode: bool) -> str:
    from google import genai                       # lazy: router imports without the SDK
    from google.genai import types

    client = genai.Client(
        api_key=key,
        http_options=types.HttpOptions(timeout=int(max(10.0, _TIMEOUT) * 1000)))
    cfg = types.GenerateContentConfig(
        system_instruction=system or None,
        response_mime_type="application/json" if json_mode else None)
    return client.models.generate_content(model=model, contents=prompt, config=cfg).text or ""


def _openai_compat(provider: str, key: str, model: str, prompt: str,
                   system: str, json_mode: bool) -> str:
    if json_mode:                                  # prompt-level; response_format 400s on some models
        system = (system + "\n" if system else "") + \
            "Reply with valid JSON only. No markdown fences, no commentary."
    messages = ([{"role": "system", "content": system}] if system else []) + \
               [{"role": "user", "content": prompt}]
    req = urllib.request.Request(
        _ENDPOINTS[provider] + "/chat/completions",
        data=json.dumps({"model": model, "messages": messages}).encode("utf-8"),
        method="POST",
        headers={"Authorization": f"Bearer {key}",
                 "Content-Type": "application/json",
                 # Groq sits behind Cloudflare, which 403s urllib's default agent.
                 "User-Agent": "jarvis-router/1.0",
                 "X-Title": "JARVIS"})
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
            data = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise _HTTPFail(e.code, e.read().decode("utf-8", "ignore")) from None
    if not data.get("choices"):                    # OpenRouter reports some errors with HTTP 200
        err = data.get("error") or {}
        raise _HTTPFail(int(err.get("code") or 502), str(err.get("message") or data)[:200])
    text = data["choices"][0]["message"].get("content") or ""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()   # R1 reasoning


_ADAPTERS = {
    "gemini": _gemini,
    "openrouter": lambda *a: _openai_compat("openrouter", *a),
    "groq": lambda *a: _openai_compat("groq", *a),
}


# ----------------------------------------------------------------------- engine

def _chain(task: str, model: str | None, prompt: str = "") -> list[tuple[str, str]]:
    prompt_lower = (prompt or "").lower()
    if "gemini" in prompt_lower or "জেমিনাই" in prompt_lower:
        return [("gemini", "gemini-2.5-flash")]

    steps = list(_rules.get(task) or _rules["fast"])
    if model:
        prov = "gemini" if model.startswith(("gemini", "models/")) \
            else "openrouter" if "/" in model else "groq"
        steps = [(prov, model)] + [s for s in steps if s != (prov, model)]
    return steps

def _run(prompt: str, task: str, system: str, model: str | None,
         json_mode: bool = False, accept=None) -> str:
    try:
        _refresh()
        # _run ফাংশনের ভেতরে:
    for provider, mdl in _chain(task if isinstance(task, str) else "fast", model, prompt=prompt):
            pool = _pools[provider]
            if _model_resting(provider, mdl):
                continue
            for _ in range(max(1, len(pool.records))):      # at most one try per key
                rec = pool.acquire()
                if rec is None:                             # none, or all cooling
                    break
                try:
                    out = (_ADAPTERS[provider](rec.key, mdl, prompt, system, json_mode) or "").strip()
                except Exception as e:                      # noqa: BLE001
                    kind = _classify(e)
                    secs = pool.fail(rec, kind)
                    print(f"[Router] {provider}/{mdl} @ {rec.label}: {kind}"
                          + (f", key rests {secs:.0f}s" if secs else "")
                          + f" ({str(e)[:100]})")
                    if kind == "gone":
                        _rest_model(provider, mdl)
                        break
                    if kind == "other":
                        break                               # model/request problem, not the key
                    continue                                # quota/auth/transient: next key
                pool.ok(rec)                                # the key worked either way
                if out and (accept is None or accept(out)):
                    return out
                print(f"[Router] {provider}/{mdl}: empty or unusable reply, moving on")
                break
    except Exception as e:                                  # noqa: BLE001
        print(f"[Router] unexpected: {type(e).__name__}: {str(e)[:140]}")
    return ""


def _parse(raw: str):
    """First JSON object/array in `raw`, tolerant of fences and chatter. None if none."""
    opens = sorted((raw.find(a), a, b) for a, b in (("{", "}"), ("[", "]")) if a in raw)
    for i, _a, b in opens:
        j = raw.rfind(b)
        if i < j:
            try:
                return json.loads(raw[i:j + 1])
            except ValueError:
                continue
    return None


# ------------------------------------------------------------------ public API

def call(prompt: str, task: str = "fast", system: str = "", model: str = None) -> str:
    """One generation, failing over across keys and providers. "" if all failed."""
    return _run(prompt, task, system, model)


def as_json(prompt: str, task: str = "fast", system: str = "") -> dict:
    """call(), parsed. A reply that is not JSON counts as a failure and the next
    step is tried. {} if all failed. A top-level list comes back as {"items": [...]}."""
    raw = _run(prompt, task, system, None, json_mode=True,
               accept=lambda t: _parse(t) is not None)
    val = _parse(raw) if raw else None
    if isinstance(val, dict):
        return val
    return {"items": val} if isinstance(val, list) else {}


def status() -> dict:
    """Key health per provider: label, consecutive fails, seconds left cooling."""
    _refresh()
    return {name: pool.snapshot() for name, pool in _pools.items()}

def fallback_text(contents, config=None, raw_cfg=None, timeout_s: float = 30.0) -> str:
    """gemini.py-এর ফলব্যাক হ্যান্ডলার — জেমিনি ফেইল করলে সরাসরি Groq বা OpenRouter দিয়ে রান করবে"""
    system = ""
    if config is not None:
        system = getattr(config, "system_instruction", None) or \
            (config.get("system_instruction") if isinstance(config, dict) else "") or ""
    
    prompt = ""
    if isinstance(contents, str):
        prompt = contents
    elif isinstance(contents, (list, tuple)):
        parts = []
        for c in contents:
            if isinstance(c, str):
                parts.append(c)
            elif hasattr(c, "text") and c.text:
                parts.append(c.text)
        prompt = "\n".join(parts)
    else:
        prompt = str(contents)

    _refresh()
    # জেমিনি ইতিমধ্যে ব্যর্থ, তাই সরাসরি Groq ও OpenRouter-এ ফলব্যাক হবে
    fallback_steps = [
        ("groq", "llama-3.3-70b-versatile"),
        ("openrouter", "meta-llama/llama-3.3-70b-instruct:free"),
        ("openrouter", "deepseek/deepseek-r1:free")
    ]
    for provider, mdl in fallback_steps:
        pool = _pools[provider]
        if not pool.records or _model_resting(provider, mdl):
            continue
        rec = pool.acquire()
        if rec is None:
            continue
        try:
            out = (_ADAPTERS[provider](rec.key, mdl, prompt, str(system), False) or "").strip()
            if out:
                pool.ok(rec)
                return out
        except Exception as e:
            pool.fail(rec, _classify(e))
            continue

    return ""