# MyAgrar Price Scraper

An automation tool that logs into a B2B supplier portal and turns an hours-long manual price check into a one-click Excel report.

## Problem

Agricultural and crop-protection buyers need to track personalized/discounted prices across a large product catalog (crop protection + fertilizer, 1,000+ SKUs across 10+ category pages). Prices are only visible after logging in, pages are paginated, and each product's package-size breakdown has to be opened individually. Doing this by hand does not scale.

## How it's built

- **Python + Playwright**: opens a real, visible browser so the user logs in with their own credentials (the script never sees or stores them), then reuses that authenticated session.
- **Automated catalog crawl**: walks every crop-protection and fertilizer listing page, de-duplicating products that appear in more than one category.
- **Parallel fetching**: `ThreadPoolExecutor` (15 workers) pulls every product page concurrently via `requests` + `BeautifulSoup`, extracting price per package size, active ingredients, approved crops/application rates, and a computed cost-per-hectare estimate.
- **Structured output**: `pandas` + `openpyxl` build a multi-sheet Excel workbook, including a pivot summary grouped by product category.
- **Packaging**: built into a standalone Windows `.exe` via a GitHub Actions workflow, so non-technical end users can run it without installing Python.
- Built iteratively with Claude Code as a pairing tool for debugging edge cases (inconsistent pagination controls, bundle-product duplicate rows, cross-sheet column matching).

## Result

Replaces a manual, multi-hour, click-through price check with a single run that produces a ready-to-use Excel report — personalized pricing, cost-per-hectare, and a category pivot — across the full catalog.

## Stack

Python, Playwright, pandas, BeautifulSoup, openpyxl, GitHub Actions.
