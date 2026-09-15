"""
Scraper for myagrar.de crop protection products.

Step 1: Log in manually in a real browser window (you type your own
        credentials - they never touch this script), so we can read
        your personalized/discounted prices afterward.
Step 2: In that same browser, click through the crop protection listing
        pages (33 pages) to collect every product URL.
Step 3: Fetch each product page in parallel using your logged-in session
        and extract the price for every package size.
Step 4: Save everything to an Excel file on the Desktop.
"""

import os
import tkinter as tk
from tkinter import filedialog, messagebox

import truststore
truststore.inject_into_ssl()

import requests
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed
import pandas as pd
import xml.etree.ElementTree as ET
import json
import re
from urllib.parse import urljoin

def get_desktop_path():
    """Find the real Desktop folder. On many corporate Windows machines,
    OneDrive's "Known Folder Move" redirects Desktop into a OneDrive
    subfolder, so the plain ~/Desktop path doesn't exist - the registry
    always reflects wherever Explorer currently considers Desktop."""
    if os.name == "nt":
        try:
            import winreg
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders",
            ) as key:
                return winreg.QueryValueEx(key, "Desktop")[0]
        except OSError:
            pass
    return os.path.join(os.path.expanduser("~"), "Desktop")


LOGIN_URL = "https://www.myagrar.de/customer/account/login/"
DESKTOP_PATH = os.path.join(get_desktop_path(), "extracted_data.xlsx")
DEBUG = True
MAX_WORKERS = 15
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}


def login_and_get_products():
    """Open a real browser, let the user log in, then click through every
    listing page (crop protection + fertilizer) to collect product links -
    all in the same authenticated browser session."""
    with sync_playwright() as p:
        # Use the Edge browser already installed on Windows instead of a
        # separate bundled Chromium - keeps the packaged .exe far smaller.
        browser = p.chromium.launch(channel="msedge", headless=False)
        context = browser.new_context()
        page = context.new_page()

        print("\nOpening the login page in a browser window...")
        page.goto(LOGIN_URL, timeout=60000)
        print("Please log in with your account in that browser window now.")
        input("Once you're logged in, come back here and press Enter to continue...")

        # Dedup by URL across every listing, in case a product is somehow
        # reachable from more than one category.
        all_products = {}
        for category, listing_url in LISTING_URLS:
            for product in get_product_list(page, listing_url):
                if product["URL"] not in all_products:
                    all_products[product["URL"]] = {**product, "Category": category}
        products = list(all_products.values())

        session = requests.Session()
        session.headers.update(HEADERS)
        for cookie in context.cookies():
            session.cookies.set(
                cookie["name"], cookie["value"],
                domain=cookie.get("domain"), path=cookie.get("path", "/"),
            )
        browser.close()

    return products, session


LISTING_URLS = [
    ("Pflanzenschutz", "https://www.myagrar.de/pflanzenschutzmittel/"),
    ("Dünger", "https://www.myagrar.de/dungemittel/blattdunger/biostimulanzien/"),
    ("Dünger", "https://www.myagrar.de/dungemittel/blattdunger/einzelnahrstoffdunger/"),
    ("Dünger", "https://www.myagrar.de/dungemittel/blattdunger/mehrnahrstoffdunger/"),
    ("Dünger", "https://www.myagrar.de/dungemittel/blattdunger/mikrogranulat/"),
    ("Dünger", "https://www.myagrar.de/dungemittel/blattdunger/mineraldunger/"),
    ("Dünger", "https://www.myagrar.de/dungemittel/blattdunger/wirtschaftsdunger-analytik/"),
    ("Dünger", "https://www.myagrar.de/dungemittel/mineraldunger/kali-dunger/"),
    ("Dünger", "https://www.myagrar.de/dungemittel/mineraldunger/np-dunger/"),
    ("Dünger", "https://www.myagrar.de/dungemittel/mineraldunger/stickstoff-dunger/"),
    ("Dünger", "https://www.myagrar.de/dungemittel/mineraldunger/zubehor/"),
]
# Excludes dungemittel/kulturen/* and dungemittel/nahrstoffe/* - those are
# cross-cutting filter views of the same products above, not distinct ones.


def get_product_list(page, listing_url):
    """
    Click through one listing's pages directly (not the whole-site sitemap -
    that was overkill). The pagination control is a custom widget where the
    "Next" button sometimes shows the word "Weiter" and sometimes just a
    "->" arrow character, so we match on the arrow itself (always present)
    rather than the word.
    """
    print(f"Opening listing page: {listing_url}")
    page.goto(listing_url, timeout=60000)
    page.wait_for_selector("a.product-item-link", timeout=30000)
    page.wait_for_timeout(3000)

    # A fresh browser session often shows a cookie-consent banner or popup
    # on first load. If left open, it can sit on top of the pagination
    # controls and silently block every click. Try to dismiss common ones.
    for text in ["Alle akzeptieren", "Akzeptieren", "Zustimmen", "Accept all", "Accept", "OK", "Schließen", "X"]:
        try:
            btn = page.query_selector(f"button:has-text('{text}')")
            if btn and btn.is_visible():
                print(f"    Dismissing popup via button: '{text}'")
                btn.click()
                page.wait_for_timeout(1000)
                break
        except Exception:
            pass

    all_products = {}
    consecutive_failures = 0
    for page_num in range(1, 40):  # safety cap
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(2000)

        links = page.query_selector_all("a.product-item-link")
        new_count = 0
        for link in links:
            name = link.inner_text().strip()
            url = link.get_attribute("href")
            if url:
                url = url.split("?")[0]
            if url and name and url not in all_products:
                all_products[url] = name
                new_count += 1
        print(f"    Page {page_num}: {len(links)} links visible, {new_count} new, {len(all_products)} total so far")

        # Find the Next button by its arrow character, not by the word
        # "Weiter" (which isn't always present in the DOM).
        next_btn = None
        all_candidates = page.query_selector_all("div.ffw-page-item-container.ffw-cursor")
        # The page renders several duplicate/hidden copies of the pagination
        # bar (responsive layout variants) - only search among the ones
        # actually visible on screen, or we'll grab a hidden clone.
        candidates = [el for el in all_candidates if el.is_visible()]
        if DEBUG and page_num <= 2:
            texts = []
            for el in candidates:
                try:
                    texts.append(repr(el.inner_text().strip()))
                except Exception:
                    texts.append("<error reading text>")
            print(f"    Debug - {len(all_candidates)} total candidates, {len(candidates)} visible: {texts}")
        for el in candidates:
            try:
                text = el.inner_text().strip()
            except Exception:
                continue
            if "\u2192" in text or "→" in text:  # right arrow
                next_btn = el
                break
        if next_btn is None and candidates:
            # Fallback: assume the last candidate in DOM order is "Next"
            next_btn = candidates[-1]

        if not next_btn:
            print("    No Next control found - assuming last page reached.")
            break

        try:
            next_btn.scroll_into_view_if_needed()
            next_btn.click(timeout=5000)
            page.wait_for_timeout(2500)
            consecutive_failures = 0
        except Exception as e:
            consecutive_failures += 1
            print(f"    Click attempt failed ({consecutive_failures}/3): {e}")
            if consecutive_failures >= 3:
                print("    Giving up on pagination after 3 consecutive failures.")
                break
            # Try a plain forced click as a fallback before giving up
            try:
                next_btn.click(force=True, timeout=5000)
                page.wait_for_timeout(2500)
                consecutive_failures = 0
            except Exception as e2:
                print(f"    Forced click also failed: {e2}")
                continue

    products = [{"Name": name, "URL": url} for url, name in all_products.items()]
    print(f"Found {len(products)} unique products on this listing.")
    return products


def _to_float(value):
    s = str(value).strip()
    if not s:
        return None
    if "," in s:
        # German format: comma is the decimal point, period is a thousands separator
        s = s.replace(".", "").replace(",", ".")
    # else: no comma present, so any period here is a genuine decimal point
    # (the site inconsistently uses plain decimals for some package sizes,
    # e.g. "2.5 Stück" instead of "2,5 Stück") - leave it as-is.
    try:
        return float(s)
    except ValueError:
        return None


def extract_balanced_json(text, start_index):
    depth = 0
    in_string = False
    escape = False
    for i in range(start_index, len(text)):
        c = text[i]
        if escape:
            escape = False
            continue
        if c == "\\":
            escape = True
            continue
        if c == '"':
            in_string = not in_string
            continue
        if not in_string:
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    return text[start_index:i + 1]
    return None


def find_sp_config(html):
    key_pos = html.find('"spConfig"')
    if key_pos == -1:
        return None
    brace_pos = html.find("{", key_pos)
    if brace_pos == -1:
        return None
    json_str = extract_balanced_json(html, brace_pos)
    if not json_str:
        return None
    try:
        return json.loads(json_str)
    except json.JSONDecodeError:
        return None


def find_size_attribute(attributes):
    numeric_attrs = []
    for attr in attributes.values():
        options = attr.get("options", [])
        labels = [o.get("label") for o in options]
        if labels and all(_to_float(l) is not None for l in labels):
            numeric_attrs.append(attr)
    for attr in numeric_attrs:
        code = (attr.get("code") or "").lower()
        if "size" in code or "container" in code or "gebinde" in code:
            return attr
    return numeric_attrs[0] if numeric_attrs else None


def get_unit_price_from_label(basepricelabel_html):
    soup = BeautifulSoup(basepricelabel_html or "", "html.parser")
    final_span = soup.find("span", class_=lambda c: c and "base-price-final" in c)
    if not final_span:
        return None, None
    price_el = final_span.find("span", class_="base-price-detail-price")
    unit_el = final_span.find("span", class_="base-price-detail-unit")
    price = None
    if price_el:
        price = _to_float(price_el.get_text(strip=True).replace("\u20ac", "").strip())
    unit = unit_el.get_text(strip=True) if unit_el else None
    return price, unit


def get_unit_from_label(basepricelabel_html):
    """Extract just the unit symbol (e.g. 'l', 'kg') from the label HTML.
    We deliberately do NOT trust the price shown here - see get_all_package_rows
    for why."""
    soup = BeautifulSoup(basepricelabel_html or "", "html.parser")
    final_span = soup.find("span", class_=lambda c: c and "base-price-final" in c)
    if not final_span:
        return None
    unit_el = final_span.find("span", class_="base-price-detail-unit")
    return unit_el.get_text(strip=True) if unit_el else None


def get_all_package_rows(sp_config):
    attributes = sp_config.get("attributes", {})
    option_prices = sp_config.get("optionPrices", {})

    size_attr = find_size_attribute(attributes)
    if size_attr is None:
        return []

    rows = []
    for option in size_attr.get("options", []):
        products = option.get("products", [])
        if not products:
            continue
        product_id = products[0]
        info = option_prices.get(product_id, {})

        total_price = info.get("finalPrice", {}).get("amount")
        total_price = float(total_price) if total_price is not None else None

        # We compute the per-unit price ourselves as total_price / package_size,
        # rather than trusting the site's separate "basepricelabel" text field,
        # which can go stale after a discount is applied.
        size_val = _to_float(option.get("label"))
        unit = get_unit_from_label(info.get("basepricelabel"))
        unit_price = round(total_price / size_val, 2) if (total_price is not None and size_val) else None

        summary_html = info.get("priceSummary", "")
        summary_text = BeautifulSoup(summary_html, "html.parser").get_text().strip()
        match = re.search(r"pro\s+(.+)", summary_text)
        size_desc = match.group(1).strip() if match else (option.get("label") or "")

        rows.append({
            "Package Size": size_desc,
            "Total Price for Packaging Size (EUR)": total_price,
            "Price per Unit (EUR)": unit_price,
            "Unit": unit,
        })

    return rows


def get_simple_package_row(html):
    soup = BeautifulSoup(html, "html.parser")

    summary_p = soup.find("p", class_="base-price-summary-text")
    if summary_p:
        text = summary_p.get_text().strip()
        match = re.search(r"([\d.,]+)\s*€\s*pro\s+([\d.,]+)\s*(.+)", text)
        total_price = None
        size_desc = text
        unit_price = None
        unit = None

        if match:
            total_price = _to_float(match.group(1))
            size_val = _to_float(match.group(2))
            rest = match.group(3).strip()
            size_desc = f"{match.group(2)} {rest}"
            unit = rest.split()[0] if rest else None
            if total_price is not None and size_val:
                unit_price = round(total_price / size_val, 2)

        return [{
            "Package Size": size_desc,
            "Total Price for Packaging Size (EUR)": total_price,
            "Price per Unit (EUR)": unit_price,
            "Unit": unit,
        }]

    if "Anmelden für Ihren persönlichen Preis" in html:
        return [{
            "Package Size": "N/A", "Total Price for Packaging Size (EUR)": "Login required",
            "Price per Unit (EUR)": "Login required", "Unit": "N/A",
        }]

    return []


ATR_DETAILS_URL = "https://www.myagrar.de/rest/V1/atr/configurable-product/get"


def get_detail_product_id(html, sp_config):
    """Find a simple-product id to query the extended-details endpoint with.
    For configurable products (multiple package sizes), any one of the size
    variants works - the regulatory/spec data doesn't change per size. For
    plain single-package products, fall back to the id embedded in the page."""
    if sp_config:
        size_attr = find_size_attribute(sp_config.get("attributes", {}))
        if size_attr:
            for option in size_attr.get("options", []):
                products = option.get("products", [])
                if products:
                    return products[0]
    match = re.search(r'data-product-id="(\d+)"', html)
    return match.group(1) if match else None


def fetch_extended_details_html(session, product_id, retries=1):
    """Fetch the extended product-details HTML fragment (active ingredients,
    cost/hectare, application group, approved cultures, label PDF link).
    This isn't in the page's initial HTML - the site loads it separately via
    this REST endpoint and injects it client-side."""
    if not product_id:
        return ""
    for attempt in range(retries + 1):
        try:
            resp = session.get(ATR_DETAILS_URL, params={"productId": product_id, "storeId": 1}, timeout=30)
            resp.raise_for_status()
            body = resp.json()  # the response is itself a JSON-encoded string
            data = json.loads(body) if isinstance(body, str) else body
            return data.get(".product__details", "") or ""
        except (requests.RequestException, ValueError):
            if attempt < retries:
                continue
            return ""
    return ""


def parse_additional_attributes(details_html):
    """Parse the "Spezifikationen" definition list (dt/dd pairs) out of the
    extended-details HTML fragment into a {label: value} dict."""
    soup = BeautifulSoup(details_html or "", "html.parser")
    attrs = {}
    for dt in soup.select("dl.additional-attributes__list dt"):
        label_el = dt.find("span")
        label = label_el.get_text(strip=True) if label_el else dt.get_text(strip=True)
        dd = dt.find_next_sibling("dd")
        if label and dd:
            attrs[label] = dd.get_text(strip=True)
    return attrs


def parse_culture_usage_rates(details_html):
    """Map each approved culture to its max application rate per hectare
    (the highest across all listed pests/uses for that culture), parsed
    from the "Anwendungshinweise pro zugelassener Kultur und Schaderreger"
    nested details tree."""
    soup = BeautifulSoup(details_html or "", "html.parser")
    h4 = soup.find("h4", string=lambda t: t and "Anwendungshinweise pro zugelassener Kultur" in t)
    wrapper = h4.find_next_sibling("details") if h4 else None
    if not wrapper:
        return {}

    rates = {}
    for culture_details in wrapper.find_all("details", recursive=False):
        h5 = culture_details.find("h5")
        if not h5:
            continue
        # The site sometimes groups several culture names into one entry,
        # e.g. "PORTULAK/GEMÜSE-/SOMMER-" or "FÄRBER-WAU/FÄRBER-RESEDE/
        # GELBKRAUT" - split on "/" so each becomes its own culture, all
        # sharing this block's rate (they're approved together, same table).
        cultures = [c.strip().title() for c in h5.get_text(strip=True).split("/") if c.strip()]
        if not cultures:
            continue
        best_amount, best_unit = None, None
        for row in culture_details.find_all("tr"):
            cells = row.find_all("td")
            if len(cells) != 2:
                continue
            label = cells[0].get_text(strip=True)
            if label.startswith("max. Aufwandsmenge") and "Saison" not in label:
                amount, unit = _parse_rate_amount_and_unit(cells[1].get_text(strip=True))
                if amount is not None and (best_amount is None or amount > best_amount):
                    best_amount, best_unit = amount, unit
        if best_amount is None:
            continue
        for culture in cultures:
            if culture not in rates or best_amount > rates[culture][0]:
                rates[culture] = (best_amount, best_unit)
    return rates


def _parse_rate_amount_and_unit(text):
    match = re.search(r"([\d.,]+)\s*([^\s]+/ha)", text)
    if not match:
        return None, None
    return _to_float(match.group(1)), match.group(2)


def parse_recommended_rate(text):
    """Parse a fertilizer's own recommended-rate text into a total
    per-hectare amount. Handles a plain range ("3-7 l/ha" -> 7, the higher
    end, matching the site's own "bis zu"/up-to convention for cost) and a
    multi-application range ("1-4 x 2,0-3,0 l/ha" -> 4 x 3.0 = 12.0 l/ha),
    so a product applied several times isn't undercounted to one dose."""
    multi = re.search(
        r"([\d.,]+)(?:\s*-\s*([\d.,]+))?\s*x\s*([\d.,]+)(?:\s*-\s*([\d.,]+))?\s*([^\s]+/ha)",
        text, re.IGNORECASE,
    )
    if multi:
        count_lo, count_hi, rate_lo, rate_hi, unit = multi.groups()
        count = _to_float(count_hi or count_lo)
        rate = _to_float(rate_hi or rate_lo)
        if count is not None and rate is not None:
            return round(count * rate, 4), unit

    single = re.search(r"([\d.,]+)(?:\s*-\s*([\d.,]+))?\s*([^\s]+/ha)", text)
    if single:
        lo, hi, unit = single.groups()
        amount = _to_float(hi or lo)
        if amount is not None:
            return amount, unit

    return None, None


def parse_fertilizer_rate(html):
    """Extract a fertilizer's own recommended per-hectare rate from its
    short-description bullet list - Dünger has no per-culture rate table
    like crop protection does, so this is the closest available source for
    a Cost per Hectare estimate."""
    soup = BeautifulSoup(html or "", "html.parser")
    container = soup.find("div", class_="product__short-description")
    if not container:
        return None, None
    for li in container.find_all("li"):
        text = li.get_text(strip=True)
        if "aufwandmenge" in text.lower():
            return parse_recommended_rate(text)
    return None, None


def compute_culture_cost(rate_amount, rate_unit, price_per_unit, unit):
    """Cost per hectare for one culture's application rate, using this
    package's own price-per-unit. None when the rate's unit (e.g. l/ha)
    doesn't match the package's price unit (e.g. kg) - can't compute a
    sane number then."""
    if not isinstance(price_per_unit, (int, float)) or not unit or not rate_unit:
        return None
    if rate_unit.split("/")[0].lower() != unit.lower():
        return None
    return round(price_per_unit * rate_amount, 2)


def max_matching_rate(rates, unit):
    """Highest rate among `rates` (a {name: (amount, rate_unit)} dict)
    whose unit matches `unit` (e.g. rate_unit "l/ha" matches unit "l") -
    filtering before taking the max so a mismatched-unit rate on one
    culture can't shadow a valid same-unit rate on another."""
    matching = [
        (amount, rate_unit) for amount, rate_unit in rates.values()
        if rate_unit and unit and rate_unit.split("/")[0].lower() == unit.lower()
    ]
    return max(matching, key=lambda r: r[0]) if matching else (None, None)


def resolve_cost_per_hectare(product, row):
    """The site's own Kosten per Hektar text when it has one. Otherwise
    compute our own estimate: from the highest matching-unit rate among the
    product's approved cultures when we have per-culture rate data (some
    crop protection products, like Karate Zeon, simply don't get a site
    figure despite having full rate data) - or from the product's own
    recommended-rate text when there's no per-culture table at all (common
    for Dünger). Marked "(berechnet)" so it's clearly not a site figure."""
    if product["cost_per_hectare"] is not None:
        return product["cost_per_hectare"]

    rate_amount, rate_unit = max_matching_rate(product["culture_rates"], row["Unit"])
    if rate_amount is None:
        rate_amount, rate_unit = product["fertilizer_rate"]

    cost = compute_culture_cost(rate_amount, rate_unit, row["Price per Unit (EUR)"], row["Unit"])
    return f"{cost:.2f} €/ha (berechnet)" if cost is not None else None


def get_culture_entries(product):
    """List of (culture_name, rate_amount, rate_unit) to emit one row per
    culture. Falls back to splitting the plain comma-separated culture list
    (no per-hectare rate available then - common for Dünger, which has no
    per-culture rate table) when there's no rate table at all."""
    if product["culture_rates"]:
        return [(name, amount, unit) for name, (amount, unit) in product["culture_rates"].items()]
    if product["approved_cultures"]:
        return [(name.strip(), None, None) for name in product["approved_cultures"].split(",") if name.strip()]
    return [(None, None, None)]


def find_label_pdf_url(details_html):
    """Find the link to the product label / instructions-for-use PDF, which
    the site gives in German ("Gebrauchsanweisung...") or English
    ("Instructions for use...") depending on the product - never the
    separate safety-data-sheet ("Sicherheitsdatenblatt") PDF also listed."""
    soup = BeautifulSoup(details_html or "", "html.parser")
    for a in soup.find_all("a", class_="action", href=True):
        text = a.get_text(strip=True)
        if text.startswith("Gebrauchsanweisung") or text.startswith("Instructions for use"):
            return urljoin("https://www.myagrar.de/", a["href"])
    return None


def process_product_url(product, session, retries=2):
    """Fetch one product page (already confirmed to be crop protection) and extract pricing."""
    html = None
    for attempt in range(retries + 1):
        try:
            resp = session.get(product["URL"], timeout=30)
            resp.raise_for_status()
            html = resp.text
            break
        except requests.RequestException as e:
            if attempt < retries:
                continue  # try again
            print(f"  Error fetching {product['Name']} after {retries + 1} attempts: {e}")
            return None

    sp_config = find_sp_config(html)
    rows = []
    if sp_config:
        rows = get_all_package_rows(sp_config)
    if not rows:
        rows = get_simple_package_row(html)
    if not rows:
        return None

    # Configurable products (multiple package sizes) get their spec block
    # via a separate AJAX call - but simple/single-package products (common
    # for Dünger) embed it directly in the page instead, and never get a
    # usable id for that AJAX call. Parse both and let the AJAX fragment
    # (more complete, when it exists) win on overlapping fields.
    detail_product_id = get_detail_product_id(html, sp_config)
    details_html = fetch_extended_details_html(session, detail_product_id)
    extra = {**parse_additional_attributes(html), **parse_additional_attributes(details_html)}
    culture_rates = parse_culture_usage_rates(details_html) or parse_culture_usage_rates(html)
    label_pdf_url = find_label_pdf_url(details_html) or find_label_pdf_url(html)

    return {
        "name": product["Name"],
        "url": product["URL"],
        "category": product["Category"],
        "rows": rows,
        "cost_per_hectare": extra.get("Kosten per Hektar"),
        # Fallback for products with no site-provided Kosten per Hektar
        # (Dünger doesn't have one) - a rate we compute cost/ha from
        # ourselves, using each package's own price (see scrape()).
        "fertilizer_rate": parse_fertilizer_rate(html),
        "application_group": extra.get("Anwendungsgruppe"),
        # "Wirkstoffe" (active ingredient) on crop protection products,
        # "Inhaltsstoffe" (ingredients) is the fertilizer equivalent.
        "active_ingredients": extra.get("Wirkstoffe") or extra.get("Inhaltsstoffe"),
        # Fallback for products with no per-culture rate table (common for
        # Dünger) - used only when culture_rates is empty (see scrape()).
        "approved_cultures": extra.get("Zugelassene Kulturen"),
        "culture_rates": culture_rates,
        "label_pdf_url": label_pdf_url,
        "label_holder": extra.get("Hersteller"),
    }


def scrape():
    products, session = login_and_get_products()

    print(f"\nFetching prices for {len(products)} products...")
    results = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(process_product_url, product, session): product for product in products}
        completed = 0
        for future in as_completed(futures):
            completed += 1
            if completed % 25 == 0:
                print(f"  ...processed {completed}/{len(products)}")
            product = future.result()
            if product:
                if DEBUG:
                    print(f"  {product['name']}: {len(product['rows'])} size(s)")
                for row in product["rows"]:
                    base = {
                        "Category": product["category"],
                        "Name": product["name"],
                        "Package Size": row["Package Size"],
                        "Total Price for Packaging Size (EUR)": row["Total Price for Packaging Size (EUR)"],
                        "Price per Unit (EUR)": row["Price per Unit (EUR)"],
                        "Unit": row["Unit"],
                        "Cost per Hectare": resolve_cost_per_hectare(product, row),
                        "Application Group": product["application_group"],
                        "Active Ingredients": product["active_ingredients"],
                    }
                    tail = {
                        "Label Holder": product["label_holder"],
                        "Label PDF": product["label_pdf_url"],
                        "URL": product["url"],
                    }
                    # One row per approved culture, so each row/cell holds
                    # exactly one culture - lets a plain Excel filter isolate
                    # a single culture cleanly, instead of everything sharing
                    # one product's combined culture list.
                    for culture, rate_amount, rate_unit in get_culture_entries(product):
                        results.append({
                            **base,
                            "Approved Culture": culture,
                            "Cost per Hectare (Culture)": compute_culture_cost(
                                rate_amount, rate_unit, row["Price per Unit (EUR)"], row["Unit"]
                            ),
                            **tail,
                        })

    print(f"\nDone. Found {len(results)} rows across all products.")
    return results


PRICE_COLUMN_NAMES = ["Total Price for Packaging Size (EUR)", "Total Price (EUR)"]


def _get_price_from_row(row):
    """Read the total price from a row, trying the current column name
    first and falling back to older names - so comparisons still work
    even against files saved by an earlier version of this script."""
    for col in PRICE_COLUMN_NAMES:
        if col in row and pd.notna(row[col]):
            val = row[col]
            if isinstance(val, (int, float)):
                return float(val)
    return None


def get_best_per_unit_prices(df):
    """For each product (grouped by URL, since multi-size products share
    one URL), find the size with the best (lowest) per-unit price."""
    best = {}
    for url, group in df.groupby("URL"):
        prices = pd.to_numeric(group["Price per Unit (EUR)"], errors="coerce")
        valid = group[prices.notna()]
        if valid.empty:
            continue
        idx = pd.to_numeric(valid["Price per Unit (EUR)"]).idxmin()
        row = valid.loc[idx]
        best[url] = {
            "Name": row["Name"],
            "Best Package Size": row["Package Size"],
            "Best Price per Unit (EUR)": float(row["Price per Unit (EUR)"]),
            "Unit": row.get("Unit"),
        }
    return best


def build_comparison_rows(current_df, previous_df):
    """One row per product, comparing only the best (lowest) per-unit
    price between the previous run and this run."""
    current_best = get_best_per_unit_prices(current_df)
    previous_best = get_best_per_unit_prices(previous_df)

    rows = []
    for url, curr in current_best.items():
        prev = previous_best.get(url)
        curr_price = curr["Best Price per Unit (EUR)"]

        if prev is None:
            rows.append({
                "Name": curr["Name"],
                "Package Size": curr["Best Package Size"],
                "Previous Price per Unit (EUR)": None,
                "Current Price per Unit (EUR)": curr_price,
                "Change (EUR)": None, "Change (%)": None, "Status": "New product",
                "URL": url,
            })
        else:
            prev_price = prev["Best Price per Unit (EUR)"]
            change_eur = round(curr_price - prev_price, 2)
            change_pct = round((curr_price - prev_price) / prev_price * 100, 1) if prev_price else 0.0
            if abs(change_eur) <= 0.001:
                status, change_eur, change_pct = "No change", 0.0, 0.0
            else:
                status = "Increased" if change_eur > 0 else "Decreased"

            rows.append({
                "Name": curr["Name"],
                "Package Size": curr["Best Package Size"],
                "Previous Price per Unit (EUR)": prev_price,
                "Current Price per Unit (EUR)": curr_price,
                "Change (EUR)": change_eur, "Change (%)": change_pct, "Status": status,
                "URL": url,
            })

    # URL is included for reliable joining elsewhere - two different
    # products can share the same display Name (confirmed on real data:
    # two "Agrotop Messzylinder" SKUs), so Name alone isn't a safe join
    # key in general, even though the Product Groups sheet is asked to
    # join by Name anyway (its source file has no URL/SKU to join on).
    columns = ["Name", "Package Size", "Previous Price per Unit (EUR)",
               "Current Price per Unit (EUR)", "Change (EUR)", "Change (%)", "Status", "URL"]
    return pd.DataFrame(rows, columns=columns)


def highlight_best_prices(filename, sheet_name="Current Run"):
    """For products sold in multiple package sizes, highlight the size
    with the best (lowest) per-unit price in green."""
    from openpyxl import load_workbook
    from openpyxl.styles import PatternFill
    from collections import defaultdict

    wb = load_workbook(filename)
    if sheet_name not in wb.sheetnames:
        return
    ws = wb[sheet_name]

    headers = [cell.value for cell in ws[1]]
    if "Name" not in headers or "Price per Unit (EUR)" not in headers:
        return
    name_col = headers.index("Name") + 1
    price_col = headers.index("Price per Unit (EUR)") + 1

    groups = defaultdict(list)
    for row_idx in range(2, ws.max_row + 1):
        name = ws.cell(row=row_idx, column=name_col).value
        price = ws.cell(row=row_idx, column=price_col).value
        if isinstance(price, (int, float)):
            groups[name].append((row_idx, price))

    fill = PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid")
    highlighted = 0
    for name, rows in groups.items():
        if len(rows) < 2:
            continue  # only one size available - nothing to compare
        best_row = min(rows, key=lambda x: x[1])[0]
        for col in range(1, len(headers) + 1):
            ws.cell(row=best_row, column=col).fill = fill
        highlighted += 1

    wb.save(filename)
    print(f"Highlighted best per-unit price for {highlighted} multi-size product(s).")


def get_additional_documents_path():
    """Ask via a popup whether the user has an additional classification
    spreadsheet (Name, Active Ingredients, Segment, Sub-segment) to build
    the Product Groups summary sheet from. Returns the chosen file path,
    or None if there isn't one / the dialog is cancelled."""
    root = tk.Tk()
    root.withdraw()  # only the dialogs below should show, not an empty window
    has_docs = messagebox.askyesno(
        "Additional documents?",
        "Do you have an additional Excel file with product classifications\n"
        "(Name, Active Ingredients, Segment, Sub-segment) to include?",
    )
    path = None
    if has_docs:
        path = filedialog.askopenfilename(
            title="Select your additional Excel file",
            filetypes=[("Excel files", "*.xlsx *.xls")],
        )
    root.destroy()
    return path or None


def load_product_groups(path):
    """Read the additional classification file into a
    {product_name: (product_group, segment)} lookup - Product Group from
    that file's own Segment column (e.g. "Spring Herbizid"), Segment from
    its Sub-segment column. Column names are matched loosely - case,
    spaces, hyphens and underscores are all ignored (so "Sub-Segment",
    "sub segment", "SubSegment" and "sub_segment" all match the same
    column), since we don't control how the file's headers are typed.
    Searches every sheet for one with a "Name" column, rather than just
    the first - the reference files put the actual data in a sheet
    called "lookup", with other sheets (a demo pivot, etc.) before or
    after it."""
    if not path:
        return {}
    try:
        sheets = pd.read_excel(path, sheet_name=None)
    except Exception as e:
        print(f"  Could not read additional document: {e}")
        return {}

    def normalize(text):
        return re.sub(r"[\s\-_]+", "", str(text).strip().lower())

    def find_column(df, name):
        target = normalize(name)
        for col in df.columns:
            if normalize(col) == target:
                return col
        return None

    for sheet_name, df in sheets.items():
        name_col = find_column(df, "Name")
        if not name_col:
            continue
        segment_col = find_column(df, "Segment")
        subsegment_col = find_column(df, "Sub-segment")

        lookup = {}
        for _, row in df.iterrows():
            name = str(row[name_col]).strip()
            if not name or name.lower() == "nan":
                continue
            lookup[name] = (
                row[segment_col] if segment_col is not None else None,
                row[subsegment_col] if subsegment_col is not None else None,
            )
        print(f"  Loaded {len(lookup)} product classifications from sheet '{sheet_name}'.")
        return lookup

    print("  Additional document has no sheet with a 'Name' column - can't match products, skipping.")
    return {}


def build_product_group_sheet(product_groups, comparison_df):
    """Herbicide price-change pivot, 3 columns matching the reference
    pivot the user built by hand ("Tabelle2": Prd group | Segment |
    Change %, and the original Pivot sheet: PrdGroup | Segment | Summe
    von Change (%)):

      - one row per PrdGroup + Segment combination (products in a
        bucket are aggregated, not listed individually)
      - value is the sum of Change (%) across that bucket's products -
        the price change is computed from the scraped website data
        (see build_comparison_rows); PrdGroup and Segment come from the
        user-provided classification file (its own Segment and
        Sub-segment columns respectively)
      - Excel "compact form": the outer PrdGroup label is shown once
        per group, blank on its following Segment rows
      - a subtotal row per PrdGroup ("<PrdGroup> Ergebnis") and a grand
        total ("Gesamtergebnis") at the bottom
      - blank PrdGroup / Segment values show as "(Leer)"

    Products are matched to their price change by Name - the only key
    the classification file provides. The two leading blank rows Excel
    leaves above a pivot are added when the sheet is written, not here.

    Built as plain computed data, not a real pivot table object - Python
    can't reliably create those from scratch, and the file is rebuilt
    fresh every run anyway."""
    columns = ["PrdGroup", "Segment", "Summe von Change (%)"]
    if not product_groups:
        return pd.DataFrame(columns=columns)

    change_by_name = dict(zip(comparison_df["Name"], comparison_df["Change (%)"]))

    def clean(value):
        return str(value).strip() if pd.notna(value) and str(value).strip() else "(Leer)"

    detail = pd.DataFrame([{
        "PrdGroup": clean(prd_group),
        "Segment": clean(segment),
        "Change (%)": change_by_name.get(name) or 0.0,
    } for name, (prd_group, segment) in product_groups.items()])

    bucket_sums = (
        detail.groupby(["PrdGroup", "Segment"])["Change (%)"].sum()
        .round(2).reset_index().sort_values(["PrdGroup", "Segment"])
    )

    rows = []
    grand_total = 0.0
    for prd_group, group_df in bucket_sums.groupby("PrdGroup", sort=False):
        group_total = 0.0
        first = True
        for _, r in group_df.iterrows():
            value = r["Change (%)"]
            group_total += value
            rows.append({
                "PrdGroup": prd_group if first else "",
                "Segment": r["Segment"],
                "Summe von Change (%)": round(value, 2),
            })
            first = False
        rows.append({
            "PrdGroup": f"{prd_group} Ergebnis", "Segment": "",
            "Summe von Change (%)": round(group_total, 2),
        })
        grand_total += group_total

    rows.append({
        "PrdGroup": "Gesamtergebnis", "Segment": "",
        "Summe von Change (%)": round(grand_total, 2),
    })

    return pd.DataFrame(rows, columns=columns)


def style_worksheet(filename):
    """Post-save formatting: a visible % sign on Comparison's and Pivot's
    Change columns (still numeric/sortable underneath), and a clean,
    readable layout for the Pivot summary sheet - bold header, frozen
    header row, sane column widths, and bolded subtotal/grand-total rows
    (matching how Excel itself renders a real pivot's Ergebnis/
    Gesamtergebnis rows)."""
    from openpyxl import load_workbook
    from openpyxl.styles import Font, PatternFill

    wb = load_workbook(filename)

    def format_percent_column(ws):
        headers = [cell.value for cell in ws[1]]
        matches = [h for h in headers if h and "Change (%)" in str(h)]
        if not matches:
            return
        col = headers.index(matches[0]) + 1
        for row_idx in range(2, ws.max_row + 1):
            cell = ws.cell(row=row_idx, column=col)
            if isinstance(cell.value, (int, float)):
                cell.number_format = '0.0"%"'

    if "Comparison" in wb.sheetnames:
        format_percent_column(wb["Comparison"])

    if "Pivot" in wb.sheetnames:
        ws = wb["Pivot"]

        # The Pivot sheet has two blank spacer rows above its header
        # (matching how Excel places a real pivot) - find the header row
        # rather than assuming row 1.
        header_row = next(
            (r for r in range(1, ws.max_row + 1) if ws.cell(row=r, column=1).value == "PrdGroup"),
            1,
        )

        headers = [ws.cell(row=header_row, column=c).value for c in range(1, ws.max_column + 1)]
        value_col = next((i + 1 for i, h in enumerate(headers) if h and "Change (%)" in str(h)), None)
        if value_col:
            for row_idx in range(header_row + 1, ws.max_row + 1):
                cell = ws.cell(row=row_idx, column=value_col)
                if isinstance(cell.value, (int, float)):
                    cell.number_format = '0.0"%"'

        header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
        header_font = Font(bold=True, color="FFFFFF")
        for cell in ws[header_row]:
            cell.fill = header_fill
            cell.font = header_font
        ws.freeze_panes = f"A{header_row + 1}"

        # Bold the subtotal ("X Ergebnis") and grand-total ("Gesamtergebnis")
        # rows, same as Excel does for a real pivot's summary rows.
        for row_idx in range(header_row + 1, ws.max_row + 1):
            label = ws.cell(row=row_idx, column=1).value
            if label and "ergebnis" in str(label).lower():
                for cell in ws[row_idx]:
                    cell.font = Font(bold=True)

        # Column widths sized to their content.
        for col_idx in range(1, ws.max_column + 1):
            letter = ws.cell(row=header_row, column=col_idx).column_letter
            max_len = max(
                (len(str(ws.cell(row=r, column=col_idx).value))
                 for r in range(header_row, ws.max_row + 1)
                 if ws.cell(row=r, column=col_idx).value is not None),
                default=10,
            )
            ws.column_dimensions[letter].width = min(max_len + 2, 45)

    wb.save(filename)


def save_to_excel(data, product_groups, filename=DESKTOP_PATH):
    if not data:
        print("No data extracted - Excel file not created.")
        return

    current_df = pd.DataFrame(data)

    # Read the previous run's "Current Run" sheet (if the file exists)
    # before we overwrite it - it becomes this run's "Previous Run" sheet.
    previous_df = None
    if os.path.exists(filename):
        try:
            previous_df = pd.read_excel(filename, sheet_name="Current Run")
        except Exception:
            try:
                previous_df = pd.read_excel(filename)  # older single-sheet file
            except Exception as e:
                print(f"  Could not read previous file for comparison: {e}")

    if previous_df is not None:
        comparison_df = build_comparison_rows(current_df, previous_df)
        print(f"\nComparison to previous run: {len(comparison_df)} price(s) changed or new.")
    else:
        comparison_df = pd.DataFrame(columns=["Name", "Package Size", "Previous Price (EUR)",
                                               "Current Price (EUR)", "Change (EUR)", "Change (%)", "Status", "URL"])
        print("\nNo previous file found - this run becomes the baseline for future comparisons.")

    product_group_df = build_product_group_sheet(product_groups, comparison_df)

    with pd.ExcelWriter(filename, engine="openpyxl") as writer:
        current_df.to_excel(writer, sheet_name="Current Run", index=False)
        if previous_df is not None:
            previous_df.to_excel(writer, sheet_name="Previous Run", index=False)
        comparison_df.to_excel(writer, sheet_name="Comparison", index=False)
        # Two blank spacer rows above the header, the way Excel places a
        # real pivot on its sheet.
        product_group_df.to_excel(writer, sheet_name="Pivot", index=False, startrow=2)

    highlight_best_prices(filename, "Current Run")
    style_worksheet(filename)

    print(f"Success! Saved {len(data)} rows to {filename} ({len(product_group_df)} product group entries)")


if __name__ == "__main__":
    print("=" * 50)
    print("  MyAgrar Crop Protection Price Extractor")
    print("=" * 50)
    try:
        product_groups = load_product_groups(get_additional_documents_path())
        data = scrape()
        save_to_excel(data, product_groups)
        print(f"\nAll done! Open the file here:\n{DESKTOP_PATH}")
    except Exception as e:
        print(f"\nSomething went wrong: {e}")
        print("Please share this message so it can be fixed.")
    input("\nPress Enter to close this window...")
