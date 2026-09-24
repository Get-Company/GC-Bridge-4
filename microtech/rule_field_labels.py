"""Presentation labels for rule-builder fields; rule field paths stay unchanged."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path


# These paths describe the Shopware values read by orders.services.order_sync.
# Values calculated or maintained by the Bridge deliberately have no API alias.
_ORDER_API_PATHS = {
    "api_id": "id",
    "api_delivery_id": "deliveries[0].id",
    "api_transaction_id": "transactions[0].id",
    "paypal_transaction_id": "transactions[0].customFields",
    "sales_channel_id": "salesChannelId",
    "order_number": "orderNumber",
    "description": "customerComment",
    "total_price": "price.totalPrice",
    "total_tax": "price.calculatedTaxes[].tax",
    "shipping_costs": "shippingCosts.totalPrice",
    "payment_method": "transactions[0].paymentMethod.name",
    "shipping_method": "deliveries[0].shippingMethod.name",
    "order_state": "stateMachineState.technicalName",
    "shipping_state": "deliveries[0].stateMachineState.technicalName",
    "payment_state": "transactions[0].stateMachineState.technicalName",
    "purchase_date": "createdAt",
}

_CUSTOMER_API_PATHS = {
    "erp_nr": "customerNumber",
    "name": "firstName",
    "company": "company",
    "email": "email",
    "api_id": "id",
    "shopware_customer_group": "group.name",
    "vat_id": "vatIds[0]",
    "is_gross": "group.displayGross",
}

_ADDRESS_API_PATHS = {
    "api_id": "id",
    "company": "company",
    "department": "department",
    "street": "street",
    "postal_code": "zipcode",
    "city": "city",
    "country_code": "country.iso",
    "email": "email",
    "title": "salutation.displayName",
    "first_name": "firstName",
    "last_name": "lastName",
    "phone": "phoneNumber",
}

_POSITION_API_PATHS = {
    "api_id": "id",
    "name": "label",
    "unit": "unitName",
    "quantity": "quantity",
    "unit_price": "price.unitPrice",
    "total_price": "price.totalPrice",
    "tax": "price.calculatedTaxes[0].tax",
}


def _description(label: str, path: str) -> str:
    text = str(label or "").strip()
    suffix = f" ({path})"
    if text.endswith(suffix):
        text = text[: -len(suffix)]
    for prefix in (
        "Order - ", "Customer - ", "Billing Address - ",
        "Shipping Address - ", "Bestellung - ", "Bestellposition - ",
        "Anschrift - ", "Kunde - ", "Rechnungsanschrift - ",
        "Lieferanschrift - ", "Zielbereich - ", "Bisheriges Mapping - ",
    ):
        if text.startswith(prefix):
            text = text[len(prefix):]
            break
    return text or path.rsplit("__", 1)[-1]


def shop_field_ui_label(path: str, label: str, *, context_root: str = "orders.Order") -> str:
    """Show Shopware's API name while retaining the Bridge field path as the value."""
    path = str(path or "").strip()
    if not path:
        return str(label or "").strip()
    if path.startswith("code_values__"):
        return f"Bridge-Mapping: {path.removeprefix('code_values__')}"

    if path.startswith("order__"):
        scope, field_name, api_paths = "Bestellung", path[7:], _ORDER_API_PATHS
        api_prefix = ""
    elif path.startswith("customer__"):
        scope, field_name, api_paths = "Kunde", path[10:], _CUSTOMER_API_PATHS
        api_prefix = "customer."
    elif path.startswith("billing_address__"):
        scope, field_name, api_paths = "Rechnungsanschrift", path[17:], _ADDRESS_API_PATHS
        api_prefix = "billingAddress."
    elif path.startswith("shipping_address__"):
        scope, field_name, api_paths = "Lieferanschrift", path[18:], _ADDRESS_API_PATHS
        api_prefix = "deliveries[0].shippingOrderAddress."
    elif path.startswith("address__"):
        scope, field_name, api_paths = "Zielanschrift", path[9:], _ADDRESS_API_PATHS
        api_prefix = "address."
    elif context_root == "customer.Address":
        scope, field_name, api_paths = "Anschrift", path, _ADDRESS_API_PATHS
        api_prefix = "address."
    elif context_root == "orders.OrderDetail":
        scope, field_name, api_paths = "Bestellposition", path, _POSITION_API_PATHS
        api_prefix = "lineItems[]."
    else:
        scope, field_name, api_paths = "Bestellung", path, _ORDER_API_PATHS
        api_prefix = ""

    description = _description(label, path)
    api_path = api_paths.get(field_name)
    if api_path:
        return f"{scope}: {api_prefix}{api_path} - {description}"
    return f"{scope} (Bridge): {field_name} - {description}"


def shop_field_paths_matching_api(query: str) -> set[str]:
    """Let the admin autocomplete find local fields by their displayed API name."""
    query = str(query or "").strip().casefold()
    if not query:
        return set()
    paths: set[str] = set()
    for prefix, api_fields in (
        ("", _ORDER_API_PATHS),
        ("order__", _ORDER_API_PATHS),
        ("customer__", _CUSTOMER_API_PATHS),
        ("billing_address__", _ADDRESS_API_PATHS),
        ("shipping_address__", _ADDRESS_API_PATHS),
    ):
        paths.update(
            f"{prefix}{local_name}"
            for local_name, api_path in api_fields.items()
            if query in api_path.casefold()
        )
    return paths


@lru_cache(maxsize=1)
def microtech_list_labels() -> dict[tuple[str, str], str]:
    """Read the bundled FELD_25.LST once for UI labels without changing catalog rows."""
    from microtech.services.dataset_field_catalog_import import (
        CORE_DATASET_SELECTORS,
        MicrotechDatasetFieldCatalogImportService,
    )

    list_file = Path(__file__).resolve().parent.parent / "FELD_25.LST"
    if not list_file.is_file():
        return {}
    datasets = MicrotechDatasetFieldCatalogImportService().parse_list_file(
        file_path=list_file,
        selectors=CORE_DATASET_SELECTORS,
    )
    return {
        (dataset.name, field.field_name): field.label
        for dataset in datasets
        for field in dataset.fields
    }


def microtech_field_ui_label(
    field_name: str, description: str, *, dataset_name: str = ""
) -> str:
    """Match the ``Field: <abbreviation> - <short description>`` list format."""
    field_name = str(field_name or "").strip()
    if dataset_name:
        description = microtech_list_labels().get((dataset_name, field_name), description)
    description = str(description or "").strip()
    if not field_name:
        return description
    return f"{field_name} - {description}" if description and description != field_name else field_name


# GraphQL input names are translated to COM fields by the GraphQL wrapper.
# Only one-to-one targets are listed; the short descriptions come from the
# bundled FELD_25.LST, not from this mapping.
_POSTAL_GRAPHQL_FIELDS = {
    "isDefaultShipping": "StdLiKz",
    "isDefaultBilling": "StdReKz",
    "name1": "Na1",
    "name2": "Na2",
    "name3": "Na3",
    "street": "Str",
    "zipCode": "PLZ",
    "city": "Ort",
    "email": "EMail1",
    "phone": "Tel",
    "department": "Abt",
    "country": "Land",
}

_CONTACT_GRAPHQL_FIELDS = {
    "isDefault": "StdKz",
    "salutation": "Anr",
    "firstName": "VNa",
    "lastName": "NNa",
    "displayName": "Ansp",
    "department": "Abt",
    "email": "EMail1",
    "phone": "Tel1",
}

_CUSTOMER_GRAPHQL_FIELDS = {
    "vatId": ("Adressen", "UStId"),
    "taxCategory": ("Adressen", "UStKat"),
    "defaultShippingAddressNumber": ("Adressen", "LiAnsNr"),
    "defaultBillingAddressNumber": ("Adressen", "ReAnsNr"),
    **{name: ("Anschriften", target) for name, target in _POSTAL_GRAPHQL_FIELDS.items()
       if name not in {"isDefaultShipping", "isDefaultBilling"}},
    **{name: ("Ansprechpartner", target) for name, target in _CONTACT_GRAPHQL_FIELDS.items()
       if name in {"salutation", "firstName", "lastName"}},
}

_VORGANG_GRAPHQL_FIELDS = {
    "orderNumber": "AuftrNr",
    "description": "Bez",
    "date": "Dat",
    "customerNumber": "AdrNr",
}

_POSITION_GRAPHQL_FIELDS = {
    "erpNumber": "ArtNr",
    "quantity": "Mge",
    "unit": "Einh",
    "price": "EPr",
    "name": "Bez",
}


def graphql_microtech_field_target(input_type: str, field_name: str) -> tuple[str, str] | None:
    """Return the catalog field that a GraphQL input writes, when unambiguous."""
    if input_type == "CustomerInput":
        return _CUSTOMER_GRAPHQL_FIELDS.get(field_name)
    if input_type == "PostalAddressInput":
        target = _POSTAL_GRAPHQL_FIELDS.get(field_name)
        return ("Anschriften", target) if target else None
    if input_type == "ContactPersonInput":
        target = _CONTACT_GRAPHQL_FIELDS.get(field_name)
        return ("Ansprechpartner", target) if target else None
    if input_type == "WebshopDefaultsInput":
        return ("Adressen", field_name)
    if input_type == "VorgangInput":
        target = _VORGANG_GRAPHQL_FIELDS.get(field_name)
        return ("Vorgang", target) if target else None
    if input_type == "VorgangPositionInput":
        target = _POSITION_GRAPHQL_FIELDS.get(field_name)
        return ("VorgangPosition", target) if target else None
    return None


def graphql_field_ui_label(
    input_type: str,
    field_name: str,
    description: str,
    catalog_labels: dict[tuple[str, str], str],
) -> str:
    target = graphql_microtech_field_target(input_type, field_name)
    if target:
        short_description = catalog_labels.get(target)
        if short_description:
            return microtech_field_ui_label(target[1], short_description)
    description = str(description or "").strip()
    return f"{field_name} - {description} (GraphQL)" if description else f"{field_name} (GraphQL)"
