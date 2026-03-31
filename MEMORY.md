# XML Auditor — Domain Memory

## What Are We Auditing?

Job feed XMLs. These are partner-generated feeds containing job listings sent to aggregators (us). Each feed varies in structure — some are standard RSS, some are proprietary schemas. The auditor needs to handle both without assumptions.

---

## Common Feed Schemas

### Schema A: Direct job nodes
```xml
<jobs>
  <job>
    <title>Software Engineer</title>
    <company>Acme Corp</company>
    <cpc>0.35</cpc>
    <cpa>2.50</cpa>
    <source>Indeed</source>
    <location>Austin, TX</location>
    <category>Technology</category>
    <url>https://...</url>
    <date>2024-01-15</date>
  </job>
</jobs>
```

### Schema B: RSS/item style
```xml
<rss>
  <channel>
    <item>
      <title>...</title>
      <advertiser>Acme Corp</advertiser>   <!-- company may be "advertiser" -->
      <bid>0.35</bid>                      <!-- cpc may be "bid" -->
      <revenue>2.50</revenue>              <!-- cpa may be "revenue" -->
    </item>
  </channel>
</rss>
```

### Schema C: Deeply nested
```xml
<feed>
  <listings>
    <listing id="123">
      <details>
        <job_title>...</job_title>          <!-- title may be nested -->
        <employer_name>...</employer_name>
      </details>
      <pricing>
        <cpc_value>0.42</cpc_value>
        <cpa_value>3.00</cpa_value>
      </pricing>
    </listing>
  </listings>
</feed>
```

---

## Known Field Name Aliases

The Reader and Breakdown agents should surface these as candidates. Don't hardcode — detect from the feed.

| Logical field | Common XML tag names |
|---|---|
| Job title | `title`, `job_title`, `jobtitle`, `position`, `job_name` |
| Company | `company`, `advertiser`, `employer`, `employer_name`, `client` |
| CPC | `cpc`, `bid`, `cpc_value`, `cost_per_click`, `price` |
| CPA | `cpa`, `revenue`, `cpa_value`, `cost_per_apply`, `conversion_value` |
| Source | `source`, `partner`, `feed_source`, `network`, `origin` |
| Location | `location`, `city`, `state`, `geo`, `region` |
| Category | `category`, `sector`, `job_type`, `industry`, `vertical` |
| Date | `date`, `pub_date`, `pubDate`, `posted_date`, `date_posted` |

---

## CPC/CPA Data Patterns

- Values are almost always decimals: `0.35`, `1.20`, `5.00`
- Sometimes formatted with currency: `$0.35` — strip the `$` before parsing
- Sometimes comma-formatted: `1,200.00` — strip commas
- Zeroes (`0`, `0.00`) are valid — don't treat as missing
- Empty string or missing tag = truly missing — represent as `None` in output
- CPA is often much larger than CPC (apply costs more than a click)
- Red flag: CPC > $5.00 is unusually high for job feeds — worth a QA flag
- Red flag: CPA > $50.00 is unusually high — worth a QA flag

---

## Gzip Patterns

Most feeds that are gzipped will be served at URLs ending in `.xml.gz` or `.gz`, but not always. Don't rely on the URL. Always detect by magic bytes `b"\x1f\x8b"`.

Some feeds are double-encoded (base64 then gzip) — out of scope for now.

---

## Common Parent Node Names

In rough order of frequency seen in the wild:
1. `job`
2. `item`
3. `listing`
4. `result`
5. `record`
6. `vacancy`
7. `position`
8. `offer`

---

## Breakdown Use Cases

What analysts actually want to slice by:

| Breakdown field | What it tells you |
|---|---|
| `source` / `partner` | Which feed source is driving volume |
| `company` / `advertiser` | Which advertisers have the most listings |
| `category` / `sector` | Job category distribution |
| `location` / `city` | Geographic spread |
| `job_type` | Full-time vs part-time etc |
| `cpc` (exact value) | CPC value distribution (use carefully — many unique values) |

---

## QA Red Flags Seen in Practice

- Feed has 1 job node — usually a test feed or fetch error
- All CPC values are 0.00 — pricing not populated in feed
- "(missing)" breakdown > 20% — field not consistently populated
- One advertiser dominates > 80% of feed — normal for single-client feeds, unusual for aggregated feeds
- Encoding issues: common with European partners (XING, Stepstone) — watch for `Ã©` instead of `é`

---

## Output Expectations

The summary table should feel like a pivot table:
- Sorted by count descending
- CPC/CPA shown to 4 decimal places (precision matters for billing)
- `—` displayed in UI (not `null` or `None`) when no CPC/CPA data
- CSV export: use `None` for missing values (analyst will handle in Excel/Sheets)

---

## Cross-Project Notes

- This project shares context with the Ad Ops Anomaly Detection system
- CPC/CPA field names here may match fields in the clicks/request_log schema
- Future: could pipe breakdown output directly into anomaly detection for per-source baselining
