"""Small Gemini client with a response cache.

Every prompt and its answer are stored in the run folder's cache/ (RSI_RUNS_DIR,
default runs/), so a run can be replayed later without an API key (set RSI_REPLAY=1).
"""
import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / os.environ.get("RSI_RUNS_DIR", "runs") / "cache"   # one cache per run, so parallel runs never mix
MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash")
URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


def _key(prompt: str, model: str) -> str:
    return hashlib.sha256(f"{model}\n{prompt}".encode()).hexdigest()[:24]


def ask_json(prompt: str, *, model: str = MODEL, temperature: float = 0.2, cache_dir: Path = CACHE):
    """Send a prompt, expect a JSON answer, return the parsed object.

    Prompts that contain private source text must pass a cache_dir outside the
    repository, so the raw text is never committed.
    """
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"{_key(prompt, model)}.json"
    if path.exists():
        return json.loads(path.read_text())["answer"]
    if os.environ.get("RSI_REPLAY") == "1":
        raise RuntimeError(f"replay mode: no cached answer for prompt {path.name}")
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not set (or use RSI_REPLAY=1)")
    body = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": temperature, "responseMimeType": "application/json"},
    }
    req = urllib.request.Request(
        URL.format(model=model),
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
    )
    last = None
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:  # fixed https host
                data = json.load(resp)
            text = data["candidates"][0]["content"]["parts"][0]["text"]
            answer = json.loads(text)
            path.write_text(json.dumps({"model": model, "prompt": prompt, "answer": answer},
                                       ensure_ascii=False, indent=1))
            return answer
        except (urllib.error.URLError, KeyError, json.JSONDecodeError, TimeoutError) as exc:
            last = exc
            time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"Gemini call failed: {last}")
