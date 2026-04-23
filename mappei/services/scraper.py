"""Mappei price scraper.

Crawls https://www.mappei.de/de/sitemap, extracts product URLs,
then parses each product page for artikelnr, VPE, price and optional
tiered prices (Staffelpreise).

Only creates a MappeiPriceSnapshot when prices actually changed
compared to the previous snapshot (via MappeiPriceSnapshot.create_if_changed).
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Iterator

import requests
from bs4 import BeautifulSoup
from django.utils import timezone
from loguru import logger

BASE_URL = "https://www.mappei.de"
SITEMAP_PATH = "/de/sitemap"
PRODUCT_URL_RE = re.compile(r"^/de/.+/\d{4,}(?:/\d+)?$")

# Markers that indicate the end of the product header section
END_MARKERS = [
    "Beschreibung",
    "Produktinformationen",
    "Zubehör",
    "Zum Merkzettel hinzufügen",
]

# Regexes for data extraction
RE_ARTIKELNR = re.compile(
    r"Produktnummer[:\s]*([A-Z0-9][A-Z0-9-]*(?:/[A-Z0-9][A-Z0-9-]*)*)",
    re.IGNORECASE,
)
RE_VPE = re.compile(r"Inhalt[:\s]*(\d+)\s*([A-Za-zÄÖÜäöüß]+)", re.IGNORECASE)
RE_PRICE_NETTO = re.compile(
    r"(\d{1,3}(?:\.\d{3})*,\d{2})\s*€[*]?\s+Brutto\s+(\d{1,3}(?:\.\d{3})*,\d{2})\s*€",
    re.IGNORECASE,
)
RE_STAFFEL_START = re.compile(r"Ab\s+(\d+)", re.IGNORECASE)
RE_PRICE_VALUE = re.compile(r"(\d{1,3}(?:\.\d{3})*,\d{2})")


def _parse_decimal(value: str) -> Decimal:
    """Convert German price string '1.234,56' to Decimal."""
    return Decimal(value.replace(".", "").replace(",", "."))


def _fetch(url: str, timeout: int = 15) -> str | None:
    try:
        response = requests.get(url, timeout=timeout, headers={"User-Agent": "GC-Bridge/1.0"})
        response.raise_for_status()
        return response.text
    except Exception as exc:
        logger.warning("Failed to fetch {}: {}", url, exc)
        return None


def _product_urls_from_sitemap() -> Iterator[str]:
    """Yield absolute product URLs found on the sitemap page."""
    html = _fetch(BASE_URL + SITEMAP_PATH)
    if not html:
        return
    soup = BeautifulSoup(html, "html.parser")
    seen: set[str] = set()
    for tag in soup.find_all("a", href=True):
        href: str = tag["href"]
        # Make absolute if relative
        if href.startswith("/"):
            path = href
        elif href.startswith(BASE_URL):
            path = href[len(BASE_URL):]
        else:
            continue
        if PRODUCT_URL_RE.match(path) and path not in seen:
            seen.add(path)
            yield BASE_URL + path


def _extract_product_header(text: str) -> str:
    """Return only the product header portion of page text."""
    for marker in END_MARKERS:
        idx = text.find(marker)
        if idx != -1:
            return text[:idx]
    return text


def _extract_image_url(soup) -> str:
    """Extract product image URL from og:image meta tag."""
    og = soup.find("meta", property="og:image")
    if og and og.get("content"):
        return og["content"]
    return ""


def _extract_name(soup) -> str:
    """Extract product name from h1.product-detail-name."""
    tag = soup.find("h1", class_="product-detail-name")
    if tag:
        return tag.get_text(strip=True)
    return ""


def _extract_description(soup) -> str:
    """Extract product description from .product-detail-description-text or similar."""
    for selector in (
        {"class_": "product-detail-description-text"},
        {"class_": "product-description"},
        {"itemprop": "description"},
    ):
        tag = soup.find(attrs=selector)
        if tag:
            return tag.get_text(separator=" ", strip=True)
    return ""


def _parse_product_page(html: str, url: str) -> dict | None:
    """Parse a product page and return a data dict or None on failure."""
    soup = BeautifulSoup(html, "html.parser")
    image_url = _extract_image_url(soup)
    name = _extract_name(soup)
    description = _extract_description(soup)
    text = soup.get_text(separator=" ", strip=True)
    header = _extract_product_header(text)

    # --- Artikelnummer ---
    m = RE_ARTIKELNR.search(header)
    if not m:
        logger.debug("No artikelnr found at {}", url)
        return None
    artikelnr = m.group(1).strip()

    # --- VPE ---
    vpe_menge: int | None = None
    vpe_einheit: str = ""
    m_vpe = RE_VPE.search(header)
    if m_vpe:
        try:
            vpe_menge = int(m_vpe.group(1))
            vpe_einheit = m_vpe.group(2).strip()
        except ValueError:
            pass

    # --- Staffelblock detection ---
    has_staffel = bool(
        re.search(r"Anzahl", header, re.IGNORECASE)
        and re.search(r"Paketpreis", header, re.IGNORECASE)
        and re.search(r"Stückpreis", header, re.IGNORECASE)
        and RE_STAFFEL_START.search(header)
    )

    if has_staffel:
        return _parse_with_staffel(
            header=header,
            artikelnr=artikelnr,
            url=url,
            image_url=image_url,
            name=name,
            description=description,
            vpe_menge=vpe_menge,
            vpe_einheit=vpe_einheit,
        )
    else:
        return _parse_without_staffel(
            header=header,
            artikelnr=artikelnr,
            url=url,
            image_url=image_url,
            name=name,
            description=description,
            vpe_menge=vpe_menge,
            vpe_einheit=vpe_einheit,
        )


def _parse_without_staffel(
    *,
    header: str,
    artikelnr: str,
    url: str,
    image_url: str,
    name: str,
    description: str,
    vpe_menge: int | None,
    vpe_einheit: str,
) -> dict | None:
    m = RE_PRICE_NETTO.search(header)
    if not m:
        logger.debug("No netto price found at {}", url)
        return None
    try:
        preis = _parse_decimal(m.group(1))
    except InvalidOperation:
        logger.warning("Could not parse price '{}' at {}", m.group(1), url)
        return None

    return {
        "artikelnr": artikelnr,
        "url": url,
        "image_url": image_url,
        "name": name,
        "description": description,
        "vpe_menge": vpe_menge,
        "vpe_einheit": vpe_einheit,
        "hat_staffel": False,
        "preis": preis,
        "staffelpreismenge_min": None,
        "staffelpreismenge_max": None,
        "staffelpreis_min": None,
        "staffelpreis_max": None,
        "partial_success": False,
    }


def _parse_with_staffel(
    *,
    header: str,
    artikelnr: str,
    url: str,
    image_url: str,
    name: str,
    description: str,
    vpe_menge: int | None,
    vpe_einheit: str,
) -> dict | None:
    """Parse staffel block. Returns dict with tiered price data."""
    staffeln: list[dict] = []
    partial_success = False

    for m_start in RE_STAFFEL_START.finditer(header):
        ab_pakete = int(m_start.group(1))
        # Find the next two price values after "Ab N"
        rest = header[m_start.end():]
        prices = RE_PRICE_VALUE.findall(rest[:200])  # limit search window
        if len(prices) < 1:
            continue
        try:
            paketpreis = _parse_decimal(prices[0])
        except InvalidOperation:
            continue
        staffeln.append({"ab_pakete": ab_pakete, "paketpreis": paketpreis})

    if not staffeln:
        logger.debug("Staffel detected but no rows parsed at {}", url)
        return None

    # Umrechnung Pakete → Stück
    if vpe_menge:
        for s in staffeln:
            s["ab_stueck"] = s["ab_pakete"] * vpe_menge
    else:
        partial_success = True
        for s in staffeln:
            s["ab_stueck"] = None

    preis = staffeln[0]["paketpreis"]
    paketpreise = [s["paketpreis"] for s in staffeln]
    staffelpreis_min = min(paketpreise)
    staffelpreis_max = max(paketpreise)

    stueck_values = [s["ab_stueck"] for s in staffeln if s["ab_stueck"] is not None]
    staffelpreismenge_min = min(stueck_values) if stueck_values else None
    staffelpreismenge_max = max(stueck_values) if stueck_values else None

    return {
        "artikelnr": artikelnr,
        "url": url,
        "image_url": image_url,
        "name": name,
        "description": description,
        "vpe_menge": vpe_menge,
        "vpe_einheit": vpe_einheit,
        "hat_staffel": True,
        "preis": preis,
        "staffelpreismenge_min": staffelpreismenge_min,
        "staffelpreismenge_max": staffelpreismenge_max,
        "staffelpreis_min": staffelpreis_min,
        "staffelpreis_max": staffelpreis_max,
        "partial_success": partial_success,
    }


def scrape_product(url: str) -> dict | None:
    """Fetch and parse a single product URL. Returns data dict or None."""
    html = _fetch(url)
    if not html:
        return None
    return _parse_product_page(html, url)


def run_scraper(
    *,
    limit: int | None = None,
    single_artikelnr: str | None = None,
) -> dict:
    """Main entry point. Crawls sitemap and upserts products + snapshots.

    Returns summary dict with counts.
    """
    from mappei.models import MappeiProduct, MappeiPriceSnapshot

    now = timezone.now()
    processed = 0
    snapshots_created = 0
    errors = 0

    if single_artikelnr:
        # Try DB first, otherwise search sitemap for matching URL
        try:
            product = MappeiProduct.objects.get(artikelnr=single_artikelnr)
            urls = [product.url] if product.url else []
        except MappeiProduct.DoesNotExist:
            logger.info("Single mode: {} not in DB, searching sitemap...", single_artikelnr)
            suffix = f"/{single_artikelnr}"
            urls = [u for u in _product_urls_from_sitemap() if u.endswith(suffix)]
            if not urls:
                logger.warning("Single mode: no URL found for artikelnr {} in sitemap.", single_artikelnr)
            else:
                logger.info("Single mode: found URL {} for artikelnr {}.", urls[0], single_artikelnr)
    else:
        urls = list(_product_urls_from_sitemap())
        logger.info("Scraper found {} product URLs in sitemap.", len(urls))

    for url in urls:
        if limit is not None and processed >= limit:
            break

        data = scrape_product(url)
        if data is None:
            errors += 1
            continue

        artikelnr = data["artikelnr"]

        # Upsert MappeiProduct
        product, _ = MappeiProduct.objects.update_or_create(
            artikelnr=artikelnr,
            defaults={
                "url": data["url"],
                "image_url": data["image_url"],
                "name": data["name"],
                "description": data["description"],
                "vpe_menge": data["vpe_menge"],
                "vpe_einheit": data["vpe_einheit"],
                "hat_staffel": data["hat_staffel"],
                "last_scraped_at": now,
            },
        )

        # Create snapshot only if prices changed
        snapshot = MappeiPriceSnapshot.create_if_changed(
            product=product,
            scraped_at=now,
            preis=data["preis"],
            staffelpreismenge_min=data["staffelpreismenge_min"],
            staffelpreismenge_max=data["staffelpreismenge_max"],
            staffelpreis_min=data["staffelpreis_min"],
            staffelpreis_max=data["staffelpreis_max"],
            partial_success=data["partial_success"],
        )
        if snapshot:
            snapshots_created += 1
            logger.debug("Price change recorded for artikelnr {}.", artikelnr)

        processed += 1

    logger.info(
        "Scraper finished. processed={} snapshots_created={} errors={}",
        processed,
        snapshots_created,
        errors,
    )
    return {"processed": processed, "snapshots_created": snapshots_created, "errors": errors}
