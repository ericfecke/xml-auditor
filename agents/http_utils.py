"""
Shared URL utilities for all agents.

Handles:
- HTTP/HTTPS with embedded credentials (user:pass@host), including
  percent-encoded passwords like %2B (+) and %3D (=)
- FTP (ftp://) using ftplib.FTP directly — avoids urllib's FTP handler
  which fails with "550 No such directory" when paths don't match its
  expected CWD navigation pattern
"""

import base64
import ftplib
import gzip
import urllib.parse
import urllib.request
from contextlib import contextmanager


# ---------------------------------------------------------------------------
# HTTP / HTTPS
# ---------------------------------------------------------------------------

def build_request(url):
    """
    Return a urllib.request.Request for *url*, correctly handling
    user:pass@ credentials even when the password contains percent-encoded
    special characters.

    - Credentials extracted via urlparse (safe — parses before decoding)
    - Username/password decoded with urllib.parse.unquote (%2B→+, %3D→=)
    - Clean URL (no userinfo) + Authorization: Basic header used instead
    """
    headers = {"User-Agent": "XMLAuditor/1.0"}
    parsed  = urllib.parse.urlparse(url)

    if parsed.username or parsed.password:
        username = urllib.parse.unquote(parsed.username or "")
        password = urllib.parse.unquote(parsed.password or "")

        netloc = parsed.hostname or ""
        if parsed.port:
            netloc = f"{netloc}:{parsed.port}"

        clean_url = urllib.parse.urlunparse((
            parsed.scheme, netloc,
            parsed.path, parsed.params,
            parsed.query, parsed.fragment,
        ))

        token = base64.b64encode(
            f"{username}:{password}".encode("utf-8")
        ).decode("ascii")
        headers["Authorization"] = f"Basic {token}"
        url = clean_url

    return urllib.request.Request(url, headers=headers)


# ---------------------------------------------------------------------------
# FTP
# ---------------------------------------------------------------------------

def _open_ftp(url):
    """
    Open and return a logged-in ftplib.FTP connection from a ftp:// URL.
    Passive mode is enabled by default (works through most firewalls).
    Credentials are percent-decoded before login.
    """
    parsed   = urllib.parse.urlparse(url)
    host     = parsed.hostname or ""
    port     = parsed.port or 21
    username = urllib.parse.unquote(parsed.username or "anonymous")
    password = urllib.parse.unquote(parsed.password or "")

    ftp = ftplib.FTP()
    ftp.connect(host, port, timeout=120)
    ftp.login(username, password)
    ftp.set_pasv(True)
    return ftp


# ---------------------------------------------------------------------------
# Unified stream opener (HTTP + FTP)
# ---------------------------------------------------------------------------

@contextmanager
def open_stream(url, is_gzip=False):
    """
    Context manager that yields a readable binary file-like object for *url*.

    Works for HTTP, HTTPS, and FTP. Transparently decompresses gzip when
    is_gzip=True. Caller can pass the yielded object directly to
    ET.iterparse() or gzip.GzipFile().

    FTP path:
      Uses ftplib.FTP.transfercmd('RETR <path>') which issues a direct
      RETR command without CWD navigation — avoids the "550 No such
      directory" error that Python's urllib FTP handler produces.

    HTTP/HTTPS path:
      Uses urllib.request with credential extraction via build_request().
    """
    parsed = urllib.parse.urlparse(url)

    if parsed.scheme == "ftp":
        ftp  = None
        sock = None
        try:
            ftp  = _open_ftp(url)
            path = urllib.parse.unquote(parsed.path)
            sock = ftp.transfercmd(f"RETR {path}")
            src  = sock.makefile("rb")
            yield gzip.GzipFile(fileobj=src) if is_gzip else src
        finally:
            if sock:
                try: sock.close()
                except Exception: pass
            if ftp:
                try: ftp.quit()
                except Exception: pass

    else:  # http / https
        req = build_request(url)
        with urllib.request.urlopen(req, timeout=120) as resp:
            yield gzip.GzipFile(fileobj=resp) if is_gzip else resp


# ---------------------------------------------------------------------------
# Misc helpers
# ---------------------------------------------------------------------------

def hostname_from_url(url):
    """Return just the hostname from a URL, stripping any credentials."""
    try:
        return urllib.parse.urlparse(url).hostname or url
    except Exception:
        return url


def is_ftp(url):
    """Return True if url uses the ftp:// scheme."""
    return urllib.parse.urlparse(url).scheme == "ftp"
