# XML Auditor

A multi-agent Flask tool for auditing job feed XML files. Paste a URL or raw XML, pick your params, get a breakdown table with counts and average CPC/CPA per field. Exports to CSV.

## How It Works

Four agents run in sequence:

| Agent | Role |
|---|---|
| **Intake** | Fetches the feed, detects gzip, sniffs encoding |
| **Reader** | Parses the XML tree, maps all tags, surfaces field candidates |
| **Breakdown** | Computes counts + avg CPC/CPA per breakdown value |
| **QA** | Checks output for gaps, anomalies, returns a confidence score |

## Setup

```bash
pip install -r requirements.txt
python app.py
```

Then open `http://localhost:5000`.

## Usage

1. Enter a feed URL (or paste XML directly)
2. Click **Probe Feed** — the tool detects parent nodes and available fields
3. Select your params: parent node, breakdown field, CPC/CPA fields
4. Click **Run Analysis**
5. Review summary table + QA flags
6. Export to CSV if needed

## Project Files

```
xml_auditor/
├── CLAUDE.md           ← Claude Code init prompt (agent architecture)
├── MEMORY.md           ← Domain knowledge: feed schemas, field aliases, QA patterns
├── app.py              ← Flask orchestrator (thin routes only)
├── agents/
│   ├── intake_agent.py
│   ├── reader_agent.py
│   ├── breakdown_agent.py
│   ├── qa_agent.py
│   └── orchestrator.py
├── templates/
│   └── index.html
└── requirements.txt
```

## Stack

- Python 3.10+
- Flask (no other dependencies — stdlib XML parsing only)
- Vanilla JS frontend (no framework)
