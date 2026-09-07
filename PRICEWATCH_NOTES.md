# pricewatch.py — what was built, what it proved

## Works, verified against live sites

- Sitemap discovery, `robots.txt` honoured, rate-limited (0.7s/host)
- Two platform connectors: **Magento** (geizdental) and **Shopware 6** (dentalbauer)
- Adding a shop is a config entry — name, sitemap, platform, URL regex
- Price + name extraction: correct on both
- Pack-size parsing and per-unit normalisation, verified by hand:
  `116,93 € / (2 x 5 L) = 0,0117 €/ml`
- Excel out: all products + matched comparison
- `--focus` samples both shops from the same product space

## Site variability is real, and it is the per-client cost

Of four Shopware dental shops tried:

| shop | sitemap | usable |
|---|---|---|
| geizdental (Magento) | 16,315 product URLs | yes |
| dentalbauer | 49,999 locs, products at depth 4 | yes |
| klapperzaehnchen | returns `Content-Length: 0` | **broken on their side** |
| kaniedenta | categories only, no products | needs category crawl |

Half the candidate shops needed work beyond a config entry. Budget for that.

## The hard part is matching, not scraping

Neither shop publishes EAN/GTIN:

- dentalbauer: manufacturer number only (`1001`), no GTIN
- geizdental: own SKU only (`A104126_gzd`), no manufacturer number

**No shared identifier exists**, so cross-shop matching is fuzzy on product
names. Two failures found and one fixed:

1. **Form factor treated as noise.** `spritze` and `kapseln` were in the
   stopword list, so a *3 g syringe* matched a *10 x 0,2 g capsule pack* at
   0.85 similarity and reported a **73% price gap**. The real per-gram gap was
   15%. Fixed: form-factor tokens retained, similarity drops to 0.73, and
   comparison is per-unit rather than sticker.

2. **Configurable products, unfixed.** dentalbauer's Tofflemire page carries
   four prices (7,29 / 10,59 / 12,49 / 5,79) — one per variant. The extractor
   takes the default, so the reported 53.5% gap compares one variant against
   another and is NOT verified. Variant handling is needed before any number
   from a configurable product can be trusted.

## The reframe this points to

N x M matching between two full catalogues is the wrong product. It is
expensive, unverifiable without a shared key, and most matches are noise.

The right product is **"monitor MY catalogue against competitors"**:

1. Client supplies their own product list with manufacturer part numbers
2. Match once against each competitor, WITH human review — a one-off setup cost
3. Track the mapped set forever, fully automatic

That turns an unsolvable N x M problem into a bounded one-time task, makes the
weekly run trivially reliable, and the mapping itself becomes switching cost.

## Next

- Variant handling for configurable products (blocks trustworthy numbers)
- Client-catalogue input instead of catalogue-vs-catalogue
- Week-over-week diff (the logic already exists in `scraper.py`)
