#!/usr/bin/env python3
"""
Omada Cloud OpenAPI - List In-Use Vouchers
Region: EU West  (euw1)
Auth:   OAuth2 Client Credentials mode

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
#  CONFIG  –  fill these in
# ──────────────────────────────────────────────────────────────

# From Settings > Platform Integration > Open API  (Client mode app)
CLIENT_ID     = os.getenv("OMADA_CLIENT_ID",     "YOUR_CLIENT_ID_HERE")
CLIENT_SECRET = os.getenv("OMADA_CLIENT_SECRET",  "YOUR_CLIENT_SECRET_HERE")

# From your Omada Cloud browser URL  (omadacId= param)
OMADAC_ID = os.getenv("OMADA_OMADAC_ID", "3ee66939ba6b266f59d8e2ef60be1870")

# EU West northbound (token + API calls go here for cloud)
NORTHBOUND_URL = "https://euw1-omada-northbound.tplinkcloud.com"

# Connector URL (from connectorUrl= param in your browser URL)
CONNECTOR_URL  = "https://euw1-api-omada-controller-connector.tplinkcloud.com"

# Leave blank to auto-select the first site
SITE_ID = os.getenv("OMADA_SITE_ID", "")

PAGE_SIZE = 100
DEBUG     = "--debug" in sys.argv
# ──────────────────────────────────────────────────────────────


def dbg(label, data):
    if DEBUG:
        print(f"\n[DEBUG] {label}:")
        print(json.dumps(data, indent=2) if isinstance(data, (dict, list)) else data)


def get_access_token(session):
    """
    Try every combination of:
      - northbound URL vs connector URL
      - with vs without omadacId in payload
      - snake_case vs camelCase field names
    Cloud controllers often don't want omadacId in the token request at all.
    """
    attempts = [
        # Cloud-style: NO omadacId in body (omadacId goes into API calls, not auth)
        (
            f"{NORTHBOUND_URL}/openapi/authorize/token?grant_type=client_credentials",
            {"client_id": CLIENT_ID, "client_secret": CLIENT_SECRET},
        ),
        (
            f"{NORTHBOUND_URL}/openapi/authorize/token?grant_type=client_credentials",
            {"clientId": CLIENT_ID, "clientSecret": CLIENT_SECRET},
        ),
        (
            f"{CONNECTOR_URL}/openapi/authorize/token?grant_type=client_credentials",
            {"client_id": CLIENT_ID, "client_secret": CLIENT_SECRET},
        ),
        (
            f"{CONNECTOR_URL}/openapi/authorize/token?grant_type=client_credentials",
            {"clientId": CLIENT_ID, "clientSecret": CLIENT_SECRET},
        ),
        # Fallback: with omadacId (works on some self-hosted versions)
        (
            f"{NORTHBOUND_URL}/openapi/authorize/token?grant_type=client_credentials",
            {"omadacId": OMADAC_ID, "client_id": CLIENT_ID, "client_secret": CLIENT_SECRET},
        ),
        (
            f"{CONNECTOR_URL}/openapi/authorize/token?grant_type=client_credentials",
            {"omadacId": OMADAC_ID, "clientId": CLIENT_ID, "clientSecret": CLIENT_SECRET},
        ),
    ]

    last_error = ""
    for url, payload in attempts:
        print(f"  Trying token endpoint: {url}")
        dbg("token payload", payload)
        try:
            resp = session.post(url, json=payload, timeout=15)
            dbg("token response", resp.json())
            data = resp.json()
            if data.get("errorCode", -1) == 0:
                token = data["result"]["accessToken"]
                expires = data["result"].get("expiresIn", "?")
                print(f"  ✓ Token obtained  (expires in {expires}s)")
                return token, url.split("/openapi/")[0]   # return (token, base_url)
            last_error = data.get("msg", str(data))
            print(f"    ✗ {last_error}")
        except Exception as e:
            print(f"    ✗ Request error: {e}")

    sys.exit(
        f"\n✗ Could not obtain access token.\n"
        f"  Last error : {last_error}\n\n"
        f"  Check:\n"
        f"  1. CLIENT_ID and CLIENT_SECRET are correct (copy-paste from Platform Integration > Open API)\n"
        f"  2. The API app is set to 'Client' mode (not Authorization Code mode)\n"
        f"  3. OMADAC_ID matches what's shown in Platform Integration\n"
        f"  4. Run with --debug to see full request/response details\n"
    )


def get_sites(session, base_url, token):
    url     = f"{base_url}/openapi/v1/{OMADAC_ID}/sites"
    headers = {"Authorization": f"AccessToken={token}"}
    params  = {"currentPage": 1, "currentPageSize": 50}
    resp    = session.get(url, headers=headers, params=params, timeout=15)
    data    = resp.json()
    dbg("sites response", data)
    if data.get("errorCode", -1) != 0:
        sys.exit(f"✗ Could not fetch sites: {data.get('msg', data)}")
    return data.get("result", {}).get("data", [])


def pick_site(session, base_url, token):
    sites = get_sites(session, base_url, token)
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


def fetch_vouchers(session, base_url, token, site_id, status="Used"):
    all_vouchers = []
    page    = 1
    headers = {"Authorization": f"AccessToken={token}"}

    # Try /vouchers then /voucher-groups
    endpoints = [
        f"{base_url}/openapi/v1/{OMADAC_ID}/sites/{site_id}/hotspot/vouchers",
        f"{base_url}/openapi/v1/{OMADAC_ID}/sites/{site_id}/hotspot/voucher-groups",
    ]

    working_url = None
    for ep in endpoints:
        params = {"currentPage": 1, "currentPageSize": 1, "status": status}
        resp   = session.get(ep, headers=headers, params=params, timeout=15)
        data   = resp.json()
        dbg(f"probe {ep}", data)
        if data.get("errorCode", -1) == 0:
            working_url = ep
            print(f"  Using endpoint: {ep}")
            break

    if not working_url:
        sys.exit(
            "✗ Voucher endpoint not found.\n"
            "  The voucher API may not be available on your controller version.\n"
            "  Try running with --debug to see the full error response."
        )

    while True:
        params = {"currentPage": page, "currentPageSize": PAGE_SIZE, "status": status}
        resp   = session.get(working_url, headers=headers, params=params, timeout=15)
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

    W = {"code": 14, "name": 20, "mac": 18, "dur": 12, "created": 17, "expires": 17, "traffic": 13, "status": 8}
    hdr = (f"{'Code':<{W['code']}}{'Name':<{W['name']}}{'Client MAC':<{W['mac']}}"
           f"{'Duration':<{W['dur']}}{'Created':<{W['created']}}{'Expires':<{W['expires']}}"
           f"{'Traffic(MB)':<{W['traffic']}}{'Status':<{W['status']}}")
    sep = "─" * len(hdr)

    print(f"\n{sep}\n{hdr}\n{sep}")
    for v in vouchers:
        print(
            f"{v.get('code','—'):<{W['code']}}"
            f"{(v.get('name') or '—')[:W['name']-1]:<{W['name']}}"
            f"{(v.get('clientMac') or v.get('bindMac') or '—'):<{W['mac']}}"
            f"{fmt_duration(v.get('duration')):<{W['dur']}}"
            f"{fmt_ts(v.get('createTime')):<{W['created']}}"
            f"{fmt_ts(v.get('expireTime') or v.get('endTime')):<{W['expires']}}"
            f"{str(v.get('trafficLimit','∞')):<{W['traffic']}}"
            f"{str(v.get('status','—')):<{W['status']}}"
        )
    print(sep)
    print(f"  Total: {len(vouchers)} in-use voucher(s)\n")


def main():
    if "YOUR_CLIENT_ID_HERE" in CLIENT_ID:
        sys.exit("✗  Set CLIENT_ID and CLIENT_SECRET in the CONFIG block (or env vars)")

    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})

    print(f"\nomadacId  : {OMADAC_ID}")
    print(f"Northbound: {NORTHBOUND_URL}")

    token, base_url = get_access_token(session)
    site_id = SITE_ID or pick_site(session, base_url, token)

    print(f"\nFetching in-use vouchers …")
    vouchers = fetch_vouchers(session, base_url, token, site_id, status="Used")
    print_vouchers(vouchers)


if __name__ == "__main__":
    main()
