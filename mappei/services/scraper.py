"""Mappei price scraper.

Crawls the XML sitemap published by https://www.mappei.de/robots.txt,
extracts product URLs,
then parses each product page for artikelnr, VPE, price and optional
tiered prices (Staffelpreise).

Only creates a MappeiPriceSnapshot when prices actually changed
compared to the previous snapshot (via MappeiPriceSnapshot.create_if_changed).
"""
from __future__ import annotations

import gzip
import re
import xml.etree.ElementTree as ET
from decimal import Decimal, InvalidOperation
from typing import Iterator
from urllib.parse import urlsplit

import requests
from bs4 import BeautifulSoup
from django.utils import timezone
from loguru import logger

BASE_URL = "https://www.mappei.de"
SITEMAP_URL = f"{BASE_URL}/de/sitemap.xml"
PRODUCT_URL_RE = re.compile(r"^/de/.+/[^/]*\d[^/]*$")

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
    """Convert German display prices and machine-readable decimals."""
    value = value.strip().replace("\xa0", "").replace("€", "")
    if "," in value:
        value = value.replace(".", "").replace(",", ".")
    return Decimal(value)


class MappeiSitemapError(RuntimeError):
    """Raised when Mappei's XML sitemap cannot provide product URLs."""


def _request(url: str, timeout: int = 15) -> requests.Response | None:
    try:
        response = requests.get(url, timeout=timeout, headers={"User-Agent": "GC-Bridge/1.0"})
        response.raise_for_status()
        return response
    except Exception as exc:
        logger.warning("Failed to fetch {}: {}", url, exc)
        return None


def _fetch(url: str, timeout: int = 15) -> str | None:
    response = _request(url, timeout=timeout)
    return response.text if response is not None else None


def _fetch_content(url: str, timeout: int = 15) -> bytes | None:
    response = _request(url, timeout=timeout)
    return response.content if response is not None else None


def _xml_local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _xml_child_text(element: ET.Element, name: str) -> str:
    for child in element:
        if _xml_local_name(child.tag) == name:
            return (child.text or "").strip()
    return ""


def _parse_sitemap_xml(content: bytes, url: str) -> ET.Element:
    try:
        if content.startswith(b"\x1f\x8b"):
            content = gzip.decompress(content)
        return ET.fromstring(content)
    except (OSError, ET.ParseError) as exc:
        raise MappeiSitemapError(f"Invalid Mappei sitemap XML at {url}: {exc}") from exc


def _is_allowed_sitemap_url(url: str) -> bool:
    parsed = urlsplit(url)
    return (
        parsed.scheme in {"http", "https"}
        and parsed.netloc.lower() == "www.mappei.de"
        and parsed.path.startswith("/de/")
    )


def _iter_sitemap_entries(
    sitemap_url: str,
    *,
    visited: set[str] | None = None,
) -> Iterator[tuple[str, str]]:
    visited = visited if visited is not None else set()
    if sitemap_url in visited:
        return
    visited.add(sitemap_url)

    content = _fetch_content(sitemap_url)
    if not content:
        raise MappeiSitemapError(f"Mappei sitemap could not be fetched: {sitemap_url}")

    root = _parse_sitemap_xml(content, sitemap_url)
    root_name = _xml_local_name(root.tag)
    if root_name == "sitemapindex":
        for sitemap in root:
            if _xml_local_name(sitemap.tag) != "sitemap":
                continue
            child_url = _xml_child_text(sitemap, "loc")
            if child_url and _is_allowed_sitemap_url(child_url):
                yield from _iter_sitemap_entries(child_url, visited=visited)
        return

    if root_name != "urlset":
        raise MappeiSitemapError(f"Unexpected Mappei sitemap root at {sitemap_url}: {root_name}")

    for entry in root:
        if _xml_local_name(entry.tag) != "url":
            continue
        loc = _xml_child_text(entry, "loc")
        if loc and _is_allowed_sitemap_url(loc):
            yield loc, _xml_child_text(entry, "changefreq").lower()


def _is_product_sitemap_entry(url: str, changefreq: str) -> bool:
    path = urlsplit(url).path
    if changefreq == "hourly":
        return True
    return not changefreq and bool(PRODUCT_URL_RE.fullmatch(path))


def _product_urls_from_sitemap() -> Iterator[str]:
    """Yield product URLs from Mappei's XML sitemap index."""
    seen: set[str] = set()
    for url, changefreq in _iter_sitemap_entries(SITEMAP_URL):
        if _is_product_sitemap_entry(url, changefreq) and url not in seen:
            seen.add(url)
            yield url
    if not seen:
        raise MappeiSitemapError("Mappei sitemap contained no product URLs.")


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


def _extract_artikelnr(soup, header: str) -> str:
    sku = soup.find(attrs={"itemprop": "sku"})
    if sku:
        value = (sku.get("content") or sku.get_text(strip=True) or "").strip()
        if value:
            return value
    match = RE_ARTIKELNR.search(header)
    return match.group(1).strip() if match else ""


def _extract_structured_staffeln(soup) -> list[dict]:
    staffeln: list[dict] = []
    for row in soup.select(".product-block-prices-row"):
        quantity = row.find("meta", attrs={"itemprop": "priceFromAmount"})
        price = row.find("meta", attrs={"itemprop": "priceNetto"})
        if not quantity or not price:
            continue
        try:
            ab_pakete = int(Decimal(str(quantity.get("content", "")).strip()))
            paketpreis = _parse_decimal(str(price.get("content", "")))
        except (InvalidOperation, ValueError):
            continue
        staffeln.append({"ab_pakete": ab_pakete, "paketpreis": paketpreis})
    return sorted(staffeln, key=lambda item: item["ab_pakete"])


def _parse_product_page(html: str, url: str) -> dict | None:
    """Parse a product page and return a data dict or None on failure."""
    soup = BeautifulSoup(html, "html.parser")
    image_url = _extract_image_url(soup)
    name = _extract_name(soup)
    description = _extract_description(soup)
    text = soup.get_text(separator=" ", strip=True)
    header = _extract_product_header(text)

    # --- Artikelnummer ---
    artikelnr = _extract_artikelnr(soup, header)
    if not artikelnr:
        logger.debug("No artikelnr found at {}", url)
        return None

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

    structured_staffeln = _extract_structured_staffeln(soup)
    if structured_staffeln:
        return _build_staffel_result(
            staffeln=structured_staffeln,
            artikelnr=artikelnr,
            url=url,
            image_url=image_url,
            name=name,
            description=description,
            vpe_menge=vpe_menge,
            vpe_einheit=vpe_einheit,
        )

    # --- Legacy text fallback ---
    has_staffel = bool(
        re.search(r"Anzahl", header, re.IGNORECASE)
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

    return _build_staffel_result(
        staffeln=staffeln,
        artikelnr=artikelnr,
        url=url,
        image_url=image_url,
        name=name,
        description=description,
        vpe_menge=vpe_menge,
        vpe_einheit=vpe_einheit,
    )


def _build_staffel_result(
    *,
    staffeln: list[dict],
    artikelnr: str,
    url: str,
    image_url: str,
    name: str,
    description: str,
    vpe_menge: int | None,
    vpe_einheit: str,
) -> dict:
    """Build normalized snapshot data from package quantities and net prices."""
    staffeln = sorted(staffeln, key=lambda item: item["ab_pakete"])
    has_staffel = len(staffeln) > 1
    partial_success = False

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
    staffelpreis_min = min(paketpreise) if has_staffel else None
    staffelpreis_max = max(paketpreise) if has_staffel else None

    stueck_values = [s["ab_stueck"] for s in staffeln if s["ab_stueck"] is not None]
    staffelpreismenge_min = min(stueck_values) if has_staffel and stueck_values else None
    staffelpreismenge_max = max(stueck_values) if has_staffel and stueck_values else None

    return {
        "artikelnr": artikelnr,
        "url": url,
        "image_url": image_url,
        "name": name,
        "description": description,
        "vpe_menge": vpe_menge,
        "vpe_einheit": vpe_einheit,
        "hat_staffel": has_staffel,
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
