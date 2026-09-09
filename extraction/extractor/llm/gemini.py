"""
Gemini REST client tuned for bulk document extraction.

Handles the three things that break naive scripts against this corpus:
  * model availability drift -> ordered fallback chain, 503/429 aware
  * files larger than the 20MB inline cap -> resumable Files API upload
  * repeat runs costing money -> content-addressed response cache on disk
"""
import base64
import hashlib
import json
import os
import random
import threading
import time

import requests
from dotenv import load_dotenv

_HERE = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(_HERE)), ".env"))

API_ROOT = "https://generativelanguage.googleapis.com"

# Ordered by preference. This key loses access to older models over time, and
# individual models return 503 under load, so we walk the chain before failing.
DEFAULT_MODEL_CHAIN = [
    "gemini-3.8-flash",
    "gemini-3.7-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-flash-latest",
]

INLINE_LIMIT_BYTES = 15 * 1024 * 1024  # headroom under the 20MB request cap
RETRYABLE = {408, 429, 500, 502, 503, 504}


class LLMError(RuntimeError):
    pass


class QuotaExhausted(LLMError):
    """Every model has spent its daily free-tier allowance."""


class CacheMiss(LLMError):
    """cache_only is set and this request has no stored response."""


def parse_quota_error(resp):
    """
    Returns (kind, retry_seconds) for a 429.

    kind is 'daily' when the violated quota is the per-day free-tier cap - that
    model is done until the quota window rolls over, so sleeping is pointless -
    or 'rate' for a short-window limit worth waiting out.
    """
    kind, retry = "rate", 30.0
    try:
        error = resp.json().get("error", {})
    except Exception:
        return kind, retry
    for detail in error.get("details", []):
        dtype = detail.get("@type", "")
        if dtype.endswith("QuotaFailure"):
            for violation in detail.get("violations", []):
                if "PerDay" in (violation.get("quotaId") or ""):
                    kind = "daily"
        elif dtype.endswith("RetryInfo"):
            text = str(detail.get("retryDelay", "")).rstrip("s")
            try:
                retry = float(text)
            except ValueError:
                pass
    return kind, retry


def sha1_file(path):
    h = hashlib.sha1()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def sha1_text(text):
    return hashlib.sha1(text.encode("utf-8", "replace")).hexdigest()


class GeminiClient:
    def __init__(self, api_key=None, model_chain=None, cache_dir=None, verbose=True,
                 cache_only=False):
        self.api_key = (api_key or os.getenv("GEMINI_API_KEY", "")).strip()
        if not self.api_key:
            raise LLMError("GEMINI_API_KEY is not set (checked .env and environment).")

        env_chain = os.getenv("GEMINI_MODEL_CHAIN", "").strip()
        if model_chain:
            self.model_chain = list(model_chain)
        elif env_chain:
            self.model_chain = [m.strip() for m in env_chain.split(",") if m.strip()]
        else:
            self.model_chain = list(DEFAULT_MODEL_CHAIN)

        self.cache_dir = cache_dir
        if self.cache_dir:
            os.makedirs(self.cache_dir, exist_ok=True)

        self.verbose = verbose
        # Replay stored responses only; never spend quota. Used to rebuild the
        # workbook after a normalisation fix without re-reading any document.
        self.cache_only = cache_only
        self._upload_cache = {}
        self._lock = threading.Lock()
        self.calls = 0
        self.cache_hits = 0
        self.prompt_tokens = 0
        self.output_tokens = 0
        # Models drop in and out of availability. Once one has failed repeatedly we
        # stop paying the round-trip for it, otherwise every document in the run
        # eats the same dead-model latency.
        self._strikes = {m: 0 for m in self.model_chain}
        self._benched = set()
        # Models whose per-day free-tier allowance is spent. Unlike a bench,
        # this is not worth retrying at all within the run.
        self._exhausted = set()

    STRIKES_TO_BENCH = 3

    def _healthy_models(self):
        live = [m for m in self.model_chain
                if m not in self._benched and m not in self._exhausted]
        if live:
            return live
        # A bench is a guess; an exhausted daily quota is a fact. Retry benched
        # models before giving up, but never the ones that are out of quota.
        return [m for m in self.model_chain if m not in self._exhausted]

    def _mark_exhausted(self, model):
        with self._lock:
            if model not in self._exhausted:
                self._exhausted.add(model)
                if self.verbose:
                    print("      [quota] %s has spent its daily free-tier allowance"
                          % model, flush=True)
            return len(self._exhausted) >= len(self.model_chain)

    def _record(self, model, ok):
        with self._lock:
            if ok:
                self._strikes[model] = 0
                self._benched.discard(model)
            else:
                self._strikes[model] = self._strikes.get(model, 0) + 1
                if self._strikes[model] >= self.STRIKES_TO_BENCH:
                    if model not in self._benched and self.verbose:
                        print("      [model] benching %s after %d consecutive failures"
                              % (model, self._strikes[model]), flush=True)
                    self._benched.add(model)

    # ---------------------------------------------------------------- caching
    def _cache_path(self, key):
        return os.path.join(self.cache_dir, key + ".json") if self.cache_dir else None

    def _cache_get(self, key):
        path = self._cache_path(key)
        if path and os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    return json.load(fh)
            except Exception:
                return None
        return None

    def _cache_put(self, key, value):
        path = self._cache_path(key)
        if not path:
            return
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(value, fh, ensure_ascii=False)
        os.replace(tmp, path)

    # ------------------------------------------------------------ file upload
    def upload_file(self, path, mime_type):
        """Resumable upload for payloads too large to inline. Returns a file URI."""
        digest = sha1_file(path)
        with self._lock:
            if digest in self._upload_cache:
                return self._upload_cache[digest]

        size = os.path.getsize(path)
        start = requests.post(
            API_ROOT + "/upload/v1beta/files?key=" + self.api_key,
            headers={
                "X-Goog-Upload-Protocol": "resumable",
                "X-Goog-Upload-Command": "start",
                "X-Goog-Upload-Header-Content-Length": str(size),
                "X-Goog-Upload-Header-Content-Type": mime_type,
                "Content-Type": "application/json",
            },
            json={"file": {"display_name": os.path.basename(path)[:120]}},
            timeout=120,
        )
        if start.status_code != 200:
            raise LLMError("Files API start failed (%s): %s" % (start.status_code, start.text[:300]))

        upload_url = start.headers.get("x-goog-upload-url") or start.headers.get("X-Goog-Upload-URL")
        if not upload_url:
            raise LLMError("Files API did not return an upload URL.")

        with open(path, "rb") as fh:
            done = requests.post(
                upload_url,
                headers={
                    "Content-Length": str(size),
                    "X-Goog-Upload-Offset": "0",
                    "X-Goog-Upload-Command": "upload, finalize",
                },
                data=fh,
                timeout=1800,
            )
        if done.status_code != 200:
            raise LLMError("Files API upload failed (%s): %s" % (done.status_code, done.text[:300]))

        info = done.json().get("file", {})
        uri = info.get("uri")
        name = info.get("name")

        # A freshly uploaded file sits in PROCESSING briefly; generateContent 400s on it.
        for _ in range(60):
            if info.get("state", "ACTIVE") == "ACTIVE":
                break
            time.sleep(2)
            poll = requests.get(API_ROOT + "/v1beta/" + name + "?key=" + self.api_key, timeout=60)
            if poll.status_code == 200:
                info = poll.json()
        if info.get("state") == "FAILED":
            raise LLMError("Files API processing failed for " + path)

        with self._lock:
            self._upload_cache[digest] = uri
        return uri

    def file_part(self, path, mime_type):
        """Inline small files, upload big ones. Returns a Gemini `parts` entry."""
        if os.path.getsize(path) <= INLINE_LIMIT_BYTES:
            with open(path, "rb") as fh:
                return {"inline_data": {"mime_type": mime_type,
                                        "data": base64.b64encode(fh.read()).decode()}}
        return {"file_data": {"mime_type": mime_type,
                              "file_uri": self.upload_file(path, mime_type)}}

    @staticmethod
    def inline_bytes(data, mime_type):
        return {"inline_data": {"mime_type": mime_type, "data": base64.b64encode(data).decode()}}

    @staticmethod
    def text_part(text):
        return {"text": text}

    # -------------------------------------------------------------- inference
    def generate_json(self, parts, system=None, schema=None, cache_key=None,
                      temperature=0.0, max_output_tokens=32768, label=""):
        """Run one JSON-mode completion. Returns the parsed object."""
        if cache_key:
            cached = self._cache_get(cache_key)
            if cached is not None:
                with self._lock:
                    self.cache_hits += 1
                return cached["data"]

        if self.cache_only:
            raise CacheMiss("no cached response for %s" % (label or "request"))

        gen_config = {
            "temperature": temperature,
            "responseMimeType": "application/json",
            "maxOutputTokens": max_output_tokens,
        }
        if schema:
            gen_config["responseSchema"] = schema

        payload = {"contents": [{"role": "user", "parts": parts}], "generationConfig": gen_config}
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}

        # Sweep the whole chain before sleeping: a 503 on one model should fall
        # through to the next immediately, not after a backoff ladder.
        last_err = None
        for sweep in range(3):
            pending = []  # (model, retry_after) for short-window rate limits
            for model in self._healthy_models():
                url = API_ROOT + "/v1beta/models/" + model + ":generateContent?key=" + self.api_key
                try:
                    resp = requests.post(url, json=payload, timeout=900)
                except Exception as exc:
                    last_err = "%s: connection error %s" % (model, exc)
                    self._record(model, False)
                    continue

                if resp.status_code == 200:
                    data = resp.json()
                    usage = data.get("usageMetadata", {})
                    with self._lock:
                        self.calls += 1
                        self.prompt_tokens += usage.get("promptTokenCount") or 0
                        self.output_tokens += usage.get("candidatesTokenCount") or 0

                    text = self._join_text(data)
                    parsed = None
                    if text:
                        try:
                            parsed = json.loads(text)
                        except json.JSONDecodeError:
                            parsed = self._salvage_json(text)

                    if parsed is not None:
                        self._record(model, True)
                        if cache_key:
                            self._cache_put(cache_key, {"model": model, "data": parsed})
                        return parsed

                    # A 200 with unusable content is the model's problem, not the chain's.
                    last_err = "%s: unusable response (%s)" % (model, self._finish_reason(data))
                    self._record(model, False)
                    continue

                if resp.status_code == 429:
                    kind, retry_after = parse_quota_error(resp)
                    if kind == "daily":
                        last_err = "%s: daily free-tier quota exhausted" % model
                        if self._mark_exhausted(model):
                            raise QuotaExhausted(
                                "Every model in the chain has exhausted its daily free-tier "
                                "quota (20 requests/day/model). Remaining files are untouched; "
                                "re-run after the quota window resets and the on-disk cache "
                                "will skip everything already extracted.")
                        continue
                    last_err = "%s: rate limited" % model
                    pending.append((model, retry_after))
                    continue

                if resp.status_code in RETRYABLE:
                    last_err = "%s: HTTP %s" % (model, resp.status_code)
                    self._record(model, False)
                    continue

                last_err = "%s: HTTP %s %s" % (model, resp.status_code, resp.text[:200])
                self._record(model, False)
                continue

            # Only short-window rate limits are worth waiting out.
            if sweep < 2 and pending:
                delay = min(min(d for _m, d in pending), 60) + random.random() * 2
                if self.verbose:
                    print("      [retry] %s: rate limited; sleeping %.0fs"
                          % (label, delay), flush=True)
                time.sleep(delay)
            elif sweep < 2:
                time.sleep(min(6 * (2 ** sweep), 30) + random.random() * 2)

        raise LLMError("All models failed for %s. Last error: %s" % (label or "request", last_err))

    @staticmethod
    def _join_text(data):
        try:
            parts = data["candidates"][0]["content"]["parts"]
        except (KeyError, IndexError):
            return ""
        return "".join(p.get("text", "") for p in parts).strip()

    @staticmethod
    def _finish_reason(data):
        try:
            return data["candidates"][0].get("finishReason", "?")
        except (KeyError, IndexError):
            return data.get("promptFeedback", {}).get("blockReason", "?")

    @staticmethod
    def _salvage_json(text):
        """Recover from fenced output or a response truncated mid-array."""
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("```", 2)[1]
            if "\n" in cleaned:
                cleaned = cleaned.split("\n", 1)[1]
        cleaned = cleaned.strip().strip("`").strip()

        try:
            return json.loads(cleaned)
        except Exception:
            pass

        # Truncated mid-array: trim back to the last complete building object.
        depth = 0
        last_good = None
        for idx, ch in enumerate(cleaned):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 1:
                    last_good = idx
        if last_good is not None:
            for suffix in ("]}", "}]}", "]}}"):
                try:
                    return json.loads(cleaned[: last_good + 1] + suffix)
                except Exception:
                    continue
        return None
