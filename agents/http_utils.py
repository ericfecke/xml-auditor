"""
Shared HTTP request builder for all agents.

Handles URLs with embedded credentials (user:pass@host), including passwords
that contain percent-encoded characters such as %2B (+) and %3D (=).

Python's urllib decodes percent-encoding before parsing the URL authority,
which causes it to misread the decoded '+' or '=' as a port separator and
raise: nonnumeric port: '+F=34MnQG7VcTc@feed34.nexxt.com'

Fix: extract and decode credentials ourselves, strip them from the URL, and
send them as an Authorization: Basic header instead.
"""

import base64
import urllib.parse
import urllib.request


def build_request(url, timeout=None):
    """
    Return a urllib.request.Request for *url*, correctly handling
    user:pass@ credentials even when the password contains percent-encoded
    special characters.

    - Credentials are extracted via urlparse (safe — parses before decoding)
    - Username/password are percent-decoded with urllib.parse.unquote
    - A clean URL (without userinfo) + Authorization header is used
    """
    headers = {"User-Agent": "XMLAuditor/1.0"}
    parsed  = urllib.parse.urlparse(url)

    if parsed.username or parsed.password:
        # unquote decodes %2B → +, %3D → =, etc.
        username = urllib.parse.unquote(parsed.username or "")
        password = urllib.parse.unquote(parsed.password or "")

        # Rebuild netloc without userinfo
        netloc = parsed.hostname or ""
        if parsed.port:
            netloc = f"{netloc}:{parsed.port}"

        clean_url = urllib.parse.urlunparse((
            parsed.scheme,
            netloc,
            parsed.path,
            parsed.params,
            parsed.query,
            parsed.fragment,
        ))

        token = base64.b64encode(
            f"{username}:{password}".encode("utf-8")
        ).decode("ascii")
        headers["Authorization"] = f"Basic {token}"
        url = clean_url

    return urllib.request.Request(url, headers=headers)


def hostname_from_url(url):
    """Return just the hostname from a URL, stripping any credentials."""
    try:
        return urllib.parse.urlparse(url).hostname or url
    except Exception:
        return url
