#!/usr/bin/env python3
"""
Omada Controller OpenAPI - List In-Use Vouchers
Auth: OAuth2 Client Credentials mode (local OpenAPI)

Interface Access Address : https://192.168.1.25:443
Omada ID                 : 3ee66939ba6b266f59d8e2ef60be1870

Usage:
    pip install requests
    python omada_vouchers.py

    Debug mode (prints raw API responses):
    python omada_vouchers.py --debug
"""

import os
import sys
import json
import requests
import urllib3
from datetime import datetime

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ──────────────────────────────────────────────────────────────
#  CONFIG  –  only CLIENT_ID and CLIENT_SECRET need filling in
# ──────────────────────────────────────────────────────────────

# From Settings > Platform Integration > Open API  (Client mode app)
CLIENT_ID = "01620a1fb27e4e9a9d3d5dd7f18faaa9"
CLIENT_SECRET = "70be9cbe1cf74aa3b99195166d8c5e18"

# Pre-filled from your "View Open API Attributes" panel
OMADAC_ID = "3ee66939ba6b266f59d8e2ef60be1870"
BASE_URL  = "https://192.168.1.25:443"   # Interface Access Address

# Leave blank to auto-select the first site
SITE_ID   = os.getenv("OMADA_SITE_ID", "")

PAGE_SIZE = 100
DEBUG     = "--debug" in sys.argv
# ──────────────────────────────────────────────────────────────


def dbg(label, data):
    if DEBUG:
        print(f"\n[DEBUG] {label}:")
        print(json.dumps(data, indent=2) if isinstance(data, (dict, list)) else data)


def get_access_token(session):
    """
    Local OpenAPI token endpoint.
    Try both snake_case and camelCase field names.
    """
    url = f"{BASE_URL}/openapi/authorize/token?grant_type=client_credentials"

    attempts = [
        {"omadacId": OMADAC_ID, "client_id": CLIENT_ID, "client_secret": CLIENT_SECRET},
        {"omadacId": OMADAC_ID, "clientId": CLIENT_ID,  "clientSecret": CLIENT_SECRET},
    ]

    last_error = ""
    for payload in attempts:
        print(f"  Trying: {url}")
        dbg("token payload", payload)
        try:
            resp = session.post(url, json=payload, verify=False, timeout=15)
            data = resp.json()
            dbg("token response", data)
            if data.get("errorCode", -1) == 0:
                token   = data["result"]["accessToken"]
                expires = data["result"].get("expiresIn", "?")
                print(f"  ✓ Token obtained  (expires in {expires}s)")
                return token
            last_error = data.get("msg", str(data))
            print(f"    ✗ {last_error}")
        except Exception as e:
            print(f"    ✗ Request error: {e}")

    sys.exit(
        f"\n✗ Could not obtain access token.\n"
        f"  Last error : {last_error}\n\n"
        f"  Check:\n"
        f"  1. CLIENT_ID and CLIENT_SECRET are correct\n"
        f"  2. The API app is set to 'Client' mode (not Authorization Code)\n"
        f"  3. Your machine can reach {BASE_URL} (try opening it in a browser)\n"
        f"  4. Run with --debug for full request/response details\n"
    )


def get_sites(session, token):
    url     = f"{BASE_URL}/openapi/v1/{OMADAC_ID}/sites"
    headers = {"Authorization": f"AccessToken={token}"}
    params  = {"currentPage": 1, "currentPageSize": 50}
    resp    = session.get(url, headers=headers, params=params, verify=False, timeout=15)
    data    = resp.json()
    dbg("sites response", data)
    if data.get("errorCode", -1) != 0:
        sys.exit(f"✗ Could not fetch sites: {data.get('msg', data)}")
    return data.get("result", {}).get("data", [])


def pick_site(session, token):
    sites = get_sites(session, token)
    if not sites:
        sys.exit("✗ No sites found — check the API app's site permissions.")
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
    all_vouchers = []
    page    = 1
    headers = {"Authorization": f"AccessToken={token}"}

    # Probe both endpoint names
    endpoints = [
        f"{BASE_URL}/openapi/v1/{OMADAC_ID}/sites/{site_id}/hotspot/vouchers",
        f"{BASE_URL}/openapi/v1/{OMADAC_ID}/sites/{site_id}/hotspot/voucher-groups",
    ]

    working_url = None
    for ep in endpoints:
        params = {"currentPage": 1, "currentPageSize": 1, "status": status}
        resp   = session.get(ep, headers=headers, params=params, verify=False, timeout=15)
        data   = resp.json()
        dbg(f"probe {ep}", data)
        if data.get("errorCode", -1) == 0:
            working_url = ep
            print(f"  Using endpoint : {ep}")
            break
        print(f"  Skipping {ep.split('/')[-1]} : {data.get('msg', data.get('errorCode'))}")

    if not working_url:
        sys.exit(
            "✗ Voucher endpoint not available.\n"
            "  This may mean your controller version does not yet expose\n"
            "  the voucher API via OpenAPI. Run with --debug for details."
        )

    while True:
        params = {"currentPage": page, "currentPageSize": PAGE_SIZE, "status": status}
        resp   = session.get(working_url, headers=headers, params=params, verify=False, timeout=15)
        result = resp.json()
        dbg(f"page {page}", result)
        data   = result.get("result", {}).get("data", [])
        total  = result.get("result", {}).get("totalRows", len(all_vouchers))
        all_vouchers.extend(data)
        if len(all_vouchers) >= total or not data:
            break
        page += 1

    return all_vouchers


# ── Formatting ─────────────────────────────────────────────────

def fmt_duration(seconds):
    if seconds is None:
        return "—"
    h, rem = divmod(int(seconds), 3600)
    m = rem // 60
    return f"{h}h {m}m"


def fmt_ts(ms):
    if not ms:
        return "—"
    try:
        return datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return str(ms)


def print_vouchers(vouchers):
    if not vouchers:
        print("\n  (no in-use vouchers found)\n")
        return

    W = {"code": 14, "name": 20, "mac": 18, "dur": 12,
         "created": 17, "expires": 17, "traffic": 13, "status": 8}
    hdr = (
        f"{'Code':<{W['code']}}{'Name':<{W['name']}}{'Client MAC':<{W['mac']}}"
        f"{'Duration':<{W['dur']}}{'Created':<{W['created']}}{'Expires':<{W['expires']}}"
        f"{'Traffic(MB)':<{W['traffic']}}{'Status':<{W['status']}}"
    )
    sep = "─" * len(hdr)
    print(f"\n{sep}\n{hdr}\n{sep}")

    for v in vouchers:
        print(
            f"{v.get('code', '—'):<{W['code']}}"
            f"{(v.get('name') or '—')[:W['name']-1]:<{W['name']}}"
            f"{(v.get('clientMac') or v.get('bindMac') or '—'):<{W['mac']}}"
            f"{fmt_duration(v.get('duration')):<{W['dur']}}"
            f"{fmt_ts(v.get('createTime')):<{W['created']}}"
            f"{fmt_ts(v.get('expireTime') or v.get('endTime')):<{W['expires']}}"
            f"{str(v.get('trafficLimit', '∞')):<{W['traffic']}}"
            f"{str(v.get('status', '—')):<{W['status']}}"
        )

    print(sep)
    print(f"  Total: {len(vouchers)} in-use voucher(s)\n")


def main():
    if "YOUR_CLIENT_ID_HERE" in CLIENT_ID:
        sys.exit("✗  Set CLIENT_ID and CLIENT_SECRET in the CONFIG block (or env vars)")

    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})

    print(f"\nBase URL  : {BASE_URL}")
    print(f"Omada ID  : {OMADAC_ID}")

    token   = get_access_token(session)
    site_id = SITE_ID or pick_site(session, token)

    print(f"\nFetching in-use vouchers …")
    vouchers = fetch_vouchers(session, token, site_id, status="Used")
    print_vouchers(vouchers)


if __name__ == "__main__":
    main()
