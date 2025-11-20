from datetime import datetime, timezone
import json
import os
import requests

BASE_URL = "https://api.crestron.io"

ACCOUNT_ID = os.environ.get("XIO_ACCOUNT_ID")
SUB_KEY = os.environ.get("XIO_SUBSCRIPTION_KEY")

if not ACCOUNT_ID or not SUB_KEY:
    raise SystemExit("Missing XIO_ACCOUNT_ID or XIO_SUBSCRIPTION_KEY env vars")

HEADERS = {
    "XiO-subscription-key": SUB_KEY,
    "Accept": "application/json",
}

# Optional: friendly names for known group IDs
GROUP_NAME_OVERRIDES = {
    "5128cb10-3b9f-4ad9-9e68-284b5e7f1460": "UFIT Learning Space",
}


def _extract_list(data):
    """
    XiO sometimes wraps lists in an object with keys like:
    Devices, devices, items, DeviceList, etc.
    """
    if isinstance(data, list):
        return data

    if isinstance(data, dict):
        for key in ("Devices", "devices", "items", "DeviceList"):
            if key in data and isinstance(data[key], list):
                return data[key]

    return []


def fetch_account_devices():
    """
    /api/v1/device/accountid/{accountid}/devices
    Returns all devices for the account.
    """
    url = f"{BASE_URL}/api/v1/device/accountid/{ACCOUNT_ID}/devices"
    resp = requests.get(url, headers=HEADERS, timeout=30)

    if resp.status_code == 429:
        raise SystemExit(
            "XiO API returned 429 Too Many Requests.\n"
            "You’ve hit the rate limit; wait a few minutes before running again."
        )

    resp.raise_for_status()
    data = resp.json()
    return _extract_list(data)


def summarize(devices):
    """
    Build the global/account summary JSON.

    Output shape (matches your existing xio-summary.json usage):
    {
      "device": {
        "counts": { "Online": n, ... },
        "total": n,
        "onlinePct": 42.0
      },
      "meta": { "generatedAtUtc": "..." }
    }
    """
    status_counts = {}
    for d in devices:
        dev_obj = d.get("device") if isinstance(d.get("device"), dict) else d
        status = dev_obj.get("device-status", "Unknown")
        status_counts[status] = status_counts.get(status, 0) + 1

    total_devices = len(devices)
    online = status_counts.get("Online", 0)
    online_pct = round((online / total_devices) * 100, 1) if total_devices else 0.0

    return {
        "device": {
            "counts": status_counts,
            "total": total_devices,
            "onlinePct": online_pct,
        },
        "meta": {
            "generatedAtUtc": datetime.now(timezone.utc).isoformat(),
        },
    }


def summarize_groups(devices):
    """
    Per-group status from the full account device list.

    Output:
    {
      "meta": { "generatedAtUtc": "..." },
      "groups": [
        {
          "groupId": "...",
          "name": "UFIT Learning Space",
          "deviceCounts": { "Online": n, "Offline": n, ... },
          "totalDevices": n,
          "onlinePct": 42.5
        },
        ...
      ]
    }
    """
    groups = {}

    for d in devices:
        dev_obj = d.get("device") if isinstance(d.get("device"), dict) else d

        gid = (
            dev_obj.get("device-groupid")
            or dev_obj.get("groupId")
            or dev_obj.get("group-id")
        )
        if not gid:
            continue  # skip devices not in a group

        status = dev_obj.get("device-status", "Unknown")

        if gid not in groups:
            groups[gid] = {
                "groupId": gid,
                "name": GROUP_NAME_OVERRIDES.get(gid, None),
                "deviceCounts": {},
                "totalDevices": 0,
            }

        g = groups[gid]
        g["deviceCounts"][status] = g["deviceCounts"].get(status, 0) + 1
        g["totalDevices"] += 1

    # compute onlinePct + fallback names
    for g in groups.values():
        counts = g["deviceCounts"]
        online = counts.get("Online", 0)
        total = g["totalDevices"]
        g["onlinePct"] = round((online / total) * 100, 1) if total else 0.0

        if not g["name"]:
            g["name"] = g["groupId"]

    return {
        "meta": {
            "generatedAtUtc": datetime.now(timezone.utc).isoformat(),
        },
        "groups": list(groups.values()),
    }


def main():
    print("Fetching *account* devices from XiO Cloud...")
    account_devices = fetch_account_devices()
    print(f"Fetched {len(account_devices)} devices for account {ACCOUNT_ID}")

    # Global summary
    summary = summarize(account_devices)
    with open("xio-summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    print("Wrote xio-summary.json")

    # Per-group summary
    groups_summary = summarize_groups(account_devices)
    with open("xio-groups-status.json", "w", encoding="utf-8") as f:
        json.dump(groups_summary, f, indent=2)
    print(f"Wrote xio-groups-status.json with {len(groups_summary['groups'])} groups")


if __name__ == "__main__":
    main()
