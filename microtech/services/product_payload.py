from __future__ import annotations

from typing import Any

from core.services import BaseService


class MicrotechProductPayloadService(BaseService):
    PRICE_TREE_FIELDS = (
        "price",
        "rebateQuantity",
        "rebatePrice",
        "specialPrice",
        "specialStartDate",
        "specialEndDate",
    )
    PRICE_TREE_NAMES = ("Vk0", "Vk1")

    @classmethod
    def duplicate_vk0_prices_to_vk1(cls, input_data: dict[str, Any]) -> dict[str, Any]:
        payload = dict(input_data)
        price_values = {}
        for price_field in cls.PRICE_TREE_FIELDS:
            if price_field in payload and payload[price_field] is not None:
                price_values[price_field] = payload[price_field]
            payload.pop(price_field, None)

        if not price_values:
            return payload

        price_trees = [
            price_tree
            for price_tree in payload.get("priceTrees") or []
            if str(price_tree.get("tree") or "").strip().lower() not in {"vk0", "vk1"}
        ]
        price_trees.extend(
            {"tree": tree_name, **price_values}
            for tree_name in cls.PRICE_TREE_NAMES
        )
        payload["priceTrees"] = price_trees
        return payload
