#!/usr/bin/env python3
"""
Omada Controller - List In-Use Vouchers
Tested against Omada SDN Controller v5.x (API v2)

Usage:
    pip install requests
    python omada_vouchers.py

    Or set environment variables instead of editing the config block:
        OMADA_URL, OMADA_USER, OMADA_PASS, OMADA_SITE_ID
"""

import os
import sys
import json
import requests
import urllib3
from datetime import datetime

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ──────────────────────────────────────────
#  CONFIG  –  edit here or use env vars
# ──────────────────────────────────────────
OMADA_URL  = os.getenv("OMADA_URL",  "https://192.168.1.1:8043")   # your controller URL
USERNAME   = os.getenv("OMADA_USER", "admin")
PASSWORD   = os.getenv("OMADA_PASS", "your_password")
# Leave SITE_ID empty to auto-select the first site, or paste your site ID here
SITE_ID    = os.getenv("OMADA_SITE_ID", "")
VERIFY_SSL = False   # set True if you have a valid cert
PAGE_SIZE  = 100     # vouchers fetched per page
# ──────────────────────────────────────────


def get_controller_id(session, base_url):
    resp = session.get(f"{base_url}/api/info", verify=VERIFY_SSL)
    resp.raise_for_status()
    data = resp.json()
    cid = data.get("result", {}).get("omadacId")
    if not cid:
        sys.exit("✗ Could not retrieve omadacId from /api/info")
    return cid


def login(session, base_url, controller_id, username, password):
    url = f"{base_url}/{controller_id}/api/v2/login"
    payload = {"username": username, "password": password}
    resp = session.post(url, json=payload, verify=VERIFY_SSL)
    resp.raise_for_status()
    data = resp.json()
    if data.get("errorCode", -1) != 0:
        sys.exit(f"✗ Login failed: {data.get('msg', 'unknown error')}")
    token = data["result"]["token"]
    session.headers.update({"Csrf-Token": token})
    return token


def get_site_id(session, base_url, controller_id, token):
    url = f"{base_url}/{controller_id}/api/v2/sites?token={token}&currentPage=1&currentPageSize=50"
    resp = session.get(url, verify=VERIFY_SSL)
    resp.raise_for_status()
    sites = resp.json().get("result", {}).get("data", [])
    if not sites:
        sys.exit("✗ No sites found on this controller.")
    if len(sites) == 1:
        site = sites[0]
        print(f"  ↳ Auto-selected site: {site['name']} ({site['id']})")
        return site["id"]
    print("\nAvailable sites:")
    for i, s in enumerate(sites):
        print(f"  [{i}] {s['name']}  (id: {s['id']})")
    idx = input("Select site index [0]: ").strip() or "0"
    return sites[int(idx)]["id"]


def fetch_vouchers(session, base_url, controller_id, site_id, token, status="Used"):
    """
    status options: All | Used | Unused | Expired
    'Used' = currently in use (voucher has been redeemed / active session).
    """
    all_vouchers = []
    page = 1
    while True:
        url = (
            f"{base_url}/{controller_id}/api/v2/hotspot/sites/{site_id}/vouchers"
            f"?token={token}&currentPage={page}&currentPageSize={PAGE_SIZE}&status={status}"
        )
        resp = session.get(url, verify=VERIFY_SSL)
        resp.raise_for_status()
        result = resp.json().get("result", {})
        data   = result.get("data", [])
        all_vouchers.extend(data)
        total = result.get("totalRows", len(all_vouchers))
        if len(all_vouchers) >= total or not data:
            break
        page += 1
    return all_vouchers


def format_duration(seconds):
    if seconds is None:
        return "—"
    h, rem = divmod(int(seconds), 3600)
    m = rem // 60
    return f"{h}h {m}m"


def format_ts(ms):
    """Convert epoch milliseconds to readable datetime."""
    if not ms:
        return "—"
    try:
        return datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return str(ms)


def print_vouchers(vouchers):
    if not vouchers:
        print("\n  (no vouchers found with this status)\n")
        return

    # Column widths
    COL = {
        "code":       14,
        "name":       20,
        "client":     18,
        "duration":   12,
        "created":    17,
        "expires":    17,
        "traffic":    14,
        "status":      8,
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
    print(f"  Total: {len(vouchers)} voucher(s)\n")


def logout(session, base_url, controller_id, token):
    try:
        url = f"{base_url}/{controller_id}/api/v2/logout?token={token}"
        session.post(url, verify=VERIFY_SSL)
    except Exception:
        pass


def main():
    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})

    print(f"\nConnecting to {OMADA_URL} …")
    controller_id = get_controller_id(session, OMADA_URL)
    print(f"  Controller ID : {controller_id}")

    token = login(session, OMADA_URL, controller_id, USERNAME, PASSWORD)
    print(f"  Logged in     : {USERNAME}")

    site_id = SITE_ID or get_site_id(session, OMADA_URL, controller_id, token)

    print(f"\nFetching in-use vouchers for site {site_id} …")
    vouchers = fetch_vouchers(session, OMADA_URL, controller_id, site_id, token, status="Used")

    print_vouchers(vouchers)

    # Optionally dump raw JSON for inspection
    if "--json" in sys.argv:
        print(json.dumps(vouchers, indent=2))

    logout(session, OMADA_URL, controller_id, token)
    print("Session closed.")


if __name__ == "__main__":
    main()
