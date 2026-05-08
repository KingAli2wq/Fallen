import json
import logging
import re
import httpx

logger = logging.getLogger(__name__)

DEFAULT_URLS = [
    "http://localhost:1234",   # LM Studio
    "http://localhost:8000",   # llama-cpp-python server
    "http://localhost:11434",  # Ollama
]

_CONNECTION_ERRORS = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
    ConnectionRefusedError,
)


def _extract_text(message: dict) -> str:
    """
    Pull the real answer out of a (possibly reasoning) model response.
    Reasoning models (Qwen3.5) output their thinking before the answer.
    The answer is after </think> if present, otherwise we take the full content.
    """
    content = message.get("content") or message.get("reasoning_content") or ""
    # Strip <think>...</think> blocks; answer follows
    after_think = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
    return after_think if after_think else content.strip()


def _last_json(text: str) -> dict | None:
    """
    Extract the last complete {...} JSON block in text.
    Reasoning models output thinking first, then the JSON — so we want the last one.
    """
    # Find all {...} candidates, take the last one that parses
    for match in reversed(list(re.finditer(r"\{", text))):
        end = text.rfind("}", match.start())
        if end == -1:
            continue
        candidate = text[match.start(): end + 1]
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass
    return None


class AIClient:
    def __init__(self, base_url: str = "", timeout: int = 150):
        self.base_url  = ""
        self.timeout   = timeout   # reasoning models need time; 150s is safe
        self.available = False
        self._connect(base_url)

    def _connect(self, hint: str = ""):
        urls = ([hint] if hint else []) + DEFAULT_URLS
        for url in urls:
            try:
                r = httpx.get(f"{url}/v1/models", timeout=3.0)
                if r.status_code == 200:
                    self.base_url = url.rstrip("/")
                    self.available = True
                    logger.info(f"AI connected at {self.base_url}")
                    return
            except Exception:
                pass
        logger.warning("No AI model server found — game runs in offline mode.")

    def complete(self, system: str, user: str, max_tokens: int = 800) -> str | None:
        if not self.available:
            self._connect()
        if not self.available:
            return None
        try:
            r = httpx.post(
                f"{self.base_url}/v1/chat/completions",
                json={
                    "model": "local-model",
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user",   "content": user},
                    ],
                    "max_tokens": max_tokens,
                    "temperature": 0.75,
                },
                timeout=self.timeout,
            )
            r.raise_for_status()
            msg = r.json()["choices"][0]["message"]
            return _extract_text(msg) or None

        except _CONNECTION_ERRORS as e:
            logger.warning(f"AI server unreachable: {e}")
            self.available = False
            return None
        except Exception as e:
            # Timeout or HTTP error — server still up, just slow
            logger.warning(f"AI call error (server still running): {e}")
            return None

    def complete_json(self, system: str, user: str, max_tokens: int = 800) -> dict | None:
        raw = self.complete(
            system,
            user + "\n\nIMPORTANT: Your FINAL output must be ONLY a valid JSON object. No markdown fences.",
            max_tokens,
        )
        if not raw:
            return None
        result = _last_json(raw)
        if result is None:
            logger.warning(f"No JSON found in response: {raw[:150]!r}")
        return result
