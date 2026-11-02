"""Per-browser settings, so a returning visitor gets their last view.

There is no database and no login: a setting lives in one browser on one device,
in localStorage. The browser itself reads it and hands it to Python through a small
component. Reading cookies on the server (st.context.cookies) works locally but not
on Streamlit Community Cloud, whose proxy strips cookies before they reach the app,
which is why the first version of this module forgot everything once deployed.

Usage: call sync() once near the top of the script. It returns False on the very
first run of a session, before the browser has answered; the component then
reruns the script with the saved values, and read() returns them from then on.
write() queues a value, which the next sync() sends to the browser.
"""
import streamlit as st

PREFIX = "sw_"
_PENDING_KEY = "_browser_store_pending"
_SAVED_KEY = "_browser_store_saved"

# Runs in the page. Applies any queued writes, then reports everything saved under
# the prefix. Cookies written by the first version are read too, so nothing saved
# before the switch is lost; localStorage wins where both exist. Every step is
# guarded: storage can be blocked (private windows, strict settings), and the app
# must still get an answer so it does not wait for one.
_JS = """
export default function (component) {
  const { data, setStateValue } = component;
  const PREFIX = "%(prefix)s";
  let store = null;
  try { store = window.localStorage; } catch (e) { store = null; }

  const writes = (data && data.writes) || {};
  for (const [name, value] of Object.entries(writes)) {
    try { if (store) store.setItem(PREFIX + name, JSON.stringify(value)); } catch (e) {}
  }

  const saved = {};
  try {
    for (const part of document.cookie.split("; ")) {
      const eq = part.indexOf("=");
      const name = eq > 0 ? part.slice(0, eq) : "";
      if (!name.startsWith(PREFIX)) continue;
      try { saved[name.slice(PREFIX.length)] = JSON.parse(decodeURIComponent(part.slice(eq + 1))); } catch (e) {}
    }
  } catch (e) {}
  try {
    if (store) {
      for (let i = 0; i < store.length; i++) {
        const name = store.key(i);
        if (!name || !name.startsWith(PREFIX)) continue;
        try { saved[name.slice(PREFIX.length)] = JSON.parse(store.getItem(name)); } catch (e) {}
      }
    }
  } catch (e) {}
  setStateValue("saved", saved);
}
""" % {"prefix": PREFIX}

_component = st.components.v2.component("browser_store", js=_JS)


def sync():
    """Send queued writes and pick up what the browser has saved.

    True once the browser has answered in this session.
    """
    pending = st.session_state.pop(_PENDING_KEY, None) or {}
    with st.container(key="browser-store", height=1, border=False):
        # The callback is required for the state to round-trip; the rerun it
        # causes is what delivers the saved values.
        result = _component(key="browser-store-component", data={"writes": pending},
                            default={"saved": None}, on_saved_change=lambda: None)
    saved = getattr(result, "saved", None)
    if isinstance(saved, dict):
        # Writes sent this run are not in the browser's answer yet; keep them visible.
        st.session_state[_SAVED_KEY] = {**saved, **pending}
    elif pending and _SAVED_KEY in st.session_state:
        st.session_state[_SAVED_KEY].update(pending)
    return _SAVED_KEY in st.session_state


def read(name, default=None):
    """Value saved under name, or default when absent or not yet known."""
    return st.session_state.get(_SAVED_KEY, {}).get(name, default)


def write(name, value):
    """Queue value to be saved. Safe to call from widget callbacks."""
    st.session_state.setdefault(_PENDING_KEY, {})[name] = value
    if _SAVED_KEY in st.session_state:
        st.session_state[_SAVED_KEY][name] = value
