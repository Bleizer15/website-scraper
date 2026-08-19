"""
Platform detector for B2B shops.

Answers two questions for any shop URL, without logging in:

  1. Which e-commerce platform is it? (Magento / Shopware / JTL / OXID / ...)
  2. Does it hide prices behind a login?

Why it matters: the price-extraction logic in scraper.py targets Magento's
`spConfig` JSON structure. Every Magento shop exposes that same structure,
so one connector covers many shops. Other platforms need their own
extraction logic -- but the login/session/pagination machinery is reused.

Usage:
    python platform_detect.py https://www.myagrar.de/pflanzenschutzmittel/
    python platform_detect.py --file urls.txt
"""

import sys
import re
import json
import concurrent.futures as cf

import requests

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"),
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
}

# Marker -> platform. Ordered most-specific first; several markers may hit,
# we report all of them with a score so ambiguous cases stay visible.
PLATFORM_MARKERS = {
    "Magento": [
        "x-magento-init", "Magento_Ui/js", "/static/version", "mage/cookies",
        "Magento_Theme", "data-mage-init", "checkout/cart/add",
    ],
    "Shopware 6": [
        "window.router", "/bundles/storefront/", "data-cms-element",
        "sw-", "Shopware.Component", "/store-api/",
    ],
    "Shopware 5": [
        "/themes/Frontend/", "shopware.jQuery", "/engine/Shopware/",
    ],
    "JTL-Shop": [
        "jtl-shop", "/templates/NOVA/", "JTL-Software", "wawi",
    ],
    "OXID eShop": [
        "oxid", "/out/azure/", "/out/flow/", "oxidEshop",
    ],
    "WooCommerce": [
        "woocommerce", "wp-content/plugins/woocommerce",
    ],
    "Shopify": [
        "cdn.shopify.com", "Shopify.theme",
    ],
    "SAP Commerce": [
        "/_ui/responsive/", "hybris",
    ],
}

# Phrases that indicate the shop hides prices until you log in.
# German first -- that is the target market -- then English.
LOGIN_GATE_PHRASES = [
    "anmelden für ihren persönlichen preis",
    "preis nach anmeldung",
    "preise nach anmeldung",
    "nettopreise nach login",
    "preis erst nach login",
    "nach dem login sichtbar",
    "bitte anmelden um preise zu sehen",
    "für preise bitte anmelden",
    "nur für angemeldete kunden",
    "ihren persönlichen preis",
    "händlerpreis",
    "log in to see price",
    "login for price",
    "price after login",
    "sign in to see pricing",
    "request a quote for pricing",
]

# Structures scraper.py already knows how to parse.
EXTRACTION_MARKERS = {
    "spConfig (Magento configurable product JSON)": '"spConfig"',
    "optionPrices (Magento per-variant pricing)": '"optionPrices"',
    "base-price (Magento unit pricing)": "base-price",
    "JSON-LD Product schema": '"@type":"Product"',
    "JSON-LD offers": '"@type":"Offer"',
}


def detect(url, timeout=20):
    out = {"url": url, "ok": False}
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout)
        out["status"] = r.status_code
        r.raise_for_status()
    except requests.RequestException as e:
        out["error"] = str(e)[:160]
        return out

    html = r.text
    low = html.lower()
    out["ok"] = True
    out["bytes"] = len(html)

    scores = {}
    for platform, markers in PLATFORM_MARKERS.items():
        hits = [m for m in markers if m.lower() in low]
        if hits:
            scores[platform] = hits
    out["platforms"] = {p: len(h) for p, h in sorted(
        scores.items(), key=lambda kv: -len(kv[1]))}
    out["platform"] = next(iter(out["platforms"]), "unknown")

    out["login_gated"] = [p for p in LOGIN_GATE_PHRASES if p in low]
    out["extractable"] = [name for name, marker in EXTRACTION_MARKERS.items()
                          if marker.lower() in low]

    # Rough verdict: how much of scraper.py transfers as-is.
    if "spConfig" in html:
        out["verdict"] = "REUSE — existing extraction should work"
    elif out["platform"].startswith("Magento"):
        out["verdict"] = "LIKELY REUSE — Magento, check a product page"
    elif out["platform"] != "unknown":
        out["verdict"] = f"NEW EXTRACTION — {out['platform']}, login/pagination code reuses"
    else:
        out["verdict"] = "UNKNOWN — inspect manually"
    return out


def report(res):
    print(f"\n{'=' * 72}\n{res['url']}")
    if not res.get("ok"):
        print(f"  FAILED  {res.get('status', '')} {res.get('error', '')}")
        return
    print(f"  platform     {res['platform']}   {res['platforms']}")
    print(f"  login-gated  {res['login_gated'] or 'no phrases found on THIS page'}")
    print(f"  extractable  {res['extractable'] or 'none on this page'}")
    print(f"  VERDICT      {res['verdict']}")


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return
    if args[0] == "--file":
        urls = [l.strip() for l in open(args[1]) if l.strip()
                and not l.startswith("#")]
    else:
        urls = args

    with cf.ThreadPoolExecutor(max_workers=8) as ex:
        for res in ex.map(detect, urls):
            report(res)

    print(f"\n{'=' * 72}\nNote: run this against a PRODUCT page, not the homepage.")
    print("spConfig only appears on configurable-product pages.")


if __name__ == "__main__":
    main()
