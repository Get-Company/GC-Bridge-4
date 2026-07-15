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
    @classmethod
    def build_complete_price_payload(
        cls,
        *,
        price: Any,
        rebate_quantity: Any = None,
        rebate_price: Any = None,
        special_price: Any = None,
        special_start_date: Any = None,
        special_end_date: Any = None,
    ) -> dict[str, Any]:
        """Erstellt den vollstaendigen Preis-Payload fuer Vk0.

        Microtech behaelt Felder bei, die in einem Update fehlen. Deshalb werden
        nicht belegte Sonderpreisfelder explizit als Leerwert gesendet. Solange
        ein Sonderpreis konfiguriert ist, darf keine Staffel parallel bestehen;
        ihre Werte werden nur in Microtech geleert und bleiben in Django erhalten.
        """
        has_special_price = special_price not in (None, "")
        price_values = {
            "price": "" if price in (None, "") else price,
            "rebateQuantity": "" if has_special_price or rebate_quantity in (None, "") else rebate_quantity,
            "rebatePrice": "" if has_special_price or rebate_price in (None, "") else rebate_price,
            "specialPrice": "" if special_price in (None, "") else special_price,
            "specialStartDate": "" if special_start_date in (None, "") else special_start_date,
            "specialEndDate": "" if special_end_date in (None, "") else special_end_date,
        }
        return {"priceTrees": [{"tree": "Vk0", **price_values}]}
