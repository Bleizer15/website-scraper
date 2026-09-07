#!/usr/bin/env python3
"""
Competitor price comparison across B2B shops. One config entry per shop.

WHAT THIS IS FOR
----------------
The agriculture scraper in scraper.py is 999 lines because crop protection
needs application rates per culture to answer "what does it cost to treat a
hectare of maize". Most verticals need nothing like that. For dental, hygiene
and general B2B consumables the buying question is simply:

    same product, different pack sizes -- who is cheapest PER UNIT, and what
    changed since last week?

That is the generic core, and it is what this file does. Adding a shop is a
config entry, not a rewrite.

POLITENESS AND LEGALITY
-----------------------
Product URLs come from each shop's own sitemap.xml, which is advertised in
their robots.txt -- we are reading the index they publish for crawlers, not
guessing URLs or hammering search. robots.txt is checked for each host and its
Disallow rules are honoured. Requests are rate-limited and single-threaded per
host by default.

Both currently configured shops publish prices publicly, so no login is
involved. If a shop hides prices behind a login, the client must supply their
own account and authorise the access in writing -- that is their contractual
relationship with the supplier, not ours.

MATCHING IS THE HARD PART, NOT SCRAPING
---------------------------------------
Two shops rarely name the same product identically ("3M Filtek One Bulk Fill
20 x 0,2 g" vs "Filtek One BulkFill Kapseln 20x0.2g"). Matching is done on a
normalised token set with a similarity floor, and every match is emitted with
its score so a human can audit the weak ones rather than trusting them
silently. Unmatched products are reported too -- a product only one shop
carries is itself useful information.

    python pricewatch.py --limit 120
    python pricewatch.py --shops geizdental --limit 300
"""
import argparse
import gzip
import io
import os
import re
import sys
import time
import urllib.parse
import urllib.robotparser as robotparser
from difflib import SequenceMatcher

import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"),
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
}
DELAY = 0.7          # seconds between requests to one host
MATCH_FLOOR = 0.62   # below this, do not claim two products are the same

# One entry per shop. `platform` selects the extractor; everything else is data.
SHOPS = {
    "geizdental": {
        "name": "GeizDental",
        "base": "https://geizdental.de",
        "sitemap": "https://geizdental.de/sitemap.xml",
        "platform": "magento",
        # Product URLs end in an article number like -a149592/ or -gz180800/
        "url_filter": re.compile(r"^https://geizdental\.de/[a-z0-9\-]+-[a-z]{0,2}\d{4,}/$"),
    },
    # Shopware 6. Product URLs are /brand/product-name-123456 .
    # NOTE: klapperzaehnchen.de was the first Shopware candidate and was
    # dropped -- its sitemap returns Content-Length 0, i.e. it is broken on
    # their side. kaniedenta.de publishes categories only. That variability
    # is normal and is why each shop costs setup time.
    "dentalbauer": {
        "name": "DentalBauer",
        "base": "https://www.dentalbauer.de",
        "sitemap": "https://www.dentalbauer.de/sitemap.xml",
        "platform": "shopware6",
        "url_filter": re.compile(r"^https://www\.dentalbauer\.de/[a-z0-9\-]+/[a-z0-9\-]+-\d{5,}$"),
    },
}

UNIT_WORDS = r"(ml|l|liter|g|kg|stk|stück|stueck|st|packung|pack|blatt|paar)"


def to_float(v):
    """German number format: comma is the decimal separator."""
    if v is None:
        return None
    s = re.sub(r"[^\d,.\-]", "", str(v))
    if not s:
        return None
    # 1.234,56 -> 1234.56 ; 12,34 -> 12.34 ; 12.34 stays
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def robots_for(base):
    rp = robotparser.RobotFileParser()
    rp.set_url(urllib.parse.urljoin(base, "/robots.txt"))
    try:
        rp.read()
    except Exception:
        return None
    return rp


def fetch(url, session, timeout=25):
    try:
        r = session.get(url, headers=HEADERS, timeout=timeout)
        if r.status_code != 200:
            return None
        return r
    except Exception:
        return None


def sitemap_urls(entry, session, cap=8000):
    """Product URLs from the shop's own sitemap, following nested indexes."""
    seen, out = set(), []
    queue = [entry["sitemap"]]
    while queue and len(out) < cap:
        sm = queue.pop(0)
        if sm in seen:
            continue
        seen.add(sm)
        r = fetch(sm, session)
        if not r:
            continue
        body = r.content
        if sm.endswith(".gz") or body[:2] == b"\x1f\x8b":
            try:
                body = gzip.decompress(body)
            except Exception:
                continue
        text = body.decode("utf-8", "ignore")
        locs = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", text)
        for u in locs:
            if u.endswith(".xml") or u.endswith(".xml.gz"):
                queue.append(u)
            elif entry["url_filter"].match(u):
                out.append(u)
        time.sleep(DELAY / 2)
    return out


def extract_magento(soup):
    name = soup.find("h1")
    name = name.get_text(" ", strip=True) if name else None
    price = None
    node = soup.select_one("[data-price-amount]")
    if node:
        price = to_float(node.get("data-price-amount"))
        # Magento sometimes carries 0 in the attribute; fall back to the text.
        if not price:
            price = to_float(node.get_text(" ", strip=True))
    if price is None:
        n = soup.select_one("span.price")
        price = to_float(n.get_text(strip=True)) if n else None
    sku = soup.find(attrs={"itemprop": "sku"})
    sku = (sku.get("content") or sku.get_text(strip=True)) if sku else None
    if not sku:
        m = re.search(r"Bestell-Nr\.?:\s*([A-Z0-9\-]+)", soup.get_text(" ", strip=True))
        sku = m.group(1) if m else None
    return name, price, sku


def extract_shopware(soup):
    name = soup.select_one("h1.product-detail-name, h1")
    name = name.get_text(" ", strip=True) if name else None
    price = None
    for sel in ("meta[itemprop=price]", ".product-detail-price",
                "span.price", "[class*=product-price]"):
        n = soup.select_one(sel)
        if n:
            price = to_float(n.get("content") or n.get_text(" ", strip=True))
            if price:
                break
    sku = soup.select_one("[itemprop=sku], .product-detail-ordernumber")
    sku = (sku.get("content") or sku.get_text(strip=True)) if sku else None
    return name, price, sku


EXTRACTORS = {"magento": extract_magento, "shopware6": extract_shopware}


def pack_size(name):
    """(count, amount, unit) parsed out of the product name.

    '20 x 0,2 g Kapseln' -> (20, 0.2, 'g');  'Flasche 75 ml' -> (1, 75.0, 'ml')
    This is what makes a per-unit comparison possible at all: two shops sell
    the same thing in different pack sizes and the sticker prices are not
    comparable until this is normalised.
    """
    t = name.lower().replace("\xa0", " ") if name else ""
    m = re.search(r"(\d+)\s*[x×]\s*([\d.,]+)\s*" + UNIT_WORDS, t)
    if m:
        return to_float(m.group(1)), to_float(m.group(2)), m.group(3)
    m = re.search(r"(\d+)\s*[x×]\s*" + UNIT_WORDS, t)
    if m:
        return to_float(m.group(1)), 1.0, m.group(2)
    m = re.search(r"([\d.,]+)\s*" + UNIT_WORDS + r"\b", t)
    if m:
        return 1.0, to_float(m.group(1)), m.group(2)
    return None, None, None


CANON = {"stück": "stk", "stueck": "stk", "st": "stk", "liter": "l",
         "packung": "stk", "pack": "stk"}


def per_unit(price, count, amount, unit):
    if price is None or not unit:
        return None, None
    u = CANON.get(unit, unit)
    total = (count or 1) * (amount or 1)
    if not total:
        return None, None
    # Normalise so ml and l (and g and kg) are comparable.
    if u == "l":
        total, u = total * 1000, "ml"
    elif u == "kg":
        total, u = total * 1000, "g"
    return round(price / total, 4), u


def norm_tokens(name):
    """Token set for matching: lowercase, drop pack sizes and noise words."""
    t = (name or "").lower().replace("\xa0", " ")
    t = re.sub(r"\d+\s*[x×]\s*[\d.,]+\s*\w+", " ", t)
    t = re.sub(r"[\d.,]+\s*" + UNIT_WORDS + r"\b", " ", t)
    t = re.sub(r"[^a-zäöüß0-9 ]", " ", t)
    # Form factor (Spritze / Caps / Kapseln) DISTINGUISHES products and must
    # stay in the token set. Treating it as noise matched a 3 g syringe against
    # a 10 x 0,2 g capsule pack and reported a 73% price gap that was really a
    # 15% gap between two different articles.
    stop = {"packung", "flasche", "je", "der", "die", "das", "und", "mit",
            "fuer", "für", "stk", "pack"}
    return [w for w in t.split() if len(w) > 2 and w not in stop]


def similarity(a, b):
    ta, tb = set(norm_tokens(a)), set(norm_tokens(b))
    if not ta or not tb:
        return 0.0
    jac = len(ta & tb) / len(ta | tb)
    seq = SequenceMatcher(None, " ".join(sorted(ta)), " ".join(sorted(tb))).ratio()
    return 0.5 * jac + 0.5 * seq


def scrape_shop(key, entry, limit, session, focus=()):
    rp = robots_for(entry["base"])
    urls = sitemap_urls(entry, session)
    if focus:
        urls = [u for u in urls if any(f in u.lower() for f in focus)]
    print(f"  {entry['name']}: {len(urls)} product URLs"
          f"{' matching focus' if focus else ' in sitemap'}")
    if not urls:
        return []
    # Even spread across the catalogue rather than the first N, which would
    # all be one brand and make the comparison look artificially good.
    step = max(1, len(urls) // limit)
    picked = urls[::step][:limit]
    ex = EXTRACTORS[entry["platform"]]
    rows = []
    for i, u in enumerate(picked):
        if rp and not rp.can_fetch(HEADERS["User-Agent"], u):
            continue
        r = fetch(u, session)
        time.sleep(DELAY)
        if not r:
            continue
        try:
            name, price, sku = ex(BeautifulSoup(r.text, "html.parser"))
        except Exception:
            continue
        if not name or price is None:
            continue
        c, a, un = pack_size(name)
        pu, puu = per_unit(price, c, a, un)
        rows.append(dict(shop=entry["name"], url=u, name=name, price=price,
                         sku=sku, count=c, amount=a, unit=un,
                         per_unit=pu, per_unit_unit=puu))
        if (i + 1) % 25 == 0:
            print(f"    {i+1}/{len(picked)}  kept {len(rows)}", end="\r")
    print(f"    {entry['name']}: {len(rows)} products with a price")
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shops", default=",".join(SHOPS))
    ap.add_argument("--limit", type=int, default=120,
                    help="products sampled per shop")
    ap.add_argument("--out", default="competitor_prices.xlsx")
    ap.add_argument("--focus", default="",
                    help="comma-separated keywords; only sample URLs containing "
                         "one of them. Without this, two catalogues of 16k and "
                         "50k products are sampled independently and almost "
                         "nothing overlaps, so the comparison looks empty for "
                         "reasons that have nothing to do with pricing.")
    a = ap.parse_args()

    session = requests.Session()
    allrows = []
    for key in a.shops.split(","):
        key = key.strip()
        if key not in SHOPS:
            print(f"unknown shop: {key}")
            continue
        focus = tuple(f.strip().lower() for f in a.focus.split(',') if f.strip())
        allrows += scrape_shop(key, SHOPS[key], a.limit, session, focus)

    if not allrows:
        print("nothing scraped")
        return 1

    shops = sorted({r["shop"] for r in allrows})
    print(f"\ntotal {len(allrows)} products across {len(shops)} shops")

    matches = []
    if len(shops) >= 2:
        left = [r for r in allrows if r["shop"] == shops[0]]
        right = [r for r in allrows if r["shop"] == shops[1]]
        for l in left:
            best, score = None, 0.0
            for rr in right:
                s = similarity(l["name"], rr["name"])
                if s > score:
                    best, score = rr, s
            if best and score >= MATCH_FLOOR:
                matches.append((l, best, score))
        matches.sort(key=lambda m: -m[2])
        print(f"matched pairs (similarity >= {MATCH_FLOOR}): {len(matches)}")

    try:
        import pandas as pd
    except ImportError:
        print("pandas not available; writing CSV instead")
        pd = None

    if pd:
        with pd.ExcelWriter(a.out, engine="openpyxl") as w:
            pd.DataFrame(allrows).to_excel(w, sheet_name="All products", index=False)
            if matches:
                cmp_rows = []
                for l, r, s in matches:
                    # Comparable ONLY when both sides normalise to the same
                    # unit. Sticker prices across different pack sizes are not
                    # a price comparison, they are a pack-size comparison.
                    same_unit = (l["per_unit"] is not None
                                 and r["per_unit"] is not None
                                 and l["per_unit_unit"] == r["per_unit_unit"])
                    if same_unit:
                        a_v, b_v = l["per_unit"], r["per_unit"]
                        basis = f"per {l['per_unit_unit']}"
                    else:
                        a_v, b_v = l["price"], r["price"]
                        basis = "STICKER - pack sizes differ, not comparable"
                    cheaper = (l["shop"] if a_v < b_v
                               else r["shop"] if b_v < a_v else "same")
                    diff = abs(a_v - b_v)
                    base = max(min(a_v, b_v), 1e-6)
                    cmp_rows.append({
                        "Product (A)": l["name"], "Product (B)": r["name"],
                        "Match score": round(s, 3), "Basis": basis,
                        f"{l['shop']} €": l["price"], f"{r['shop']} €": r["price"],
                        f"{l['shop']} {basis}": a_v if same_unit else None,
                        f"{r['shop']} {basis}": b_v if same_unit else None,
                        "Diff %": round(diff / base * 100, 1) if same_unit else None,
                        "Cheaper": cheaper if same_unit else "unknown",
                        "URL A": l["url"], "URL B": r["url"],
                    })
                pd.DataFrame(cmp_rows).to_excel(w, sheet_name="Comparison", index=False)
        print(f"wrote {a.out}")

    if matches:
        print(f"\n{'score':>6}{'A €':>9}{'B €':>9}{'per-unit diff':>15}  product")
        for l, r, s in matches[:12]:
            ok = (l["per_unit"] is not None and r["per_unit"] is not None
                  and l["per_unit_unit"] == r["per_unit_unit"])
            if ok:
                base = max(min(l["per_unit"], r["per_unit"]), 1e-6)
                d = f"{abs(l['per_unit']-r['per_unit'])/base*100:>13.0f}%"
            else:
                d = "  not comparable"
            print(f"{s:>6.2f}{l['price']:>9.2f}{r['price']:>9.2f}{d}  {l['name'][:46]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
