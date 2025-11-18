import os
import json
from datetime import datetime, timezone

import requests

BASE_URL = "https://api.crestron.io"

# Read from environment variables (names, not values!)
ACCOUNT_ID = os.environ.get("XIO_ACCOUNT_ID")
SUB_KEY = os.environ.get("XIO_SUBSCRIPTION_KEY")

if not ACCOUNT_ID or not SUB_KEY:
    raise SystemExit("Missing XIO_ACCOUNT_ID or XIO_SUBSCRIPTION_KEY env vars")

HEADERS = {
    "XiO-subscription-key": SUB_KEY,
    "Accept": "application/json",
}


def fetch_devices():

    url = f"{BASE_URL}/api/v1/device/accountid/{ACCOUNT_ID}/devices"
    resp = requests.get(url, headers=HEADERS, timeout=30)

    if resp.status_code == 429:
        raise SystemExit(
            "XiO API returned 429 Too Many Requests.\n"
            "You’ve hit the rate limit; wait a few minutes before running again."
        )

    resp.raise_for_status()
    data = resp.json()


    if isinstance(data, dict):
        for key in ("Devices", "devices", "items"):
            if key in data and isinstance(data[key], list):
                return data[key]
        return []
    elif isinstance(data, list):
        return data
    else:
        return []


def summarize(devices):

    status_counts = {}
    for d in devices:
        status = d.get("device-status", "Unknown")
        status_counts[status] = status_counts.get(status, 0) + 1

    total_devices = len(devices)
    online = status_counts.get("Online", 0)
    online_pct = round((online / total_devices) * 100, 1) if total_devices else 0.0

    summary = {
        "device": {
            "counts": status_counts,
            "total": total_devices,
            "onlinePct": online_pct,
        },
        "meta": {
            "generatedAtUtc": datetime.now(timezone.utc).isoformat(),
        },
    }

    return summary


def main():
    print("Fetching devices from XiO Cloud...")
    devices = fetch_devices()
    print(f"Fetched {len(devices)} devices")

    print("Summarizing...")
    summary = summarize(devices)

    out_path = "xio-summary.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
