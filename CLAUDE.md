# XML Auditor — Claude Code Init

## What This Is

Multi-agent Flask app for auditing job feed XMLs. Input: URL or raw paste. Output: a fixed set of aggregated cards rendered on-page. Users are ad ops analysts doing quick feed sanity checks. Feeds are job XML or RSS-style, sometimes gzip. Performance is a hard requirement — feeds can be 1 GB+.

---

## Pipeline

```
Intake → Reader → Breakdown → QA → Flask → Frontend
```

Each agent is a module in `/agents/`. They share a single `state` dict — receive it, return an updated copy, never mutate in place.

---

## State Schema

```python
state = {
    # Intake
    "source_url": str | None,       # set for URL feeds; None for paste
    "raw_bytes": bytes,             # first 512 bytes only (never full content)
    "content_bytes": bytes,         # paste mode: full content. URL mode: b""
    "is_gzip": bool,
    "encoding": str,
    "source_label": str,            # URL hostname or "paste"
    "cache_key": str,               # sha256(url) for URL feeds; sha256(content) for paste
    "errors": [],                   # [{agent, message, severity}]

    # Reader
    "root_tag": str,
    "root": None,                   # always None — iterparse used, no tree stored
    "tag_inventory": dict,          # {tag: count} all tags seen
    "parent_candidates": dict,      # {tag: count} likely record-level parent nodes
    "field_candidates": dict,       # {tag: [sample_values]} leaf tags, first 20 nodes

    # Breakdown
    "parent_tag": str,
    "node_count": int,
    "cards": {},                    # {card_id: card_result} — see Card Spec below
    "available_tags": [],

    # QA
    "qa_flags": [],                 # [{field, issue, severity, suggested_action?}]
    "confidence": float,            # 0.0–1.0
    "qa_passed": bool,
}
```

---

## Agents

### Intake

**URL mode:** Open connection, read first 2 bytes only to detect gzip (`b"\x1f\x8b"`). Store `source_url` and `is_gzip`. Do NOT read full content — `content_bytes` stays `b""`. Cache key = `sha256(url.encode())`.

**Paste mode:** Accept raw XML string or bytes. Cap at 10 MB. Decompress if gzip. Store full content in `content_bytes`. Cache key = `sha256(content_bytes)`.

Sniff encoding from XML declaration header. On any error: append to errors, return early.

### Reader

Stream the full feed via `ET.iterparse` — never builds the full tree in memory.

**URL mode:** Open a new HTTP connection, stream through `gzip.GzipFile(fileobj=resp)` if gzip, feed directly into `ET.iterparse`. `content_bytes` is empty; reader re-fetches the URL.

**Paste mode:** `ET.iterparse(io.BytesIO(content_bytes), ...)`.

Use a stack to track parent/child relationships during streaming. Build:
- `tag_inventory` — count of every tag seen
- `parent_candidates` — tags with avg 3+ children per node AND 10+ occurrences, OR named `job/item/listing/result/record/vacancy`
- `field_candidates` — up to 5 sample values per leaf tag, from first 20 nodes seen

Call `elem.clear()` after each "end" event to free memory. Handle `ET.ParseError` gracefully — use what was parsed.

`root` is always set to `None`. Do not store the ET tree.

### Breakdown

Re-streams the full feed in a single `iterparse` pass. Never calls `root.iter()` — uses `_iter_nodes()` generator instead.

**URL mode:** Opens a fresh HTTP connection to `state["source_url"]`, streams through gzip if needed.
**Paste mode:** Parses from `io.BytesIO(state["content_bytes"])`.

`_iter_nodes(state, parent_tag)` yields each fully-parsed parent element at its "end" event, then calls `elem.clear()`. This keeps RAM flat regardless of feed size.

Single pass accumulates all 6 cards simultaneously. Each card stores both:
- `rows` — top 25 by count (for UI display)
- `all_rows` — all rows uncapped (for CSV export)

### QA

Score starts at 1.0. Subtract 0.15 per warn, 0.35 per error, floor at 0.

| Check | Condition | Severity |
|---|---|---|
| Empty result | `node_count == 0` | error |
| Low node count | `node_count < 10` | warn |
| No CPC data | All CPC values missing | warn |
| No CPA data | All CPA values missing | warn |
| High missing rate | title or company missing > 10% | warn |
| CPC outlier | Any avg_cpc > 10× median | warn |
| CPA outlier | Any avg_cpa > 10× median | warn |

If `confidence < 0.5`: set `qa_passed = False`, add `suggested_action` to each flag.

### Orchestrator

Two independent caches — both in-memory, 15-minute TTL, no Redis, no disk.

```python
FEED_CACHE      = {}   # post-reader state (tag metadata). Key = sha256(url) or sha256(content)
BREAKDOWN_CACHE = {}   # post-breakdown state (includes all_rows). Key = sha256(reader_key + parent_tag + field_map)
```

**probe_feed(url, xml_text):**
1. Check `FEED_CACHE` — return cached reader state if hit
2. Run intake → reader
3. Store in `FEED_CACHE`

**run_pipeline(url, xml_text, parent_tag, field_map):**
1. Check `FEED_CACHE` for reader state — run intake + reader if miss
2. Run breakdown + QA (always — field_map can differ between calls)
3. Store full post-QA state in `BREAKDOWN_CACHE` (keyed by reader_key + parent_tag + field_map)
4. Return state

Breakdown always re-streams the URL — it does not use cached content. The `BREAKDOWN_CACHE` exists so that `/api/export_csv` can serve `all_rows` instantly without re-fetching the feed.

---

## Card Spec

Six fixed cards. Computed in a single iterparse pass by Breakdown agent.

```python
DEFAULT_CARDS = [
    {"id": "title_cpc",   "label": "Job Title × CPC",          "group_by": "title",   "metrics": ["count", "avg_cpc"], "sort_by": "count", "cap": 25},
    {"id": "title_cpa",   "label": "Job Title × CPA",          "group_by": "title",   "metrics": ["count", "avg_cpa"], "sort_by": "count", "cap": 25},
    {"id": "company_cpc", "label": "Company × CPC",            "group_by": "company", "metrics": ["count", "avg_cpc"], "sort_by": "count", "cap": 25},
    {"id": "company_cpa", "label": "Company × CPA",            "group_by": "company", "metrics": ["count", "avg_cpa"], "sort_by": "count", "cap": 25},
    {"id": "cpc_dist",    "label": "CPC Value Distribution",   "group_by": "cpc",     "metrics": ["count"],            "sort_by": "cpc_value_asc", "cap": None},
    {"id": "total_count", "label": "Total Node Count",         "type": "stat",        "value_key": "node_count"},
]
```

Each non-stat card result shape (server-side):
```python
{
    "id": "title_cpc",
    "label": "Job Title × CPC",
    "total_unique": 312,          # total distinct values
    "capped": True,
    "rows": [...],                # top 25 — sent to frontend for display
    "all_rows": [...],            # all rows — kept server-side, served on CSV export
}
```

`all_rows` is stripped from the `/api/analyze` JSON response before sending to the frontend. It lives only in `BREAKDOWN_CACHE` and is streamed directly to CSV on export.

---

## Flask (`app.py`) — thin routes only

| Route | Body | Returns |
|---|---|---|
| `GET /` | — | `index.html` |
| `POST /api/probe` | `{url?, xml_text?}` | `{root_tag, is_gzip, parent_candidates, field_candidates, errors}` |
| `POST /api/analyze` | `{url?, xml_text?, parent_tag, field_map}` | `{node_count, cards (rows only, no all_rows), qa_flags, confidence, errors}` |
| `POST /api/export_csv` | `{card_id, url?, xml_text?, parent_tag, field_map}` | streaming CSV of all_rows from BREAKDOWN_CACHE |

`field_map` shape: `{"title": "job_title", "company": "advertiser", "cpc": "cpc", "cpa": "cpa"}`

Export looks up `BREAKDOWN_CACHE` first (instant). Falls back to re-running the full pipeline if cache has expired.

---

## Frontend (`templates/index.html`)

Vanilla JS, no frameworks. Two steps:

**Step 1 — Probe**
URL input or paste toggle → "Probe Feed" → shows:
- Detected parent node chips (click to select, first auto-selected)
- Field mapping dropdowns: Title, Company, CPC, CPA (auto-matched by alias from `field_candidates`)

**Step 2 — Analyze**
"Run Analysis" → all 6 cards render at once from single JSON response.

Each card renders as a compact table. Total Count card renders as a single large stat.

Card table columns:
- Title/Company cards: Value | Count | Avg CPC or Avg CPA (show `—` for null)
- CPC dist card: CPC Value | Count

Export button label shows total row count: **"Export CSV (all 4,312)"**. Sends analysis params (url, parent_tag, field_map) to `/api/export_csv` — server serves from cache, no re-fetch.

`lastAnalysisParams` stored in JS after each analysis run and reused for all export calls.

UI: dark theme, monospace for data values, dense tool aesthetic.

---

## Rules

- Single iterparse pass in Breakdown — never iterate the feed more than once per analyze call
- `rows` (top 25) sent to frontend; `all_rows` (full) kept server-side only
- `root` is always `None` — never stored, never serialized
- `raw_bytes` is first 512 bytes only — never the full feed
- All exceptions caught in agents — append to errors, never crash pipeline
- No auth, no DB, no Docker, no Redis
- URL feeds: no content stored — re-streamed on each analyze and export (served from cache after first run)
- Paste feeds: content stored in RAM up to 10 MB
- See `MEMORY.md` for field aliases, feed schemas, CPC/CPA quirks
