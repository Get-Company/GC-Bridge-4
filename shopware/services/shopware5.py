from __future__ import annotations

import os
from decimal import Decimal, ROUND_UP
from typing import Any
from urllib.parse import quote

import requests
from loguru import logger
from requests.adapters import HTTPAdapter
from requests.auth import HTTPBasicAuth, HTTPDigestAuth
from urllib3 import Retry

from core.services import BaseService
from products.models import Price, Product
from shopware.models import Shopware5Settings


class Shopware5APIError(RuntimeError):
    pass


SHOPWARE5_CUSTOMER_GROUP_FACTORS: dict[str, Decimal] = {
    "CHB2C": Decimal("1.3"),
    "CHB2B": Decimal("1.3"),
    "IT_de": Decimal("1.0413"),
    "IT_it": Decimal("1.0413"),
    "Vk0": Decimal("1"),
    "Vk1": Decimal("1"),
    "EK": Decimal("1"),
}


class Shopware5ProductSyncService(BaseService):
    model = Product
    timeout_seconds = 30

    def __init__(
        self,
        *,
        settings_obj: Shopware5Settings | None = None,
        session: requests.Session | None = None,
    ) -> None:
        self.settings = settings_obj if settings_obj is not None else self._load_settings()
        self.base_url = self._normalize_api_url(
            self._config_value("api_url", ("SHOPWARE5_API_URL", "SHOPWARE_API_URL"))
        )
        self.username = self._config_value("username", ("SHOPWARE5_API_USER", "SHOPWARE_API_USER"))
        self.api_token = self._config_value("api_token", ("SHOPWARE5_API_TOKEN", "SHOPWARE_API_TOKEN"))
        legacy_credentials = os.getenv("SHOPWARE_API_CREDENTIALS", "")
        if (not self.username or not self.api_token) and ":" in legacy_credentials:
            self.username, self.api_token = legacy_credentials.split(":", 1)
        self.session = session or self._build_session()

    def sync_products(self, products: list[Product] | tuple[Product, ...]) -> dict[str, object]:
        self._validate_config()
        summary: dict[str, object] = {
            "processed": 0,
            "success": 0,
            "errors": 0,
            "skipped": 0,
            "error_details": [],
        }

        for product in products:
            summary["processed"] = int(summary["processed"]) + 1
            try:
                if not str(product.erp_nr or "").strip():
                    raise ValueError("Product has no ERP number.")
                self.sync_product(product)
                summary["success"] = int(summary["success"]) + 1
            except Exception as exc:
                summary["errors"] = int(summary["errors"]) + 1
                detail = {"erp_nr": getattr(product, "erp_nr", ""), "error": str(exc)}
                error_details = summary["error_details"]
                if isinstance(error_details, list):
                    error_details.append(detail)
                logger.warning("Shopware5 sync failed for {}: {}", getattr(product, "erp_nr", ""), exc)

        return summary

    def sync_product(self, product: Product) -> dict[str, Any]:
        article = self.get_article_by_number(str(product.erp_nr))
        article_id = str(article.get("id") or "").strip()
        if not article_id:
            raise Shopware5APIError(f"Shopware5 article id missing for {product.erp_nr}.")
        payload = self.build_product_payload(product)
        return self.put(f"/articles/{quote(article_id, safe='')}", payload)["data"]

    def get_article_by_number(self, product_number: str) -> dict[str, Any]:
        product_number = quote(str(product_number).strip(), safe="")
        response = self.get(f"/articles/{product_number}?useNumberAsId=true")
        data = response.get("data")
        if not isinstance(data, dict):
            raise Shopware5APIError(f"Shopware5 article not found for {product_number}.")
        return data

    def build_product_payload(self, product: Product) -> dict[str, Any]:
        purchase_unit = self._positive_int(getattr(product, "purchase_unit", None), default=1)
        min_purchase = self._positive_int(getattr(product, "min_purchase", None), default=1)
        name = (self._localized_value(product, "name") or "").strip()
        main_detail: dict[str, Any] = {
            "inStock": self._stock(product),
            "maxPurchase": 2000 * purchase_unit,
            "minPurchase": min_purchase,
            "purchaseSteps": purchase_unit,
        }

        pack_unit = self._pack_unit(getattr(product, "unit", ""))
        if pack_unit:
            main_detail["packUnit"] = pack_unit

        factor = getattr(product, "factor", None)
        main_detail["gcFaktor"] = factor if factor not in (None, 0, "") else None

        price = self._select_price(product)
        if price:
            main_detail["prices"] = self._build_prices(price)

        payload: dict[str, Any] = {
            "active": bool(product.is_active),
            "is_active": bool(product.is_active),
            "mainDetail": main_detail,
        }
        if name:
            payload["name"] = name
        description_short = self._localized_value(product, "description_short")
        if description_short is not None:
            payload["description"] = description_short
        description = self._localized_value(product, "description")
        if description is not None:
            payload["descriptionLong"] = description
        return payload

    def get(self, path: str) -> dict[str, Any]:
        return self._request("get", path)

    def put(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("put", path, payload=payload)

    def _request(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        response = self._request_once(method=method, path=path, payload=payload)
        if self._should_retry_with_basic(response):
            logger.warning(
                "Shopware5 Digest auth was rejected for {}. Retrying once with Basic auth.",
                response.request.url,
            )
            response = self._request_once(
                method=method,
                path=path,
                payload=payload,
                auth=HTTPBasicAuth(self.username, self.api_token),
            )

        try:
            data = response.json()
        except ValueError as exc:
            raise Shopware5APIError(f"Shopware5 returned no JSON: HTTP {response.status_code}") from exc

        if not isinstance(data, dict):
            raise Shopware5APIError(f"Shopware5 returned unexpected JSON: HTTP {response.status_code}: {data}")
        if response.status_code >= 400:
            raise Shopware5APIError(f"Shopware5 request failed: HTTP {response.status_code}: {data}")
        if not data.get("success"):
            raise Shopware5APIError(f"Shopware5 indicated failure: {data}")
        return data

    def _request_once(
        self,
        *,
        method: str,
        path: str,
        payload: dict[str, Any] | None,
        auth: HTTPBasicAuth | None = None,
    ) -> requests.Response:
        kwargs: dict[str, Any] = {
            "method": method.upper(),
            "url": f"{self.base_url}{path}",
            "json": payload,
            "timeout": self.timeout_seconds,
        }
        if auth is not None:
            kwargs["auth"] = auth
        return self.session.request(**kwargs)

    @staticmethod
    def _load_settings() -> Shopware5Settings | None:
        try:
            return Shopware5Settings.load()
        except Exception as exc:
            logger.warning("Shopware5 settings could not be loaded: {}", exc)
            return None

    def _build_session(self) -> requests.Session:
        session = requests.Session()
        if self.username and self.api_token:
            session.auth = HTTPDigestAuth(self.username, self.api_token)
        retry = Retry(
            total=5,
            backoff_factor=0.3,
            status_forcelist=[500, 502, 503, 504],
            allowed_methods=frozenset({"GET", "PUT", "POST", "DELETE"}),
        )
        adapter = HTTPAdapter(max_retries=retry)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        return session

    @staticmethod
    def _normalize_api_url(value: str) -> str:
        url = str(value or "").strip().rstrip("/")
        if not url:
            return ""
        if not url.lower().endswith("/api"):
            url = f"{url}/api"
        return url

    def _should_retry_with_basic(self, response: requests.Response) -> bool:
        if response.status_code not in {401, 403}:
            return False
        if not self.username or not self.api_token:
            return False
        authorization = response.request.headers.get("Authorization", "")
        if authorization.startswith("Basic "):
            return False
        return True

    def _config_value(self, field_name: str, env_names: tuple[str, ...]) -> str:
        setting_value = getattr(self.settings, field_name, "") if self.settings else ""
        if setting_value:
            return str(setting_value).strip()
        for env_name in env_names:
            value = os.getenv(env_name)
            if value:
                return value.strip()
        return ""

    def _validate_config(self) -> None:
        missing = []
        if not self.base_url:
            missing.append("SHOPWARE5_API_URL")
        if not self.username:
            missing.append("SHOPWARE5_API_USER")
        if not self.api_token:
            missing.append("SHOPWARE5_API_TOKEN")
        if missing:
            raise ValueError(
                "Missing Shopware5 config: "
                f"{', '.join(missing)}. Set them in .env or configure the optional Shopware 5 admin overrides."
            )

    @staticmethod
    def _stock(product: Product) -> int:
        try:
            storage = product.storage
        except Exception:
            storage = None
        if not storage:
            return 0
        return int(storage.get_stock or 0)

    @staticmethod
    def _positive_int(value: object, *, default: int) -> int:
        try:
            result = int(value)
        except (TypeError, ValueError):
            return default
        return result if result > 0 else default

    @staticmethod
    def _pack_unit(value: object) -> str:
        unit = str(value or "").strip()
        if "% Stck" in unit:
            return "Stck"
        return unit

    @classmethod
    def _localized_value(cls, product: Product, field_name: str) -> str | None:
        translated_value = cls._string_or_none(getattr(product, f"{field_name}_de", None))
        if translated_value:
            return translated_value

        base_value = cls._string_or_none(getattr(product, field_name, None))
        if base_value is not None:
            return base_value

        fallback_value = cls._string_or_none(getattr(product, f"{field_name}_en", None))
        if fallback_value:
            return fallback_value

        return None

    @staticmethod
    def _string_or_none(value: object) -> str | None:
        if value is None:
            return None
        return str(value or "")

    @staticmethod
    def _select_price(product: Product) -> Price | None:
        prefetched = getattr(product, "prefetched_prices_for_shopware_sync", None)
        if prefetched is not None:
            prices = list(prefetched)
        else:
            prices = list(product.prices.select_related("sales_channel").all())
        if not prices:
            return None
        default_price = next(
            (
                price
                for price in prices
                if getattr(getattr(price, "sales_channel", None), "is_default", False)
                and getattr(getattr(price, "sales_channel", None), "is_active", True)
            ),
            None,
        )
        if default_price:
            return default_price
        active_channel_price = next(
            (
                price
                for price in prices
                if getattr(getattr(price, "sales_channel", None), "is_active", True)
            ),
            None,
        )
        return active_channel_price or prices[0]

    @classmethod
    def _build_prices(cls, price: Price) -> list[dict[str, Any]]:
        prices: list[dict[str, Any]] = []
        for customer_group_key, factor in SHOPWARE5_CUSTOMER_GROUP_FACTORS.items():
            standard_price = cls._round_up_5ct(Decimal(price.price) * factor)
            current_price = standard_price
            pseudo_price = None
            if price.is_special_active and price.special_price:
                current_price = cls._round_up_5ct(Decimal(price.special_price) * factor)
                pseudo_price = standard_price

            rebate_quantity = cls._positive_int(price.rebate_quantity, default=0)
            rebate_price = price.rebate_price
            if rebate_quantity > 1 and rebate_price:
                prices.append(
                    {
                        "customerGroupKey": customer_group_key,
                        "from": 1,
                        "to": rebate_quantity - 1,
                        "price": float(current_price),
                        "pseudoPrice": float(pseudo_price) if pseudo_price is not None else None,
                    }
                )
                prices.append(
                    {
                        "customerGroupKey": customer_group_key,
                        "from": rebate_quantity,
                        "to": "beliebig",
                        "price": float(cls._round_up_5ct(Decimal(rebate_price) * factor)),
                        "pseudoPrice": None,
                    }
                )
                continue

            prices.append(
                {
                    "customerGroupKey": customer_group_key,
                    "from": 1,
                    "to": "beliebig",
                    "price": float(current_price),
                    "pseudoPrice": float(pseudo_price) if pseudo_price is not None else None,
                }
            )
        return prices

    @staticmethod
    def _round_up_5ct(value: Decimal) -> Decimal:
        step = Decimal("0.05")
        return ((value / step).to_integral_value(rounding=ROUND_UP) * step).quantize(Decimal("0.01"))
