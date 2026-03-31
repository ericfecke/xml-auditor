# XML Auditor — Claude Code Init

## What This Is

Multi-agent Flask app for auditing job feed XMLs. Input: URL or raw paste. Output: a fixed set of aggregated cards rendered on-page. Users are ad ops analysts doing quick feed sanity checks. Feeds are job XML or RSS-style, sometimes gzip. Performance is a hard requirement — feeds can be large.

---

## Pipeline

```
Intake → Reader → Breakdown → QA → Flask → Frontend
```

Each agent is a module in `/agents/`. They share a single `state` dict — receive it, return an updated copy, never mutate in place.

---

## Build Order

1. `agents/intake_agent.py`
2. `agents/reader_agent.py`
3. `agents/breakdown_agent.py`
4. `agents/qa_agent.py`
5. `agents/orchestrator.py`
6. `app.py`
7. `templates/index.html`

---

## State Schema

```python
state = {
    # Intake
    "source_url": str | None,
    "raw_bytes": bytes,
    "content_bytes": bytes,       # decompressed
    "is_gzip": bool,
    "encoding": str,
    "source_label": str,          # URL hostname or "paste"
    "cache_key": str,             # sha256 of raw_bytes
    "errors": [],                 # [{agent, message, severity}]

    # Reader
    "root_tag": str,
    "root": ET.Element,
    "tag_inventory": dict,        # {tag: count} all tags in tree
    "parent_candidates": dict,    # {tag: count} tags with child elements
    "field_candidates": dict,     # {tag: [sample_values]} leaf tags, first 20 nodes

    # Breakdown
    "parent_tag": str,
    "node_count": int,
    "cards": {},                  # {card_id: card_result} — see Card Spec below
    "available_tags": [],

    # QA
    "qa_flags": [],               # [{field, issue, severity, suggested_action?}]
    "confidence": float,          # 0.0–1.0
    "qa_passed": bool,
}
```

---

## Agents

### Intake
Fetch URL (urllib, `User-Agent: XMLAuditor/1.0`, 30s timeout) or accept raw paste. Detect gzip by magic bytes `b"\x1f\x8b"`, decompress. Sniff encoding from XML declaration. Compute `cache_key = sha256(raw_bytes)`. On any error: append to errors, return early.

### Reader
Parse with `xml.etree.ElementTree`. Build `tag_inventory`, `parent_candidates` (3+ children per node AND 10+ occurrences), `field_candidates` (up to 5 sample values per leaf tag, first 20 nodes). Do not guess CPC/CPA fields. On parse error: append to errors, return.

Parent detection heuristics: 3+ children per node, repeats 10+ times, or named `job / item / listing / result / record / vacancy`.

### Breakdown
Compute all 6 default cards in a single pass over `root.iter(parent_tag)`. One iteration — do not loop the tree multiple times. Each card accumulates its own aggregation during that pass. Enforces row caps server-side before returning.

See **Card Spec** section below for exact card definitions.

### QA
Score starts at 1.0. Subtract 0.15 per warn, 0.35 per error, floor at 0.

| Check | Condition | Severity |
|---|---|---|
| Low node count | `node_count < 10` | warn |
| No CPC data | All CPC values missing | warn |
| No CPA data | All CPA values missing | warn |
| High missing rate | title or company missing > 10% | warn |
| CPC outlier | Any avg_cpc > 10× median | warn |
| CPA outlier | Any avg_cpa > 10× median | warn |
| Empty result | `node_count == 0` | error |

If `confidence < 0.5`: set `qa_passed = False`, add `suggested_action` to each flag.

### Orchestrator

```python
def run_pipeline(url, xml_text, parent_tag, field_map):
    # field_map: {title, company, cpc, cpa} — user-chosen tag names
    state = build_initial_state()

    # Check cache before fetching
    cache_key = get_cache_key(url or xml_text)
    if cache_key in FEED_CACHE:
        state = FEED_CACHE[cache_key].copy()
    else:
        state = intake_agent.run(state, url=url, xml_text=xml_text)
        if has_errors(state): return state
        state = reader_agent.run(state)
        if has_errors(state): return state
        FEED_CACHE[cache_key] = state.copy()   # cache after parse

    state = breakdown_agent.run(state, parent_tag=parent_tag, field_map=field_map)
    state = qa_agent.run(state)
    return state
```

---

## Caching

In-memory cache in `orchestrator.py`. Cache key = `sha256(raw_bytes)` for URL feeds, `sha256(xml_text.encode())` for pastes.

```python
import time
FEED_CACHE = {}          # {cache_key: state}
CACHE_TTL  = 900         # 15 minutes

def get_cached(key):
    entry = FEED_CACHE.get(key)
    if entry and time.time() - entry["cached_at"] < CACHE_TTL:
        return entry["state"]
    return None

def set_cache(key, state):
    FEED_CACHE[key] = {"state": state, "cached_at": time.time()}
```

Cache stores the post-Reader state (parsed tree + tag inventory). Breakdown always re-runs against the cached tree — fast because it's already in memory, and field_map can change between runs.

Cache is intentionally simple — no Redis, no disk. This is a local tool. Evict on TTL only.

---

## Card Spec

Six fixed cards. Computed in a single tree pass by Breakdown agent. All caps enforced server-side.

```python
DEFAULT_CARDS = [
    {
        "id": "title_cpc",
        "label": "Job Title × CPC",
        "group_by": "title",          # resolved from field_map
        "metrics": ["count", "avg_cpc"],
        "sort_by": "count",
        "cap": 25,
    },
    {
        "id": "title_cpa",
        "label": "Job Title × CPA",
        "group_by": "title",
        "metrics": ["count", "avg_cpa"],
        "sort_by": "count",
        "cap": 25,
    },
    {
        "id": "company_cpc",
        "label": "Company × CPC",
        "group_by": "company",
        "metrics": ["count", "avg_cpc"],
        "sort_by": "count",
        "cap": 25,
    },
    {
        "id": "company_cpa",
        "label": "Company × CPA",
        "group_by": "company",
        "metrics": ["count", "avg_cpa"],
        "sort_by": "count",
        "cap": 25,
    },
    {
        "id": "cpc_dist",
        "label": "CPC Value Distribution",
        "group_by": "cpc",            # group by exact CPC value
        "metrics": ["count"],
        "sort_by": "cpc_value_asc",   # sort numerically ascending
        "cap": None,                  # show all distinct values
    },
    {
        "id": "total_count",
        "label": "Total Node Count",
        "type": "stat",               # single number — not a table
        "value_key": "node_count",
    },
]
```

Each non-stat card result shape:
```python
{
    "id": "title_cpc",
    "label": "Job Title × CPC",
    "total_unique": 312,             # total distinct values before cap
    "capped": True,                  # whether cap was applied
    "rows": [
        {"value": "Software Engineer", "count": 840, "avg_cpc": 0.38},
        ...
    ]
}
```

---

## Flask (`app.py`) — thin routes only

| Route | Body | Returns |
|---|---|---|
| `GET /` | — | `index.html` |
| `POST /api/probe` | `{url?, xml_text?}` | `{root_tag, is_gzip, parent_candidates, field_candidates, errors}` |
| `POST /api/analyze` | `{url?, xml_text?, parent_tag, field_map}` | `{node_count, cards, qa_flags, confidence, errors}` |
| `POST /api/export_csv` | `{card_id, rows}` | streaming CSV download — never loads full rows into memory |

`field_map` shape: `{"title": "job_title", "company": "advertiser", "cpc": "cpc", "cpa": "cpa"}`

CSV export streams directly from server — raw rows never touch the browser.

---

## Frontend (`templates/index.html`)

Vanilla JS, no frameworks. Two steps:

**Step 1 — Probe**
URL input or paste toggle → "Probe Feed" → shows:
- Detected parent node chips (click to select)
- Field mapping dropdowns: Title field, Company field, CPC field, CPA field (auto-matched by name from `field_candidates`, user can override)

**Step 2 — Analyze**
"Run Analysis" → cards render independently as each resolves. Do not wait for all 6 before showing anything.

Each card renders as a compact table with a header showing label + row count. Total Count card renders as a single large stat.

Card table columns:
- Title/Company cards: Value | Count | Avg CPC or Avg CPA (show `—` for null)
- CPC dist card: CPC Value | Count

**Performance rules for frontend:**
- Cards render one at a time as JSON arrives — no blocking
- Tables are static HTML — no JS sorting, filtering, or re-rendering
- No raw rows in DOM — aggregated data only
- Export button per card → hits `/api/export_csv` → file download, page unaffected

UI: dark theme, monospace for data values, dense tool aesthetic.

---

## Rules

- Single tree pass in Breakdown — never iterate the XML tree more than once per analyze call
- Caps enforced server-side — browser never receives more than 25 rows per card (except CPC dist)
- `root` and `raw_bytes` never serialized to JSON
- All exceptions caught in agents — append to errors, never crash pipeline
- No auth, no DB, no Docker
- See `MEMORY.md` for field aliases, feed schemas, CPC/CPA quirks
