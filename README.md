# XML Auditor

A multi-agent Flask tool for auditing job feed XMLs. Paste a URL or raw XML, pick your field mappings, get aggregated cards showing counts and average CPC/CPA per title, company, and CPC value. Exports full data to CSV.

Built for ad ops analysts doing quick feed sanity checks. Handles feeds of any size — including gzip-compressed feeds and multi-hundred-MB XML files — via streaming.

---

## How It Works

**Step 1 — Probe**
Enter a feed URL (or paste XML) and click **Probe Feed**. The tool fetches just enough to detect:
- Root tag and parent node candidates (click a chip to select)
- All available field tags with sample values (auto-matches title, company, CPC, CPA by name)

**Step 2 — Analyze**
Click **Run Analysis**. Six cards render:

| Card | What it shows |
|---|---|
| Total Node Count | Single large number — total jobs in the feed |
| Job Title × CPC | Top 25 titles by count, with avg CPC |
| Job Title × CPA | Top 25 titles by count, with avg CPA |
| Company × CPC | Top 25 companies by count, with avg CPC |
| Company × CPA | Top 25 companies by count, with avg CPA |
| CPC Value Distribution | All distinct CPC values and how often they appear |

Each card has an **Export CSV (all N)** button — exports every row, not just the top 25 displayed.

**QA Summary** appears above the cards showing a confidence score and any flagged issues (missing fields, outlier CPC/CPA values, low node count, etc.).

---

## Agent Pipeline

```
Intake → Reader → Breakdown → QA → Flask → Frontend
```

| Agent | Role |
|---|---|
| **Intake** | URL mode: peeks 2 bytes (gzip detect), stores URL only. Paste mode: stores content (10 MB cap). |
| **Reader** | Streams full feed via `iterparse` — builds tag inventory, parent candidates, field samples. Never loads full XML into memory. |
| **Breakdown** | Re-streams feed from URL, single iterparse pass, computes all 6 cards simultaneously. Clears each node after processing. |
| **QA** | Scores confidence 0–1. Flags missing fields, outliers, empty feeds. |
| **Orchestrator** | Two-level cache: post-reader metadata (15 min) + post-breakdown results (15 min). Export is instant — no re-fetch. |

---

## Large Feed Support

Feeds of any size are supported. The tool streams directly into the XML parser — RAM usage stays flat regardless of feed size.

- **talent.com** (1.1 GB uncompressed XML) — 300,000 nodes, ~84s on Render free tier
- **jobget.com** (125 MB gzip) — full feed, streamed and decompressed on the fly
- **Paste mode** — capped at 10 MB (use URL mode for large feeds)

---

## Setup — Run Locally

```bash
git clone https://github.com/ericfecke/xml-auditor.git
cd xml-auditor
pip install -r requirements.txt
python app.py
```

Open `http://localhost:5000`.

**Requirements:** Python 3.8+, Flask, gunicorn (gunicorn only needed for hosted deployments).

---

## Hosted Deployment (Render)

The app is deployable to Render's free tier via `render.yaml`.

**One-time setup:**
1. Go to [render.com](https://render.com) → New → Web Service
2. Connect GitHub → select `ericfecke/xml-auditor`
3. Render auto-detects `render.yaml` — click **Create Web Service**

**Start command** (if prompted manually):
```
flask run --host=0.0.0.0 --port=$PORT
```

**Environment variable** (if prompted):
```
FLASK_APP = app
```

**Free tier note:** The service sleeps after 15 minutes of inactivity. First request after sleep takes ~30 seconds to wake up. Subsequent requests are fast.

---

## Sharing With Co-Workers

| Scenario | How |
|---|---|
| Same office/WiFi | Run locally with `python app.py`, share your machine's IP: `http://192.168.x.x:5000` |
| Remote co-workers, ad hoc | Use [ngrok](https://ngrok.com): `ngrok http 5000` — gives a temporary public URL |
| Always-on team link | Deploy to Render (see above) |

---

## Data & Privacy

**Nothing is written to disk or a database — ever.**

| Data | Where | How long |
|---|---|---|
| Feed URL | Server RAM only | 15 min (cache TTL) |
| Sample field values (first 5 per tag) | Server RAM only | 15 min |
| Aggregated breakdown results | Server RAM only | 15 min |
| Raw feed content (URL mode) | Never stored — streamed and discarded | — |
| Paste content | Server RAM only | 15 min |

Render captures standard HTTP access logs (method, path, status, response time). Request bodies are not logged — feed URLs and paste content do not appear in Render's logs.

The in-memory cache clears automatically when the server restarts (happens on every deploy and after inactivity on the free tier).

**For sensitive feeds:** run locally — nothing leaves your machine.

---

## Project Files

```
xml-auditor/
├── CLAUDE.md               ← Agent architecture spec (Claude Code init)
├── MEMORY.md               ← Domain knowledge: feed schemas, field aliases, QA patterns
├── README.md               ← This file
├── app.py                  ← Flask routes (thin — no business logic)
├── render.yaml             ← Render deployment config
├── requirements.txt        ← flask, gunicorn
├── agents/
│   ├── intake_agent.py     ← URL peek / paste ingest
│   ├── reader_agent.py     ← Streaming iterparse, tag inventory
│   ├── breakdown_agent.py  ← Streaming single-pass aggregation, 6 cards
│   ├── qa_agent.py         ← Confidence scoring, 7 QA checks
│   └── orchestrator.py     ← Two-level cache, probe + pipeline entry points
└── templates/
    └── index.html          ← Vanilla JS, dark theme, two-step UI
```

---

## Stack

- Python 3.8+ — stdlib only for XML parsing (`xml.etree.ElementTree`, `gzip`, `zlib`)
- Flask + gunicorn
- Vanilla JS — no frameworks, no build step
