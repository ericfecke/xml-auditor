import hashlib
import io
import re
import urllib.request
import zlib
from copy import deepcopy

MAX_DECOMPRESSED = 50 * 1024 * 1024  # 50 MB decompressed cap
CHUNK = 65536                          # 64 KB read chunks


def run(state, url=None, xml_text=None):
    state = deepcopy(state)
    try:
        if url:
            state["source_url"] = url
            state["source_label"] = _hostname(url)
            content_bytes, is_gzip, truncated = _fetch_url(url)
        elif xml_text:
            state["source_url"] = None
            state["source_label"] = "paste"
            raw = xml_text.encode("utf-8") if isinstance(xml_text, str) else xml_text
            is_gzip = raw[:2] == b"\x1f\x8b"
            if is_gzip:
                content_bytes = zlib.decompress(raw, zlib.MAX_WBITS | 16)[:MAX_DECOMPRESSED]
                truncated = len(raw) > MAX_DECOMPRESSED
            else:
                content_bytes = raw[:MAX_DECOMPRESSED]
                truncated = len(raw) > MAX_DECOMPRESSED
        else:
            state["errors"].append({
                "agent": "intake",
                "message": "No URL or XML text provided",
                "severity": "error",
            })
            return state

        state["content_bytes"] = content_bytes
        state["raw_bytes"] = content_bytes[:4096]   # small sample — never serialized
        state["cache_key"] = hashlib.sha256(content_bytes).hexdigest()
        state["is_gzip"] = is_gzip
        state["truncated"] = truncated
        state["encoding"] = _sniff_encoding(content_bytes)

        if truncated:
            state["errors"].append({
                "agent": "intake",
                "message": "Feed exceeds 50 MB — analysis based on first 50 MB of content",
                "severity": "warn",
            })

    except Exception as exc:
        state["errors"].append({
            "agent": "intake",
            "message": str(exc),
            "severity": "error",
        })

    return state


# ---------------------------------------------------------------------------
# Fetch helpers
# ---------------------------------------------------------------------------

def _fetch_url(url):
    req = urllib.request.Request(url, headers={"User-Agent": "XMLAuditor/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        first2 = resp.read(2)
        is_gzip = first2 == b"\x1f\x8b"
        if is_gzip:
            content_bytes, truncated = _stream_decompress(resp, first2)
        else:
            content_bytes, truncated = _stream_plain(resp, first2)
    return content_bytes, is_gzip, truncated


def _stream_plain(resp, already_read):
    """Read plain XML up to MAX_DECOMPRESSED bytes."""
    chunks = [already_read]
    total = len(already_read)
    truncated = False
    while True:
        chunk = resp.read(CHUNK)
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
        if total >= MAX_DECOMPRESSED:
            truncated = True
            break
    data = b"".join(chunks)
    return data[:MAX_DECOMPRESSED], truncated


def _stream_decompress(resp, already_read):
    """Stream-decompress gzip response, stopping at MAX_DECOMPRESSED bytes."""
    decomp = zlib.decompressobj(zlib.MAX_WBITS | 16)  # 16 = gzip auto-header
    out_chunks = []
    total_out = 0
    truncated = False

    for raw_input in (already_read, None):  # prime with already_read, then loop
        if raw_input is not None:
            chunk = raw_input
        else:
            while total_out < MAX_DECOMPRESSED:
                chunk = resp.read(CHUNK)
                if not chunk:
                    break
                try:
                    piece = decomp.decompress(chunk)
                except zlib.error:
                    break
                remaining = MAX_DECOMPRESSED - total_out
                if len(piece) >= remaining:
                    out_chunks.append(piece[:remaining])
                    total_out = MAX_DECOMPRESSED
                    truncated = True
                    break
                out_chunks.append(piece)
                total_out += len(piece)
            break

        try:
            piece = decomp.decompress(chunk)
        except zlib.error:
            break
        out_chunks.append(piece)
        total_out += len(piece)

    return b"".join(out_chunks), truncated


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

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
