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

    detail_product_id = get_detail_product_id(html, sp_config)
    details_html = fetch_extended_details_html(session, detail_product_id)
    extra = parse_additional_attributes(details_html)
    culture_rates = parse_culture_usage_rates(details_html)

    return {
        "name": product["Name"],
        "url": product["URL"],
        "category": product["Category"],
        "rows": rows,
        "cost_per_hectare": extra.get("Kosten per Hektar"),
        "application_group": extra.get("Anwendungsgruppe"),
        "active_ingredients": extra.get("Wirkstoffe"),
        # Fallback for the rare product with no per-culture rate table -
        # used only when culture_rates is empty (see scrape()).
        "approved_cultures": extra.get("Zugelassene Kulturen"),
        "culture_rates": culture_rates,
        "label_pdf_url": find_label_pdf_url(details_html),
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
                        "Cost per Hectare": product["cost_per_hectare"],
                        "Application Group": product["application_group"],
                        "Active Ingredients": product["active_ingredients"],
                    }
                    tail = {"Label PDF": product["label_pdf_url"], "URL": product["url"]}
                    # One row per approved culture, so each row/cell holds
                    # exactly one culture - lets a plain Excel filter isolate
                    # a single culture cleanly, instead of everything sharing
                    # one product's combined culture list.
                    if product["culture_rates"]:
                        for culture, (rate_amount, rate_unit) in product["culture_rates"].items():
                            results.append({
                                **base,
                                "Approved Culture": culture,
                                "Cost per Hectare (Culture)": compute_culture_cost(
                                    rate_amount, rate_unit, row["Price per Unit (EUR)"], row["Unit"]
                                ),
                                **tail,
                            })
                    else:
                        results.append({
                            **base,
                            "Approved Culture": product["approved_cultures"],
                            "Cost per Hectare (Culture)": None,
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
            })

    columns = ["Name", "Package Size", "Previous Price per Unit (EUR)",
               "Current Price per Unit (EUR)", "Change (EUR)", "Change (%)", "Status"]
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


def style_worksheet(filename):
    """Format the comparison sheet's Change (%) column with a visible %
    sign while keeping the underlying value numeric/sortable."""
    from openpyxl import load_workbook

    wb = load_workbook(filename)

    if "Comparison" in wb.sheetnames:
        ws = wb["Comparison"]
        headers = [cell.value for cell in ws[1]]
        if "Change (%)" in headers:
            col = headers.index("Change (%)") + 1
            for row_idx in range(2, ws.max_row + 1):
                cell = ws.cell(row=row_idx, column=col)
                if isinstance(cell.value, (int, float)):
                    cell.number_format = '0.0"%"'

    wb.save(filename)


def save_to_excel(data, filename=DESKTOP_PATH):
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
                                               "Current Price (EUR)", "Change (EUR)", "Change (%)", "Status"])
        print("\nNo previous file found - this run becomes the baseline for future comparisons.")

    with pd.ExcelWriter(filename, engine="openpyxl") as writer:
        current_df.to_excel(writer, sheet_name="Current Run", index=False)
        if previous_df is not None:
            previous_df.to_excel(writer, sheet_name="Previous Run", index=False)
        comparison_df.to_excel(writer, sheet_name="Comparison", index=False)

    highlight_best_prices(filename, "Current Run")
    style_worksheet(filename)

    print(f"Success! Saved {len(data)} rows to {filename}")


if __name__ == "__main__":
    print("=" * 50)
    print("  MyAgrar Crop Protection Price Extractor")
    print("=" * 50)
    try:
        data = scrape()
        save_to_excel(data)
        print(f"\nAll done! Open the file here:\n{DESKTOP_PATH}")
    except Exception as e:
        print(f"\nSomething went wrong: {e}")
        print("Please share this message so it can be fixed.")
    input("\nPress Enter to close this window...")
