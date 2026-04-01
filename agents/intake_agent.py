import gzip
import hashlib
import re
import urllib.request
from copy import deepcopy

PASTE_MAX = 10 * 1024 * 1024   # 10 MB cap on raw paste (URL feeds stream — no cap)


def run(state, url=None, xml_text=None):
    state = deepcopy(state)
    try:
        if url:
            state["source_url"] = url
            state["source_label"] = _hostname(url)
            # Peek at first 2 bytes only — detect gzip without loading feed
            is_gzip, cache_key = _peek_url(url)
            state["is_gzip"] = is_gzip
            state["cache_key"] = cache_key
            state["content_bytes"] = b""   # URL feeds stream — nothing stored here
            state["encoding"] = "utf-8"    # sniffed properly by reader during stream

        elif xml_text:
            state["source_url"] = None
            state["source_label"] = "paste"
            raw = xml_text.encode("utf-8") if isinstance(xml_text, str) else xml_text
            if len(raw) > PASTE_MAX:
                raw = raw[:PASTE_MAX]
                state["errors"].append({
                    "agent": "intake",
                    "message": "Paste exceeds 10 MB — truncated. Use a URL for large feeds.",
                    "severity": "warn",
                })
            is_gzip = raw[:2] == b"\x1f\x8b"
            if is_gzip:
                content = gzip.decompress(raw)
            else:
                content = raw
            state["is_gzip"] = is_gzip
            state["content_bytes"] = content
            state["cache_key"] = hashlib.sha256(content).hexdigest()
            state["encoding"] = _sniff_encoding(content)
            state["raw_bytes"] = raw[:512]

        else:
            state["errors"].append({
                "agent": "intake",
                "message": "No URL or XML text provided",
                "severity": "error",
            })

    except Exception as exc:
        state["errors"].append({
            "agent": "intake",
            "message": str(exc),
            "severity": "error",
        })

    return state


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _peek_url(url):
    """Fetch first 2 bytes to detect gzip. Returns (is_gzip, cache_key)."""
    req = urllib.request.Request(url, headers={"User-Agent": "XMLAuditor/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        first2 = resp.read(2)
    is_gzip = first2 == b"\x1f\x8b"
    cache_key = hashlib.sha256(url.encode()).hexdigest()
    return is_gzip, cache_key


def _sniff_encoding(content_bytes):
    try:
        header = content_bytes[:200].decode("ascii", errors="replace")
        m = re.search(r'<\?xml[^>]+encoding=["\']([^"\']+)["\']', header, re.IGNORECASE)
        if m:
            return m.group(1).lower()
    except Exception:
        pass
    return "utf-8"


def _hostname(url):
    try:
        m = re.search(r"https?://([^/]+)", url)
        return m.group(1) if m else url
    except Exception:
        return url
