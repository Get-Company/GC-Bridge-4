from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from core.services import BaseService

from ai.models import AIProviderConfig


class AIProviderService(BaseService):
    model = AIProviderConfig

    def rewrite_text(
        self,
        *,
        provider: AIProviderConfig,
        system_prompt: str,
        user_prompt: str,
        temperature: float | None = None,
    ) -> str:
        api_key = (provider.api_key or "").strip()
        if not api_key:
            raise ValueError(f"AI Provider '{provider.name}' hat keinen API-Key.")

        payload = {
            "model": provider.model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": float(temperature if temperature is not None else provider.temperature),
        }
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            url=f"{provider.base_url.rstrip('/')}/chat/completions",
            data=body,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=provider.timeout_seconds) as response:
                parsed = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"AI request failed ({exc.code}): {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError("AI request failed (connection error)") from exc

        return self._extract_message_content(parsed)

    @staticmethod
    def _extract_message_content(payload: dict[str, Any]) -> str:
        choices = payload.get("choices") or []
        if not choices:
            raise RuntimeError("AI response enthaelt keine choices.")
        message = (choices[0] or {}).get("message") or {}
        content = message.get("content")
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            text_parts = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    text_parts.append(str(item.get("text") or ""))
            result = "".join(text_parts).strip()
            if result:
                return result
        raise RuntimeError("AI response enthaelt keinen Textinhalt.")

