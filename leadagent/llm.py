"""Minimal Gemini (free tier) client over REST, with rate limiting, retries and a disk cache."""
import hashlib
import json
import os
import re
import threading
import time

import requests

from . import config

CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".cache", "llm")
API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

_lock = threading.Lock()
_last_call = 0.0
_dead_models: set[str] = set()


class LLMError(Exception):
    pass


def _throttle():
    global _last_call
    with _lock:
        wait = config.LLM_MIN_SECONDS_BETWEEN_CALLS - (time.time() - _last_call)
        if wait > 0:
            time.sleep(wait)
        _last_call = time.time()


def _parse_json(text: str) -> dict:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    return json.loads(text)


def generate_json(prompt: str, system: str = "", use_cache: bool = True, temperature: float = 0.2) -> dict:
    if not config.GEMINI_API_KEY:
        raise LLMError("GEMINI_API_KEY is not set (see README)")
    key = hashlib.sha1(f"{system}\n{prompt}\n{temperature}".encode()).hexdigest()
    cp = os.path.join(CACHE_DIR, key + ".json")
    if use_cache and os.path.exists(cp):
        with open(cp, encoding="utf-8") as f:
            return json.load(f)

    body = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": temperature, "responseMimeType": "application/json"},
    }
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}

    last_err = ""
    for model in [m for m in config.GEMINI_MODELS if m not in _dead_models]:
        for attempt in range(4):
            _throttle()
            try:
                r = requests.post(API.format(model=model), params={"key": config.GEMINI_API_KEY}, json=body, timeout=120)
            except requests.RequestException as e:
                last_err = f"{type(e).__name__}: {e}"
                time.sleep(3 * (attempt + 1))
                continue
            if r.status_code == 404:
                _dead_models.add(model)
                last_err = f"model {model} not available"
                break
            if r.status_code in (429, 500, 503):
                m = re.search(r'"retryDelay":\s*"(\d+)', r.text)
                delay = int(m.group(1)) + 1 if m else 10 * (attempt + 1)
                last_err = f"HTTP {r.status_code} from {model}"
                time.sleep(min(delay, 60))
                continue
            if r.status_code != 200:
                raise LLMError(f"HTTP {r.status_code}: {r.text[:300]}")
            try:
                data = r.json()
                text = "".join(p.get("text", "") for p in data["candidates"][0]["content"]["parts"])
                out = _parse_json(text)
            except (KeyError, IndexError, ValueError) as e:
                last_err = f"unparseable model output: {type(e).__name__}"
                continue
            os.makedirs(CACHE_DIR, exist_ok=True)
            with open(cp, "w", encoding="utf-8") as f:
                json.dump(out, f)
            return out
    raise LLMError(last_err or "no Gemini model available")
