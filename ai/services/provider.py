from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from core.services import BaseService

from ai.models import AIProviderConfig


class AIProviderService(BaseService):
    model = AIProviderConfig

    def structured_response(
        self, *, provider: AIProviderConfig, instructions: str,
        context: dict[str, Any], schema: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Run one bounded Responses request; never expose upstream error bodies.

        Customer reconciliation intentionally uses only the official endpoint,
        disables storage and tools, and does not automatically retry paid calls.
        """
        if provider.base_url.rstrip("/") != "https://api.openai.com/v1":
            raise ValueError("Für den Kundenmerge bitte einen OpenAI-Provider auswählen.")
        if not provider.is_active or not (provider.api_key or "").strip():
            raise ValueError("Beim gewählten KI-Provider fehlt ein aktiver API-Schlüssel.")
        request = urllib.request.Request(
            "https://api.openai.com/v1/responses",
            data=json.dumps({
                "model": provider.model_name,
                "instructions": instructions,
                "input": json.dumps(context, ensure_ascii=False),
                "store": False,
                "max_output_tokens": 10000,
                "text": {"format": {
                    "type": "json_schema", "name": "customer_reconciliation",
                    "strict": True, "schema": schema,
                }},
            }).encode("utf-8"),
            headers={"Authorization": f"Bearer {provider.api_key.strip()}",
                     "Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=min(provider.timeout_seconds, 120)) as response:
                raw = response.read(2_000_001)
            if len(raw) > 2_000_000:
                raise RuntimeError("Die KI-Antwort überschreitet die zulässige Größe.")
            result = json.loads(raw)
        except urllib.error.HTTPError as exc:
            messages = {
                401: "Der API-Schlüssel des KI-Providers wurde abgelehnt.",
                403: "Der KI-Provider hat keinen Zugriff auf das gewählte Modell.",
                404: "Das eingetragene KI-Modell ist über die API nicht verfügbar.",
                429: "Das API-Kontingent oder das Anfragelimit ist erreicht. Bitte die API-Abrechnung prüfen.",
            }
            raise RuntimeError(messages.get(exc.code, "Die KI-Anfrage ist fehlgeschlagen. Bitte Modell und Provider prüfen.")) from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise RuntimeError("Die KI hat nicht rechtzeitig geantwortet. Es wurde nichts geändert.") from None
        if result.get("status") != "completed":
            raise RuntimeError("Die KI-Antwort ist unvollständig. Es wurde kein Vorschlag freigegeben.")
        parts = []
        for item in result.get("output", []):
            for content in item.get("content", []):
                if content.get("type") == "refusal":
                    raise RuntimeError("Die KI konnte für diese Daten keinen Vorschlag erstellen.")
                if content.get("type") == "output_text":
                    parts.append(content.get("text", ""))
        try:
            parsed = json.loads("".join(parts))
        except (ValueError, TypeError):
            raise RuntimeError("Die KI hat keinen gültigen Änderungsvorschlag geliefert.") from None
        usage = result.get("usage") or {}
        return parsed, {key: usage.get(key, 0) for key in ("input_tokens", "output_tokens", "total_tokens")}

    def rewrite_text(
        self,
        *,
        provider: AIProviderConfig,
        system_prompt: str,
        user_prompt: str,
        temperature: float | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> str:
        result_text, _provider_response = self.rewrite_text_with_response(
            provider=provider,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=temperature,
            response_format=response_format,
        )
        return result_text

    def rewrite_text_with_response(
        self,
        *,
        provider: AIProviderConfig,
        system_prompt: str,
        user_prompt: str,
        temperature: float | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> tuple[str, str]:
        api_key = (provider.api_key or "").strip()

        payload = {
            "model": provider.model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": float(temperature if temperature is not None else provider.temperature),
        }
        if response_format:
            payload["response_format"] = response_format

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            url=f"{provider.base_url.rstrip('/')}/chat/completions",
            data=body,
            headers=headers,
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

        return (
            self._extract_message_content(parsed),
            json.dumps(parsed, ensure_ascii=False, indent=2, default=str),
        )

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
