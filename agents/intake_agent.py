import gzip
import hashlib
import re
import urllib.request
from copy import deepcopy


def run(state, url=None, xml_text=None):
    state = deepcopy(state)
    try:
        if url:
            state["source_url"] = url
            state["source_label"] = _hostname(url)
            raw_bytes = _fetch_url(url)
        elif xml_text:
            state["source_url"] = None
            state["source_label"] = "paste"
            raw_bytes = xml_text.encode("utf-8") if isinstance(xml_text, str) else xml_text
        else:
            state["errors"].append({
                "agent": "intake",
                "message": "No URL or XML text provided",
                "severity": "error",
            })
            return state

        state["raw_bytes"] = raw_bytes
        state["cache_key"] = hashlib.sha256(raw_bytes).hexdigest()

        if raw_bytes[:2] == b"\x1f\x8b":
            state["is_gzip"] = True
            state["content_bytes"] = gzip.decompress(raw_bytes)
        else:
            state["is_gzip"] = False
            state["content_bytes"] = raw_bytes

        state["encoding"] = _sniff_encoding(state["content_bytes"])

    except Exception as exc:
        state["errors"].append({
            "agent": "intake",
            "message": str(exc),
            "severity": "error",
        })

    return state


def _fetch_url(url):
    req = urllib.request.Request(url, headers={"User-Agent": "XMLAuditor/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()


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
