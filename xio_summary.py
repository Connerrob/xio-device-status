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


UFIT_GROUP_ID = os.environ.get(
    "XIO_UFIT_GROUP_ID",
    "5128cb10-3b9f-4ad9-9e68-284b5e7f1460",
)

UFIT_LABEL = os.environ.get("XIO_UFIT_LABEL", "UFIT Learning Space")


def _extract_list(data):

    if isinstance(data, list):
        return data

    if isinstance(data, dict):
        for key in ("Devices", "devices", "items", "DeviceList"):
            if key in data and isinstance(data[key], list):
                return data[key]

    return []


def fetch_account_devices():

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


def summarize_groups(devices, highlight_group_id=None, highlight_label=None):


    groups_raw = {}

    for d in devices:
        dev_obj = d.get("device") if isinstance(d.get("device"), dict) else d

        gid = (
            dev_obj.get("device-groupid")
            or dev_obj.get("groupId")
            or dev_obj.get("group-id")
        )
        if not gid:

            continue

        status = dev_obj.get("device-status", "Unknown")

        if gid not in groups_raw:
            groups_raw[gid] = {
                "deviceCounts": {},
                "totalDevices": 0,
            }

        g = groups_raw[gid]
        g["deviceCounts"][status] = g["deviceCounts"].get(status, 0) + 1
        g["totalDevices"] += 1

    groups_list = []
    highlight_data = None


    for gid, g in groups_raw.items():
        counts = g["deviceCounts"]
        total = g["totalDevices"]
        online = counts.get("Online", 0)
        online_pct = round((online / total) * 100, 1) if total else 0.0

        group_obj = {
            "deviceCounts": counts,
            "totalDevices": total,
            "onlinePct": online_pct,
        }
        groups_list.append(group_obj)


        if highlight_group_id and gid == highlight_group_id:
            highlight_data = {
                "label": highlight_label or "Highlighted Group",
                "deviceCounts": counts,
                "totalDevices": total,
                "onlinePct": online_pct,
            }


    if not highlight_data and groups_raw:
        gid_top, g_top = max(
            groups_raw.items(),
            key=lambda kv: kv[1]["totalDevices"]
        )
        counts = g_top["deviceCounts"]
        total = g_top["totalDevices"]
        online = counts.get("Online", 0)
        online_pct = round((online / total) * 100, 1) if total else 0.0

        highlight_data = {
            "label": highlight_label or "Highlighted Group",
            "deviceCounts": counts,
            "totalDevices": total,
            "onlinePct": online_pct,
        }

    return {
        "meta": {
            "generatedAtUtc": datetime.now(timezone.utc).isoformat(),
        },
        "groups": groups_list,
        "highlight": highlight_data,
    }


def main():
    print("Fetching *account* devices from XiO Cloud...")
    account_devices = fetch_account_devices()
    print(f"Fetched {len(account_devices)} devices for account {ACCOUNT_ID}")


    summary = summarize(account_devices)
    with open("xio-summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    print("Wrote xio-summary.json")


    groups_summary = summarize_groups(
        account_devices,
        highlight_group_id=UFIT_GROUP_ID,
        highlight_label=UFIT_LABEL,
    )
    with open("xio-groups-status.json", "w", encoding="utf-8") as f:
        json.dump(groups_summary, f, indent=2)
    print("Wrote xio-groups-status.json")


if __name__ == "__main__":
    main()
