# SalvageIQ

## Salvage Vehicle Part Recommendation Engine

## Overview

SalvageIQ is a web app built for salvage yard workers and resellers:

> Walk into a salvage yard, scan or enter a VIN, and instantly know which parts on that car are actually worth pulling.

Rather than relying on gut instinct, SalvageIQ pulls real marketplace data from eBay to answer three questions for every part on a given vehicle:

- How often does it sell?
- What does it typically sell for?
- How confident are we in that data?

Those three answers combine into a ranked list of parts with a **Pull / Maybe / Skip** recommendation for each one.

---

## How It Works

1. **User enters a VIN or year/make/model** in the browser (or scans a barcode)
2. **The app checks the cache** — if fresh results exist, they're returned immediately
3. **If not cached**, a background job fires and concurrently scrapes eBay for:
   - Sold listing history (price, title, sell date)
   - Active listing counts (current market supply)
4. **The pipeline runs**: cleanse → normalize → aggregate → rank
5. **Results are persisted** in SQLite and returned to the UI with verdicts and estimated net values
6. **Subsequent lookups for the same vehicle** are served from cache (14-day TTL)

---

## The Scoring Model

### Sell-Through Rate (STR)

eBay doesn't publish sell-through metrics, so SalvageIQ estimates demand vs. supply from available data:

```
sell_through = sold_count / (sold_count + active_count)
```

### Opportunity Score

Each part is scored by combining price, demand, and data confidence into a single number:

```
opportunity_score = median_sold_price × sell_through × confidence_score
```

### Confidence Score

A weighted reliability score based on how much data backs the result:

```
sold_component   = min(1.0, sold_count   / target)   # weight: 0.70
active_component = min(1.0, active_count / target)   # weight: 0.30
confidence_score = (sold_component × 0.70) + (active_component × 0.30)
```

### Net Value Estimate

Each part is further enriched with a net value calculation that accounts for your actual costs:

```
net_value = median_price
          - (pull_time_hours × labor_rate)
          - estimated_yard_cost
          - (median_price × marketplace_fee)
          - estimated_shipping_cost
```

Labor rate, marketplace fee, and other adjustments are configurable in the app's Settings panel.

### Pull / Maybe / Skip Verdicts

| Verdict | Meaning |
|---------|---------|
| **Pull** | Strong opportunity — high STR, good price, solid data |
| **Maybe** | Marginal — worth considering but not a clear winner |
| **Skip** | Low demand, low price, or insufficient data to trust |

Thresholds shift based on your selected risk tolerance (low / medium / high).

### Quality Flags

| Flag | Condition | Purpose |
|------|-----------|---------|
| `low_sample_flag` | sold_count < 5 | Insufficient total observations |
| `very_low_sold_flag` | sold_count < 3 | Too few sold records to trust STR |
| `stale_snapshot_flag` | time_diff > 48 hrs | Active snapshot is too old relative to sold data |

Price outlier trimming is applied at the 5th and 95th percentiles (for groups of 20+ observations) before calculating median price.

---

## What This Is Not

- Not a full parts catalog or vehicle inventory system
- Not a true sell-through rate — it's a proxy built from available eBay data
- Not a profit calculator — net value estimates are approximations, not guarantees
- Not a future price predictor — all values reflect the past 90 days only

---

## Project Structure

```text
salvageiq/
│
├── app/
│   ├── api.py               # FastAPI endpoints (search, jobs, results, history, settings)
│   ├── cache.py             # Cache freshness logic (fresh / usable_stale / expired)
│   ├── db.py                # SQLite layer — all tables, migrations, queries
│   ├── net_value.py         # Pull profiles, net value formula, verdict thresholds
│   ├── salvage_service.py   # Background job runner — bridges API to pipeline
│   ├── vehicle_lookup.py    # VIN decode (NHTSA vPIC), build_vehicle_key
│   └── static/
│       ├── index.html       # Single-page UI — search, results, history, settings
│       ├── script.js        # Polling, VIN scanner, history, settings panel
│       └── style.css        # App styles
│
├── config/
│   ├── settings.py          # Runtime defaults and tuning parameters
│   ├── vehicles.py          # Supported vehicles and make/model aliases
│   ├── taxonomy.py          # Part classification rules and eBay search terms
│   ├── schema.py            # Column contracts for each pipeline stage
│   ├── scrape_config.py     # ScrapeConfig dataclass and all path properties
│   ├── extraction_rules.py  # eBay CSS selectors and URL constants
│   └── config_builder.py    # Run mode factory (full, mini, test)
│
├── scrape/
│   ├── runner.py            # Async httpx scraper (concurrent sold + active passes)
│   ├── extractors.py        # Field extractors and listing heuristics
│   └── search_builder.py    # eBay search URL and checkpoint key builders
│
├── wrangle/
│   ├── cleanse.py           # Raw listing cleanup and field extraction
│   └── normalize.py         # Standardization, taxonomy mapping, deduplication
│
├── analysis/
│   ├── analyze.py           # Analysis stage controller
│   ├── aggregation.py       # Sold + active join, STR, flags, opportunity score
│   ├── scoring.py           # STR, confidence, and opportunity score formulas
│   ├── pricing_metrics.py   # Price outlier trimming
│   └── ranking.py           # Ranked output builder (top N parts per vehicle)
│
├── pipeline/
│   └── orchestrator.py      # Stage sequencing: scrape → cleanse → normalize → analyze
│
├── utils/
│   ├── checkpoint_utils.py  # Scrape resume support (completed search tracking)
│   ├── io_utils.py          # CSV helpers, directory setup, file resets
│   └── logging_utils.py     # Run-scoped logging to file + console
│
├── tests/
│   ├── smoke/
│   │   ├── test_imports.py         # Module import validation
│   │   ├── test_config_build.py    # ScrapeConfig construction
│   │   ├── test_runner_smoke.py    # Scrape runner execution [integration]
│   │   ├── test_wrangle_smoke.py   # Cleanse → normalize flow
│   │   └── test_analyze_smoke.py   # Analysis stage output
│   ├── unit/
│   │   ├── test_normalize_token.py
│   │   ├── test_standardize_make.py
│   │   ├── test_standardize_model.py
│   │   ├── test_standardize_part.py
│   │   ├── test_classify_part.py
│   │   ├── test_category_from_part.py
│   │   ├── test_deduplicate_listings.py
│   │   └── test_run_normalization.py
│   └── test_aggregation.py         # Aggregation layer unit tests
│
├── data/
│   └── runs/
│       └── <run_id>/
│           └── outputs/
│               └── logs/
│                   ├── pipeline_<run_id>.log
│                   ├── scrape_run.log
│                   └── scrape_checkpoint.json  # only when resume is enabled
│
├── assets/
│   ├── logo_main.png        # Horizontal logo (light background)
│   └── logo_dark.png        # Banner logo (dark background, used as favicon)
│
├── main.py                  # CLI entry point for the scrape pipeline
├── pytest.ini
├── requirements.txt         # Pipeline dependencies
├── requirements_app.txt     # App dependencies (superset of requirements.txt)
└── README.md
```

---

## Data Flow

Each pipeline run is fully isolated under a unique `run_id` (UUID). All data moves between stages **in memory** — no intermediate files are written to disk.

```
eBay (sold pass)   ──► raw_df (DataFrame, in memory)
eBay (active pass) ──► market_df (DataFrame, in memory)
                           │
                     cleanse.py
                           │ (DataFrame)
                     normalize.py
                           │ (DataFrame)
                     aggregation.py  ◄── market_df
                           │ (DataFrame)
                     ranking.py
                           │ (DataFrame)
                     salvage_service.py
                           │
                     SQLite (result_sets, result_items)
                           │
                     FastAPI → browser UI
```

The only things written to disk per run are the log files (and a checkpoint file if resume is enabled), stored under `data/runs/<run_id>/outputs/logs/`.

**Sold and active are scraped as separate passes.** The sold pass feeds the full cleanse → normalize → analysis path. The active pass captures current market supply and is joined to sold data during aggregation to compute sell-through rates.

**The scraper is fully concurrent.** All part searches for a given vehicle run simultaneously via `asyncio.gather` with a connection semaphore. eBay search pages are server-side rendered, so no browser is needed — `httpx` + `BeautifulSoup` replace the old Playwright approach. A full vehicle analysis that previously took ~3 minutes now completes in ~15–25 seconds.

---

## Running the App

### Install dependencies

```bash
pip install -r requirements_app.txt
```

### Start the server

```bash
uvicorn app.api:app --reload
```

Then open `http://localhost:8000` in your browser.

---

## Pipeline Run Modes

The scrape pipeline can also be run directly from the CLI. Defined in `config/config_builder.py`.

### Full Run

All configured vehicles, all parts, all years (2012–2020).

```bash
python main.py
# or:
python main.py full
```

### Mini Run

1 vehicle (Toyota Camry), 2 parts (alternator + headlight), 2 years. Good for a quick end-to-end pipeline check.

```bash
python main.py mini
```

### Test Run

1 vehicle, 1 part, 1 year, 1 page. Fast smoke test.

```bash
python main.py test
```

---

## Key Design Decisions

### 1. Cache-First Architecture
The API checks SQLite for a recent result set before firing a scrape job. Results have a 14-day TTL. Stale-but-usable results are served immediately while a background refresh runs.

### 2. Async HTTP Scraping
The scraper uses `httpx.AsyncClient` with `asyncio.gather` to run all part searches concurrently. eBay search result pages are server-side rendered, so no browser execution is needed. A configurable semaphore limits simultaneous connections to avoid rate limiting.

### 3. In-Memory Pipeline
All data flows between pipeline stages as DataFrames — no intermediate CSV files are written. The scraper returns DataFrames directly to the cleanse stage, which hands off to normalize, which hands off to analysis. The final ranked results land in SQLite without ever touching disk in between. The only disk writes per run are the log file and an optional checkpoint file for resume support.

### 4. Run-Isolated Log Directory
Each pipeline run gets its own directory under `data/runs/<run_id>/outputs/logs/` for its log file and optional checkpoint. Since all data is in memory, this is the only directory created per run — no accumulating CSV files regardless of usage volume.

### 5. Config-Driven Pipeline
Vehicles, parts, taxonomy rules, column contracts, and path structures all live in `config/`. No hardcoded paths or magic strings scattered through stage logic.

### 6. Taxonomy-Based Classification
Part search terms and classification rules live in `config/taxonomy.py`. Each part category defines include terms and exclude terms (e.g., "alternator" includes `alternator` but excludes `alternator rebuild kit`). This makes the search scope easy to tune without touching scraper logic.

### 7. Checkpoint / Resume
Completed searches are written to a checkpoint file after each successful fetch. If a run is interrupted, it can resume from where it left off rather than starting over.

---

## Testing

```bash
# All tests (excluding live network calls)
pytest -m "not integration"

# All tests including the live scrape runner
pytest
```

### Test Structure

```text
tests/
├── smoke/
│   ├── test_imports.py         # All core modules import without error
│   ├── test_config_build.py    # ScrapeConfig builds correctly for each mode
│   ├── test_runner_smoke.py    # Scrape runner executes and returns expected shape [integration]
│   ├── test_wrangle_smoke.py   # Cleanse → normalize produces correct output
│   └── test_analyze_smoke.py   # Analysis stage reads inputs and writes expected CSV
├── unit/
│   ├── test_normalize_token.py
│   ├── test_standardize_make.py
│   ├── test_standardize_model.py
│   ├── test_standardize_part.py
│   ├── test_classify_part.py
│   ├── test_category_from_part.py
│   ├── test_deduplicate_listings.py
│   └── test_run_normalization.py
└── test_aggregation.py         # Sold + active aggregation, STR, flags, scoring
```

---

## Bottom Line

SalvageIQ turns:

> "I think this part might sell"

into:

> "Based on real eBay data, these are your top pulls for this vehicle."
