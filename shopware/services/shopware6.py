from lib_shopware6_api_base import (
    Shopware6AdminAPIClientBase,
    Criteria,
    EqualsFilter,
    ContainsFilter,
)
from loguru import logger

from shopware.services.base import ShopwareBaseService
from shopware.services.config import ConfShopware6ApiBase

try:
    from authlib.integrations.base_client.errors import InvalidTokenError
except Exception:  # pragma: no cover
    class InvalidTokenError(Exception):
        pass


class Shopware6Service(ShopwareBaseService):
    def __init__(self) -> None:
        super().__init__()
        self.client = self._build_client()

    @staticmethod
    def _build_client():
        return Shopware6AdminAPIClientBase(config=ConfShopware6ApiBase())

    @staticmethod
    def _is_invalid_token_error(exc: Exception) -> bool:
        return isinstance(exc, InvalidTokenError) or "token_invalid" in str(exc).lower()

    def _request_with_retry(self, method_name: str, *args, **kwargs):
        request_method = getattr(self.client, method_name)
        try:
            return request_method(*args, **kwargs)
        except Exception as exc:
            if not self._is_invalid_token_error(exc):
                raise
            logger.warning("Shopware token invalid. Reinitializing API client and retrying request once.")
            self.client = self._build_client()
            retry_method = getattr(self.client, method_name)
            return retry_method(*args, **kwargs)

    def authenticate(self) -> str:
        if not self.client_id or not self.client_secret:
            raise ValueError("Missing Shopware API credentials.")

        grant_type = (self.grant_type or "").lower()
        if grant_type in ("resource_owner", "client_credentials"):
            payload = {
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            }
        elif grant_type in ("user_credentials", "password"):
            if not self.username or not self.password:
                raise ValueError("Missing Shopware user credentials.")
            payload = {
                "grant_type": "password",
                "client_id": self.client_id or "administration",
                "client_secret": self.client_secret or "",
                "username": self.username,
                "password": self.password,
            }
        else:
            raise ValueError(f"Unsupported grant type: {self.grant_type}")

        response = self.request("POST", "/api/oauth/token", payload=payload, require_auth=False)
        token = response.get("access_token") if isinstance(response, dict) else None
        if not token:
            raise RuntimeError("Failed to obtain Shopware access token.")
        return token

    def request_get(self, path: str):
        logger.debug("Shopware6 GET {}", path)
        result = self._request_with_retry("request_get", path)
        logger.debug("Shopware6 GET {} -> {}", path, result)
        return result

    def request_post(self, path: str, payload: dict | None = None, additional_query_params: dict | None = None):
        logger.debug("Shopware6 POST {} payload={}", path, payload)
        result = self._request_with_retry(
            "request_post",
            path,
            payload=payload,
            additional_query_params=additional_query_params,
        )
        logger.debug("Shopware6 POST {} -> {}", path, result)
        return result

    def request_patch(self, path: str, payload: dict | None = None):
        logger.debug("Shopware6 PATCH {} payload={}", path, payload)
        result = self._request_with_retry("request_patch", path, payload=payload)
        logger.debug("Shopware6 PATCH {} -> {}", path, result)
        return result

    def request_delete(self, path: str):
        logger.debug("Shopware6 DELETE {}", path)
        result = self._request_with_retry("request_delete", path)
        logger.debug("Shopware6 DELETE {} -> {}", path, result)
        return result


__all__ = [
    "Shopware6Service",
    "Criteria",
    "EqualsFilter",
    "ContainsFilter",
]
