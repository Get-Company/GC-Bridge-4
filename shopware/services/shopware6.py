from lib_shopware6_api_base import (
    Shopware6AdminAPIClientBase,
    Criteria,
    EqualsFilter,
    ContainsFilter,
)
from loguru import logger

from shopware.services.base import ShopwareBaseService
from shopware.services.config import ConfShopware6ApiBase


class Shopware6Service(ShopwareBaseService):
    def __init__(self) -> None:
        super().__init__()
        self.client = Shopware6AdminAPIClientBase(config=ConfShopware6ApiBase())

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
        result = self.client.request_get(path)
        logger.debug("Shopware6 GET {} -> {}", path, result)
        return result

    def request_post(self, path: str, payload: dict | None = None, additional_query_params: dict | None = None):
        logger.debug("Shopware6 POST {} payload={}", path, payload)
        result = self.client.request_post(path, payload=payload, additional_query_params=additional_query_params)
        logger.debug("Shopware6 POST {} -> {}", path, result)
        return result

    def request_patch(self, path: str, payload: dict | None = None):
        logger.debug("Shopware6 PATCH {} payload={}", path, payload)
        result = self.client.request_patch(path, payload=payload)
        logger.debug("Shopware6 PATCH {} -> {}", path, result)
        return result

    def request_delete(self, path: str):
        logger.debug("Shopware6 DELETE {}", path)
        result = self.client.request_delete(path)
        logger.debug("Shopware6 DELETE {} -> {}", path, result)
        return result


__all__ = [
    "Shopware6Service",
    "Criteria",
    "EqualsFilter",
    "ContainsFilter",
]
