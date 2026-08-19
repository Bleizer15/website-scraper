"""
Shopware 6 price extraction.

Companion to the Magento path in scraper.py. Same idea, different markup:
scraper.py reads Magento's `spConfig` JSON and `base-price` spans; this reads
Shopware 6's default Storefront classes.

Returns the SAME row shape as scraper.get_all_package_rows(), so the Excel
writer, the run-over-run comparison and the best-price-per-unit highlighting
all work unchanged:

    {"Package Size", "Total Price for Packaging Size (EUR)",
     "Price per Unit (EUR)", "Unit"}

Markup this targets (verified live against a real Shopware 6 B2B shop,
2026-08-13):

    div.product-detail-price-container
      p.product-detail-price                 1.100,83 €*      <- what you pay
      span.list-price-price                  1.354,00 €*      <- struck-through list
      span.list-price-percentage             (18.7% gespart)
    div.product-detail-price-unit
      span.price-unit-label                  Inhalt:
    div.product-block-prices                 quantity tiers (B2B staffelpreise)

Why the customer price matters more here than on Magento: Shopware shows the
list price and the customer price side by side once logged in, so the discount
is directly visible. That difference IS the product.
"""

import re

from bs4 import BeautifulSoup


def _to_float(value):
    """German number format: comma is the decimal point, period groups thousands.
    Shared behaviour with scraper._to_float so both paths agree."""
    if value is None:
        return None
    s = re.sub(r"[^\d,.\-]", "", str(value)).strip()
    if not s:
        return None
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def _text(node):
    return node.get_text(" ", strip=True) if node else None


def _first_price(value):
    """Take the FIRST price-shaped number out of a string.

    Necessary because Shopware nests the struck-through list price and the
    saved-percentage inside the same .product-price element, e.g.

        "269,70 €* statt 314,65 €* (14.29% gespart)"

    Stripping non-digits and parsing the remainder would concatenate all three
    numbers into nonsense. The customer's actual price is always rendered
    first, so take that."""
    if value is None:
        return None
    m = re.search(r"\d{1,3}(?:\.\d{3})*,\d{2}|\d+,\d{2}|\d+\.\d{2}|\d+", str(value))
    return _to_float(m.group(0)) if m else None


def parse_unit_content(soup):
    """Shopware shows package content as 'Inhalt: 500 ml' (or '1 Stk').
    Returns (amount, unit), e.g. (500.0, 'ml'). Either may be None."""
    unit_block = soup.select_one(".product-detail-price-unit, .product-unit")
    if not unit_block:
        return None, None
    txt = _text(unit_block) or ""
    # e.g. "Inhalt: 500 ml"  /  "Inhalt: 1 Stück"  /  "Inhalt: 2,5 l"
    m = re.search(r"([\d.,]+)\s*([A-Za-zÄÖÜäöüß]+)", txt)
    if not m:
        return None, None
    return _to_float(m.group(1)), m.group(2)


def parse_tier_prices(soup):
    """Shopware block prices = B2B quantity tiers ('ab 10 Stück: 9,90 €').
    These matter: the headline price is often not the price actually paid."""
    tiers = []
    table = soup.select_one(".product-block-prices, .product-block-prices-grid")
    if not table:
        return tiers
    for row in table.select("tr, .product-block-prices-row"):
        cells = [_text(c) for c in row.select("td, .product-block-prices-cell")]
        cells = [c for c in cells if c]
        if len(cells) < 2:
            continue
        qty = re.search(r"(\d+)", cells[0])
        price = _to_float(cells[-1])
        if qty and price is not None:
            tiers.append({"min_qty": int(qty.group(1)), "price": price})
    return tiers


def parse_variants(soup):
    """Configurator options (size/colour). Each variant lives on its own URL in
    Shopware, so the caller fetches them separately -- we just return links."""
    urls = []
    for a in soup.select(".product-detail-configurator-option-label[href], "
                         ".product-detail-configurator a[href]"):
        href = a.get("href")
        if href and href not in urls:
            urls.append(href)
    return urls


def extract_shopware_product(html, url=None):
    """Parse one Shopware 6 product page.

    Returns {"name", "sku", "url", "rows", "list_price", "discount_pct",
             "tiers", "variant_urls"} or None if no price is on the page
    (which usually means prices are gated and the session is not logged in --
    an important signal, not an error)."""
    soup = BeautifulSoup(html, "html.parser")

    name = _text(soup.select_one(".product-detail-name, h1.product-detail-name"))
    sku = _text(soup.select_one(".product-detail-ordernumber, "
                                "[itemprop='sku'], .product-detail-ordernumber-container"))
    if sku:
        # Shops render "Produktnummer: 0012761" / "Artikelnummer: ..." -- keep the value only.
        sku = re.sub(r"^\s*(Produkt|Artikel|Bestell)?nummer\s*:?\s*", "", sku, flags=re.I).strip()

    price_el = soup.select_one(".product-detail-price, .product-price")
    price = _first_price(_text(price_el))

    list_price = _first_price(_text(soup.select_one(".list-price-price")))
    pct_txt = _text(soup.select_one(".list-price-percentage"))
    discount_pct = _to_float(re.sub(r"[^\d.,]", "", pct_txt)) if pct_txt else None
    # Recompute rather than trusting the rendered percentage -- same reasoning
    # as scraper.py computing per-unit price instead of reading basepricelabel.
    if list_price and price and list_price > 0:
        discount_pct = round((list_price - price) / list_price * 100, 1)

    if price is None:
        return None  # gated or out of stock -- caller decides what that means

    amount, unit = parse_unit_content(soup)
    unit_price = round(price / amount, 4) if (amount and amount > 0) else None

    rows = [{
        "Package Size": f"{amount:g} {unit}" if amount and unit else (unit or "1 Stk"),
        "Total Price for Packaging Size (EUR)": price,
        "Price per Unit (EUR)": unit_price,
        "Unit": unit,
    }]

    return {
        "name": name,
        "sku": sku,
        "url": url,
        "rows": rows,
        "list_price": list_price,
        "discount_pct": discount_pct,
        "tiers": parse_tier_prices(soup),
        "variant_urls": parse_variants(soup),
    }


def extract_shopware_listing(html, base_url=None):
    """Parse a Shopware 6 CATEGORY/LISTING page.

    Far cheaper than fetching every product: one request yields name, link,
    price, list price and unit for a whole page of products. Verified against
    a live Shopware 6 B2B shop whose theme puts prices on listing cards
    (.product-price / .list-price-price) rather than on detail pages.

    Themes vary, so both this and extract_shopware_product() are needed --
    try listing first, fall back to detail pages when it yields nothing.
    """
    soup = BeautifulSoup(html, "html.parser")
    rows = []

    # Selectors in fallback order, NOT combined: .cms-listing-col wraps
    # .product-box, so a comma-list matches every product twice.
    cards = (soup.select(".product-box")
             or soup.select(".cms-listing-col")
             or soup.select(".card"))
    for card in cards:
        link = card.select_one("a.product-name[href], .product-name a[href], a[href]")
        href = link.get("href") if link else None
        name = _text(card.select_one(".product-name, .product-box .product-name")) \
            or (_text(link) if link else None)

        # Try selectors in priority order and take the first that actually
        # yields a number. select_one() with a comma-list returns whichever
        # matches first in DOCUMENT order, which on some themes is an empty
        # .product-cheapest-price wrapper -- that silently swallowed every row.
        price = None
        for sel in (".product-price", ".product-cheapest-price", ".product-detail-price"):
            price = _first_price(_text(card.select_one(sel)))
            if price is not None:
                break
        if price is None:
            continue  # gated, or not a product card

        list_price = _first_price(_text(card.select_one(".list-price-price")))
        unit_txt = _text(card.select_one(".product-price-unit"))
        amount = unit = None
        if unit_txt:
            m = re.search(r"([\d.,]+)\s*([A-Za-zÄÖÜäöüß]+)", unit_txt)
            if m:
                amount, unit = _to_float(m.group(1)), m.group(2)

        discount_pct = None
        if list_price and list_price > 0:
            discount_pct = round((list_price - price) / list_price * 100, 1)

        rows.append({
            "Name": name,
            "URL": href,
            "Package Size": f"{amount:g} {unit}" if amount and unit else (unit or ""),
            "Total Price for Packaging Size (EUR)": price,
            "Price per Unit (EUR)": round(price / amount, 4) if amount else None,
            "Unit": unit,
            "List Price (EUR)": list_price,
            "Discount (%)": discount_pct,
        })

    return rows


def is_price_gated(html):
    """True when the page is clearly hiding prices behind a login. Used to tell
    'not logged in' apart from 'genuinely has no price'."""
    low = html.lower()
    phrases = [
        "preise nach anmeldung", "preis nach anmeldung",
        "nach dem login", "bitte anmelden", "nur für angemeldete",
        "zum händlerpreis anmelden", "login for price", "log in to see",
    ]
    if any(p in low for p in phrases):
        return True
    return "product-detail-price" not in low and "product-detail-buy" in low


if __name__ == "__main__":
    import sys
    import requests

    H = {"User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 Chrome/120.0 Safari/537.36"),
         "Accept-Language": "de-DE,de;q=0.9"}
    for u in sys.argv[1:]:
        html = requests.get(u, headers=H, timeout=30).text
        res = extract_shopware_product(html, u)
        print("\n" + "=" * 70)
        print(u)
        if res is None:
            print("  no price found | gated:", is_price_gated(html))
            continue
        print(f"  name        {res['name']}")
        print(f"  sku         {res['sku']}")
        print(f"  price       {res['rows'][0]['Total Price for Packaging Size (EUR)']}")
        print(f"  list price  {res['list_price']}   discount {res['discount_pct']}%")
        print(f"  package     {res['rows'][0]['Package Size']}")
        print(f"  per unit    {res['rows'][0]['Price per Unit (EUR)']} / {res['rows'][0]['Unit']}")
        print(f"  tiers       {res['tiers']}")
        print(f"  variants    {len(res['variant_urls'])}")
