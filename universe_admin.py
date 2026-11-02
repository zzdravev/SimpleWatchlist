"""Owner-only editing of the shared ticker list, saved as a commit to GitHub.

Streamlit Cloud's filesystem resets on every restart, so a change written to disk
would vanish. Instead the panel commits data/universe.csv through GitHub's contents
API. That push starts the record job (its paths include the file), so a new ticker
has analyst data and event dates within minutes, and Streamlit Cloud redeploys the
app with the new list.

Needs two secrets: ADMIN_PASSWORD, and GITHUB_TOKEN, a fine-grained token limited
to this repository with Contents read and write. GITHUB_REPO and GITHUB_BRANCH
override the defaults below.
"""
import base64
import csv
import hmac
import io
import os
import time

import requests
import streamlit as st

import finnhub_client
from watchlist import SYMBOL

DEFAULT_REPO = "zzdravev/SimpleWatchlist"
DEFAULT_BRANCH = "main"
PATH = "data/universe.csv"
FIELDS = ["ticker", "name", "sector", "group"]
ADDED_GROUP = "Added"
MAX_ATTEMPTS = 5


class SaveError(Exception):
    pass


def _secret(name, default=""):
    try:
        value = st.secrets.get(name)
    except Exception:  # no secrets file at all
        value = None
    return str(value or os.environ.get(name) or default).strip()


def configured():
    return bool(_secret("ADMIN_PASSWORD") and _secret("GITHUB_TOKEN"))


def password_matches(entered):
    expected = _secret("ADMIN_PASSWORD")
    return bool(expected) and hmac.compare_digest(entered.encode(), expected.encode())


def _api(method, **kwargs):
    repo = _secret("GITHUB_REPO", DEFAULT_REPO)
    headers = {
        "Authorization": f"Bearer {_secret('GITHUB_TOKEN')}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    try:
        return requests.request(method, f"https://api.github.com/repos/{repo}/contents/{PATH}",
                                headers=headers, timeout=15, **kwargs)
    except requests.RequestException as e:
        raise SaveError(f"GitHub could not be reached ({type(e).__name__}).") from None


def read_remote():
    """(rows, sha) of the file as it is on GitHub now, not as this deployment has it."""
    response = _api("GET", params={"ref": _secret("GITHUB_BRANCH", DEFAULT_BRANCH)})
    if response.status_code != 200:
        raise SaveError(f"Reading the list from GitHub failed (HTTP {response.status_code}).")
    payload = response.json()
    text = base64.b64decode(payload["content"]).decode("utf-8")
    return list(csv.DictReader(io.StringIO(text))), payload["sha"]


def to_csv(rows):
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=FIELDS, lineterminator="\n", extrasaction="ignore")
    writer.writeheader()
    writer.writerows(sorted(rows, key=lambda r: r["ticker"]))
    return out.getvalue()


def write_remote(rows, sha, message):
    """Commit the new list. sha is the version read: if someone saved in between,
    GitHub refuses with 409 and nothing is overwritten."""
    response = _api("PUT", json={
        "message": message,
        "content": base64.b64encode(to_csv(rows).encode("utf-8")).decode("ascii"),
        "sha": sha,
        "branch": _secret("GITHUB_BRANCH", DEFAULT_BRANCH),
    })
    if response.status_code == 409:
        raise SaveError("The list changed on GitHub meanwhile. Nothing was saved; try again.")
    if response.status_code not in (200, 201):
        raise SaveError(f"Saving to GitHub failed (HTTP {response.status_code}). "
                        "Check that GITHUB_TOKEN can write this repository's contents.")


def has_prices(ticker):
    """Whether Yahoo returns recent daily prices, the one thing every row needs."""
    import yfinance as yf
    try:
        data = yf.download(ticker, period="5d", interval="1d", progress=False, auto_adjust=True)
    except Exception:
        return False
    return data is not None and not data.dropna(how="all").empty


def add_ticker(symbol, name, sector):
    symbol = symbol.strip().upper()
    if not SYMBOL.match(symbol):
        raise SaveError(f"{symbol or 'That'} is not a valid Yahoo symbol.")
    rows, sha = read_remote()
    if any(r["ticker"] == symbol for r in rows):
        raise SaveError(f"{symbol} is already on the list.")
    if not has_prices(symbol):
        raise SaveError(f"Yahoo has no recent prices for {symbol}, so it was not added.")
    profile = finnhub_client.profile(symbol) or {}
    rows.append({
        "ticker": symbol,
        "name": name.strip() or profile.get("name") or symbol,
        "sector": sector.strip() or profile.get("finnhubIndustry") or "",
        "group": ADDED_GROUP,
    })
    write_remote(rows, sha, f"Add {symbol} to the shared ticker list\n\nMade from the app's admin panel.")
    return symbol


def remove_tickers(symbols):
    rows, sha = read_remote()
    present = {r["ticker"] for r in rows}
    gone = [s for s in symbols if s in present]
    if not gone:
        raise SaveError("None of those tickers are on the list any more.")
    rows = [r for r in rows if r["ticker"] not in gone]
    write_remote(rows, sha, f"Remove {', '.join(gone)} from the shared ticker list\n\n"
                            "Made from the app's admin panel.")
    return gone


def render(shared):
    """The panel body; shared is the list as this deployment currently has it."""
    if not configured():
        st.caption("Editing the shared list needs ADMIN_PASSWORD and GITHUB_TOKEN in the app's secrets.")
        return

    if not st.session_state.get("admin_unlocked"):
        attempts = st.session_state.get("admin_attempts", 0)
        if attempts >= MAX_ATTEMPTS:
            st.caption("Too many wrong passwords. Reload the page to try again.")
            return
        with st.form("admin-login", clear_on_submit=True, border=False):
            entered = st.text_input("Admin password", type="password")
            if st.form_submit_button("Unlock"):
                if password_matches(entered):
                    st.session_state.admin_unlocked = True
                    st.rerun()
                st.session_state.admin_attempts = attempts + 1
                time.sleep(1)  # makes guessing slow
                st.error("Wrong password.")
        return

    notice = st.session_state.pop("admin_notice", None)
    if notice:
        st.success(notice)

    add_col, remove_col = st.columns(2)
    with add_col:
        with st.form("admin-add", clear_on_submit=True):
            st.markdown("**Add a ticker**")
            symbol = st.text_input("Yahoo symbol", placeholder="e.g. ASML or SAP.DE")
            name = st.text_input("Name (optional)", help="Filled in from Finnhub when left empty.")
            sector = st.text_input("Sector (optional)")
            if st.form_submit_button("Add to the shared list"):
                try:
                    with st.spinner("Checking prices and saving..."):
                        added = add_ticker(symbol, name, sector)
                    st.session_state.admin_notice = (
                        f"Added {added}. Its analyst data and event dates arrive within a few "
                        "minutes, and the app reloads with the new list once Streamlit Cloud "
                        "picks up the change.")
                    st.rerun()
                except SaveError as e:
                    st.error(str(e))
    with remove_col:
        with st.form("admin-remove"):
            st.markdown("**Remove tickers**")
            chosen = st.multiselect("From the shared list", list(shared),
                                    format_func=lambda t: f"{t} · {shared[t].get('name', '')}")
            if st.form_submit_button("Remove") and chosen:
                try:
                    with st.spinner("Saving..."):
                        gone = remove_tickers(chosen)
                    st.session_state.admin_notice = (
                        f"Removed {', '.join(gone)}. Visitors who already watch them keep them "
                        "as their own additions.")
                    st.rerun()
                except SaveError as e:
                    st.error(str(e))
    st.caption("Each change is a commit to data/universe.csv on GitHub, so it can be "
               "reviewed or reverted there.")
