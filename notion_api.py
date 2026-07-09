"""Thin Notion REST wrapper for the Life HQ gym/sleep dashboard.

Uses the 2025-09-03 data-source API directly (no MCP). Reads NOTION_TOKEN
from the environment (loaded from .env by the app).
"""
import os

import requests

NOTION_VERSION = "2025-09-03"
BASE = "https://api.notion.com/v1"


def _token():
    tok = os.environ.get("NOTION_TOKEN")
    if not tok:
        raise RuntimeError(
            "NOTION_TOKEN is not set. Copy .env.example to .env and paste your "
            "Notion internal integration token."
        )
    return tok


def _headers():
    return {
        "Authorization": f"Bearer {_token()}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


def _raise(resp):
    if not resp.ok:
        raise RuntimeError(f"Notion {resp.status_code}: {resp.text[:400]}")


def query(data_source_id, filter=None, sorts=None, page_size=100):
    """Query a data source, following pagination, returns list of page objects."""
    url = f"{BASE}/data_sources/{data_source_id}/query"
    payload = {"page_size": page_size}
    if filter:
        payload["filter"] = filter
    if sorts:
        payload["sorts"] = sorts
    out = []
    while True:
        r = requests.post(url, headers=_headers(), json=payload, timeout=30)
        _raise(r)
        data = r.json()
        out += data.get("results", [])
        if data.get("has_more") and data.get("next_cursor"):
            payload["start_cursor"] = data["next_cursor"]
        else:
            return out


def update_page(page_id, properties):
    r = requests.patch(
        f"{BASE}/pages/{page_id}", headers=_headers(), json={"properties": properties}, timeout=30
    )
    _raise(r)
    return r.json()


def create_page(data_source_id, properties, icon=None):
    payload = {
        "parent": {"type": "data_source_id", "data_source_id": data_source_id},
        "properties": properties,
    }
    if icon:
        payload["icon"] = {"type": "emoji", "emoji": icon}
    r = requests.post(f"{BASE}/pages", headers=_headers(), json=payload, timeout=30)
    _raise(r)
    return r.json()


def create_database(parent_page_id, title, properties):
    """Create a new database (with an initial data source) under a page.
    Returns the database object; the data source id is at data_sources[0].id.
    """
    payload = {
        "parent": {"type": "page_id", "page_id": parent_page_id},
        "title": [{"type": "text", "text": {"content": title}}],
        "initial_data_source": {"properties": properties},
    }
    r = requests.post(f"{BASE}/databases", headers=_headers(), json=payload, timeout=30)
    _raise(r)
    return r.json()


# --- property accessors (Notion page.properties -> plain python) ---

def title_text(props, name):
    arr = props.get(name, {}).get("title", [])
    return arr[0]["plain_text"] if arr else ""


def rich_text(props, name):
    arr = props.get(name, {}).get("rich_text", [])
    return arr[0]["plain_text"] if arr else ""


def number(props, name):
    return props.get(name, {}).get("number")


def select_name(props, name):
    sel = props.get(name, {}).get("select")
    return sel["name"] if sel else None


def date_start(props, name):
    d = props.get(name, {}).get("date")
    return d["start"] if d else None


def checkbox(props, name):
    return bool(props.get(name, {}).get("checkbox", False))


def relation_ids(props, name):
    return [x["id"] for x in props.get(name, {}).get("relation", [])]
