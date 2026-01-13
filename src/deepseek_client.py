from __future__ import annotations

import json
import time
from typing import Any, Dict, Generator, List, Optional

import requests


class DeepSeekClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        timeout_sec: int = 120,
        max_retries: int = 3,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout_sec = timeout_sec
        self.max_retries = max_retries

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float,
        top_p: float,
        stream: bool = False,
    ) -> str | Generator[str, None, None]:
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "top_p": top_p,
            "stream": stream,
        }
        url = f"{self.base_url}/v1/chat/completions"

        for attempt in range(1, self.max_retries + 1):
            try:
                if stream:
                    return self._stream_response(url, payload)
                return self._non_stream_response(url, payload)
            except Exception:
                if attempt >= self.max_retries:
                    raise
                time.sleep(1.5 * attempt)
        raise RuntimeError("Unreachable")

    def _non_stream_response(self, url: str, payload: Dict[str, Any]) -> str:
        response = requests.post(
            url,
            headers=self._headers(),
            json=payload,
            timeout=self.timeout_sec,
        )
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"]

    def _stream_response(self, url: str, payload: Dict[str, Any]) -> Generator[str, None, None]:
        response = requests.post(
            url,
            headers=self._headers(),
            json=payload,
            timeout=self.timeout_sec,
            stream=True,
        )
        response.raise_for_status()
        for line in response.iter_lines(decode_unicode=True):
            if not line:
                continue
            if not line.startswith("data:"):
                continue
            data = line[len("data:"):].strip()
            if data == "[DONE]":
                break
            payload = json.loads(data)
            delta = payload["choices"][0].get("delta", {})
            content = delta.get("content")
            if content:
                yield content
