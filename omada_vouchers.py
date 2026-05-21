#!/usr/bin/env python3
"""
Omada Cloud OpenAPI - List In-Use Vouchers
Supports: EU West (euw1) and other regional cloud controllers
Auth:      OAuth2 Client Credentials mode (Client ID + Client Secret)

Usage:
    pip install requests
    python omada_vouchers.py

    Or export env vars instead of editing the CONFIG block:
        OMADA_CLIENT_ID, OMADA_CLIENT_SECRET, OMADA_OMADAC_ID,
        OMADA_CONNECTOR_URL  (optional, defaults to EU West)
"""

import os
import sys
import json
import requests
import urllib3
from datetime import datetime

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ──────────────────────────────────────────────────────────────
#  CONFIG  –  edit here  OR  set environment variables
# ──────────────────────────────────────────────────────────────

# From your Omada Cloud URL:
#   omadacId=3ee66939ba6b266f59d8e2ef60be1870
OMADAC_ID = os.getenv("OMADA_OMADAC_ID", "3ee66939ba6b266f59d8e2ef60be1870")

# From Settings > Platform Integration > Open API  (Client mode app)
CLIENT_ID     = os.getenv("OMADA_CLIENT_ID",     "YOUR_CLIENT_ID_HERE")
CLIENT_SECRET = os.getenv("OMADA_CLIENT_SECRET",  "YOUR_CLIENT_SECRET_HERE")

# Connector URL from your Omada Cloud login URL
# (the connectorUrl= param you shared)
CONNECTOR_URL = os.getenv(
    "OMADA_CONNECTOR_URL",
    "https://euw1-api-omada-controller-connector.tplinkcloud.com"
)

# Leave blank to auto-select the first/only site
SITE_ID = os.getenv("OMADA_SITE_ID", "")

PAGE_SIZE = 100   # vouchers per page
# ──────────────────────────────────────────────────────────────


def get_access_token(session):
    """OAuth2 client_credentials flow → returns access token string."""
    url = f"{CONNECTOR_URL}/openapi/authorize/token?grant_type=client_credentials"
    payload = {
        "omadacId":     OMADAC_ID,
        "client_id":    CLIENT_ID,
        "client_secret": CLIENT_SECRET,
    }
    resp = session.post(url, json=payload)
    resp.raise_for_status()
    data = resp.json()
    if data.get("errorCode", -1) != 0:
        sys.exit(f"✗ Token request failed: {data.get('msg', data)}")
    token = data["result"]["accessToken"]
    expires_in = data["result"].get("expiresIn", "?")
    print(f"  Access token obtained  (expires in {expires_in}s)")
    return token


def get_sites(session, token):
    """Return list of sites available to this API client."""
    url = f"{CONNECTOR_URL}/openapi/v1/{OMADAC_ID}/sites"
    headers = {"Authorization": f"AccessToken={token}"}
    params  = {"currentPage": 1, "currentPageSize": 50}
    resp = session.get(url, headers=headers, params=params)
    resp.raise_for_status()
    data = resp.json()
    if data.get("errorCode", -1) != 0:
        sys.exit(f"✗ Could not fetch sites: {data.get('msg', data)}")
    return data.get("result", {}).get("data", [])


def pick_site(session, token):
    sites = get_sites(session, token)
    if not sites:
        sys.exit("✗ No sites found — check your API app's site permissions.")
    if len(sites) == 1:
        s = sites[0]
        print(f"  Auto-selected site : {s['name']}  ({s['id']})")
        return s["id"]
    print("\nAvailable sites:")
    for i, s in enumerate(sites):
        print(f"  [{i}]  {s['name']}  (id: {s['id']})")
    idx = input("Select site index [0]: ").strip() or "0"
    return sites[int(idx)]["id"]


def fetch_vouchers(session, token, site_id, status="Used"):
    """
    Fetch all vouchers for the given site.
    status: Used | Unused | Expired | All
    'Used' = voucher has been redeemed (active/in-use).
    """
    all_vouchers = []
    page = 1
    headers = {"Authorization": f"AccessToken={token}"}

    while True:
        # Try OpenAPI v1 endpoint first (voucher-groups / vouchers)
        url = (
            f"{CONNECTOR_URL}/openapi/v1/{OMADAC_ID}"
            f"/sites/{site_id}/hotspot/vouchers"
        )
        params = {
            "currentPage":     page,
            "currentPageSize": PAGE_SIZE,
            "status":          status,
        }
        resp = session.get(url, headers=headers, params=params)
        resp.raise_for_status()
        result = resp.json()

        if result.get("errorCode", -1) != 0:
            # Some controller versions expose voucher-groups instead
            print(f"  Note: /vouchers returned error ({result.get('msg')}), trying /voucher-groups …")
            url2 = (
                f"{CONNECTOR_URL}/openapi/v1/{OMADAC_ID}"
                f"/sites/{site_id}/hotspot/voucher-groups"
            )
            resp2 = session.get(url2, headers=headers, params=params)
            resp2.raise_for_status()
            result = resp2.json()
            if result.get("errorCode", -1) != 0:
                sys.exit(f"✗ Could not fetch vouchers: {result.get('msg', result)}")

        data  = result.get("result", {}).get("data", [])
        total = result.get("result", {}).get("totalRows", len(all_vouchers))
        all_vouchers.extend(data)

        if len(all_vouchers) >= total or not data:
            break
        page += 1

    return all_vouchers


# ── Formatting helpers ─────────────────────────────────────────

def format_duration(seconds):
    if seconds is None:
        return "—"
    h, rem = divmod(int(seconds), 3600)
    m = rem // 60
    return f"{h}h {m}m"


def format_ts(ms):
    if not ms:
        return "—"
    try:
        return datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return str(ms)


def print_vouchers(vouchers):
    if not vouchers:
        print("\n  (no vouchers found with status=Used)\n")
        return

    COL = {
        "code":     14,
        "name":     20,
        "client":   18,
        "duration": 12,
        "created":  17,
        "expires":  17,
        "traffic":  14,
        "status":    8,
    }

    header = (
        f"{'Code':<{COL['code']}}"
        f"{'Name':<{COL['name']}}"
        f"{'Client MAC':<{COL['client']}}"
        f"{'Duration':<{COL['duration']}}"
        f"{'Created':<{COL['created']}}"
        f"{'Expires':<{COL['expires']}}"
        f"{'Traffic (MB)':<{COL['traffic']}}"
        f"{'Status':<{COL['status']}}"
    )
    sep = "─" * len(header)

    print(f"\n{sep}")
    print(header)
    print(sep)

    for v in vouchers:
        code     = v.get("code", "—")
        name     = (v.get("name") or "—")[:COL["name"] - 1]
        client   = v.get("clientMac") or v.get("bindMac") or "—"
        duration = format_duration(v.get("duration"))
        created  = format_ts(v.get("createTime"))
        expires  = format_ts(v.get("expireTime") or v.get("endTime"))
        traffic  = v.get("trafficLimit", "∞")
        status   = v.get("status", "—")

        print(
            f"{code:<{COL['code']}}"
            f"{name:<{COL['name']}}"
            f"{client:<{COL['client']}}"
            f"{duration:<{COL['duration']}}"
            f"{created:<{COL['created']}}"
            f"{expires:<{COL['expires']}}"
            f"{str(traffic):<{COL['traffic']}}"
            f"{str(status):<{COL['status']}}"
        )

    print(sep)
    print(f"  Total: {len(vouchers)} in-use voucher(s)\n")


def main():
    if "YOUR_CLIENT_ID_HERE" in CLIENT_ID:
        sys.exit(
            "✗  Please set CLIENT_ID and CLIENT_SECRET in the CONFIG block\n"
            "   (or via env vars OMADA_CLIENT_ID / OMADA_CLIENT_SECRET)"
        )

    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})

    print(f"\nConnecting to {CONNECTOR_URL}")
    print(f"  omadacId : {OMADAC_ID}")

    token   = get_access_token(session)
    site_id = SITE_ID or pick_site(session, token)

    print(f"\nFetching in-use vouchers for site {site_id} …")
    vouchers = fetch_vouchers(session, token, site_id, status="Used")

    print_vouchers(vouchers)

    if "--json" in sys.argv:
        print(json.dumps(vouchers, indent=2))


if __name__ == "__main__":
    main()
