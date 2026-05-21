#!/usr/bin/env python3
"""
Omada Cloud OpenAPI - List In-Use Vouchers
Auth: OAuth2 Client Credentials (cloud northbound, EU West)

Usage:
    pip install requests
    python omada_vouchers.py

    Debug mode:
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
#  CONFIG  –  only CLIENT_SECRET needs filling in
# ──────────────────────────────────────────────────────────────

CLIENT_ID     = "01620a1fb27e4e9a9d3d5dd7f18faaa9"
CLIENT_SECRET = "70be9cbe1cf74aa3b99195166d8c5e18"

OMADAC_ID     = "3ee66939ba6b266f59d8e2ef60be1870"
NORTHBOUND    = "https://euw1-omada-northbound.tplinkcloud.com"

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
    Cloud northbound client_credentials token request.
    Tries 4 payload combinations to handle variation across controller versions.
    """
    url = f"{NORTHBOUND}/openapi/authorize/token?grant_type=client_credentials"

    attempts = [
        # Cloud style — no omadacId in body
        {"client_id":  CLIENT_ID, "client_secret":  CLIENT_SECRET},
        {"clientId":   CLIENT_ID, "clientSecret":   CLIENT_SECRET},
        # With omadacId in body
        {"omadacId": OMADAC_ID, "client_id":  CLIENT_ID, "client_secret":  CLIENT_SECRET},
        {"omadacId": OMADAC_ID, "clientId":   CLIENT_ID, "clientSecret":   CLIENT_SECRET},
    ]

    last_error = ""
    for payload in attempts:
        dbg("token payload", payload)
        try:
            resp = session.post(url, json=payload, verify=True, timeout=15)
            data = resp.json()
            dbg("token response", data)
            if data.get("errorCode", -1) == 0:
                token   = data["result"]["accessToken"]
                expires = data["result"].get("expiresIn", "?")
                print(f"  ✓ Token obtained  (expires in {expires}s)")
                return token
            last_error = data.get("msg", str(data))
            print(f"  ✗ Attempt failed: {last_error}  (payload keys: {list(payload.keys())})")
        except Exception as e:
            last_error = str(e)
            print(f"  ✗ Request error: {e}")

    sys.exit(
        f"\n✗ All token attempts failed.\n"
        f"  Last error : {last_error}\n\n"
        f"  Most likely cause: CLIENT_SECRET is wrong.\n"
        f"  Delete the API app in Omada, create a new one (Client mode),\n"
        f"  and copy the secret immediately when it appears.\n"
        f"  Run with --debug to see full responses.\n"
    )


def get_sites(session, token):
    url     = f"{NORTHBOUND}/openapi/v1/{OMADAC_ID}/sites"
    headers = {"Authorization": f"AccessToken={token}"}
    params  = {"currentPage": 1, "currentPageSize": 50}
    resp    = session.get(url, headers=headers, params=params, verify=True, timeout=15)
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

    endpoints = [
        f"{NORTHBOUND}/openapi/v1/{OMADAC_ID}/sites/{site_id}/hotspot/vouchers",
        f"{NORTHBOUND}/openapi/v1/{OMADAC_ID}/sites/{site_id}/hotspot/voucher-groups",
    ]

    working_url = None
    for ep in endpoints:
        params = {"currentPage": 1, "currentPageSize": 1, "status": status}
        resp   = session.get(ep, headers=headers, params=params, verify=True, timeout=15)
        data   = resp.json()
        dbg(f"probe {ep.split('/')[-1]}", data)
        if data.get("errorCode", -1) == 0:
            working_url = ep
            print(f"  Using endpoint : .../{ep.split('/hotspot/')[1]}")
            break
        print(f"  Skipping {ep.split('/')[-1]} : {data.get('msg', data.get('errorCode'))}")

    if not working_url:
        sys.exit(
            "✗ Voucher endpoint not available on this controller version.\n"
            "  Run with --debug for full error details."
        )

    while True:
        params = {"currentPage": page, "currentPageSize": PAGE_SIZE, "status": status}
        resp   = session.get(working_url, headers=headers, params=params, verify=True, timeout=15)
        result = resp.json()
        dbg(f"page {page}", result)
        data   = result.get("result", {}).get("data", [])
        total  = result.get("result", {}).get("totalRows", len(all_vouchers))
        all_vouchers.extend(data)
        if len(all_vouchers) >= total or not data:
            break
        page += 1

    return all_vouchers


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
    if "YOUR_CLIENT_SECRET_HERE" in CLIENT_SECRET:
        sys.exit("✗  Set CLIENT_SECRET in the CONFIG block (or env var OMADA_CLIENT_SECRET)")

    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})

    print(f"\nNorthbound : {NORTHBOUND}")
    print(f"Client ID  : {CLIENT_ID}")
    print(f"Omada ID   : {OMADAC_ID}")
    print(f"\nRequesting access token …")

    token   = get_access_token(session)
    site_id = SITE_ID or pick_site(session, token)

    print(f"\nFetching in-use vouchers …")
    vouchers = fetch_vouchers(session, token, site_id, status="Used")
    print_vouchers(vouchers)


if __name__ == "__main__":
    main()
