"""Per-browser settings kept in cookies, so a returning visitor gets their last view.

There is no database and no login: a setting lives in one browser on one device.
Streamlit can read cookies (st.context.cookies, from the request that opened the
session) but not set them, so writes go out as a small script at the end of a run.
"""
import json
from urllib.parse import quote, unquote

import streamlit as st

PREFIX = "sw_"
# Browsers cap cookie lifetime at 400 days; asking for more is silently shortened.
MAX_AGE_SECONDS = 400 * 24 * 60 * 60
_PENDING_KEY = "_browser_store_pending"


def read(name, default=None):
    """Value saved under name, or default when absent or unreadable."""
    raw = st.context.cookies.get(PREFIX + name)
    if raw is None:
        return default
    try:
        return json.loads(unquote(raw))
    except ValueError:
        return default


def write(name, value):
    """Queue value to be saved; flush() sends it. Safe to call from widget callbacks."""
    st.session_state.setdefault(_PENDING_KEY, {})[name] = value


def flush():
    """Send queued writes. Call once, at the end of the script."""
    pending = st.session_state.pop(_PENDING_KEY, None)
    if not pending:
        return
    # quote() with no safe characters leaves only [A-Za-z0-9_.~-] and %XX, so the
    # value cannot break out of the string literal whatever it contains.
    assignments = "".join(
        f"document.cookie = '{PREFIX}{name}={quote(json.dumps(value, separators=(',', ':')), safe='')}"
        f"; path=/; max-age={MAX_AGE_SECONDS}; SameSite=Lax' + secure;"
        for name, value in pending.items()
    )
    st.html(
        "<script>(function () {"
        "var secure = location.protocol === 'https:' ? '; Secure' : '';"
        f"{assignments}"
        "})();</script>",
        unsafe_allow_javascript=True,
    )
