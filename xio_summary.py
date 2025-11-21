from datetime import datetime, timezone
import json
import os
import sys
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

GROUPS_OF_INTEREST = {
    "4b8e5e57-861e-4a73-84d8-f1687ded87ca": "Malachowsky Hall",
    "ce2a359d-bc31-487b-98da-34c586a721e0": "Scheduling Panels",
    "9f292bd3-2a30-4c65-88fe-d0aa7873ea83": "UF Libraries",
    "ec748315-bcff-443d-b2d9-519d653ae43c": "UFIT AV Install Group",
    "1b7d0227-f9db-47a0-94ed-14d5d6e9261f": "UFIT Conference Rooms",
    "5128cb10-3b9f-4ad9-9e68-284b5e7f1460": "UFIT Learning Spaces",
}
GROUP_IDS_OF_INTEREST = set(GROUPS_OF_INTEREST.keys())


def _extract_device_list(data):
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
            "XiO API returned 429 Too Many Requests for Account Devices.\n"
            "V1 calls are limited to one request per five-minutes interval."
        )

    resp.raise_for_status()
    raw = resp.json()
    devices = _extract_device_list(raw)

    if not devices and isinstance(raw, dict):
        values = [v for v in raw.values() if isinstance(v, dict)]
        if values:
            return values

    return devices


def summarize_overall(devices):
    status_counts = {}
    for d in devices:
        dev = d.get("device") if isinstance(d.get("device"), dict) else d
        status = dev.get("device-status", "Unknown")
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


def build_ui_devices(devices):
    ui_devices = []
    for d in devices:
        dev = d.get("device") if isinstance(d.get("device"), dict) else d
        name = (
            dev.get("device-name")
            or dev.get("Name")
            or dev.get("name")
        )
        status = (
            dev.get("device-status")
            or dev.get("Online Status")
            or dev.get("status")
        )
        ui_devices.append(
            {
                "name": name,
                "onlineStatus": status,
            }
        )

    return {
        "devices": ui_devices,
        "meta": {
            "generatedAtUtc": datetime.now(timezone.utc).isoformat(),
        },
    }


def summarize_groups_of_interest(devices):
    counts_by_label = {label: {} for label in GROUPS_OF_INTEREST.values()}

    for d in devices:
        dev = d.get("device") if isinstance(d.get("device"), dict) else d
        dev_group_id = dev.get("device-groupid")
        if not dev_group_id or dev_group_id not in GROUP_IDS_OF_INTEREST:
            continue

        label = GROUPS_OF_INTEREST[dev_group_id]
        status = dev.get("device-status", "Unknown")

        group_counts = counts_by_label.setdefault(label, {})
        group_counts[status] = group_counts.get(status, 0) + 1

    group_summaries = []
    for label, status_counts in counts_by_label.items():
        total = sum(status_counts.values())
        online = status_counts.get("Online", 0)
        online_pct = round((online / total) * 100, 1) if total else 0.0

        group_summaries.append(
            {
                "name": label,
                "counts": status_counts,
                "total": total,
                "onlinePct": online_pct,
            }
        )

    return {
        "groups": group_summaries,
        "meta": {
            "generatedAtUtc": datetime.now(timezone.utc).isoformat(),
            "groupCount": len(group_summaries),
        },
    }


def main():
    print("Fetching *account* devices from XiO Cloud (single v1 call)...")
    devices = fetch_account_devices()
    print(f"Fetched {len(devices)} devices from account {ACCOUNT_ID}")

    summary = summarize_overall(devices)
    with open("xio-summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    print("Wrote xio-summary.json")

    ui_devices = build_ui_devices(devices)
    with open("xio-devices-ui.json", "w", encoding="utf-8") as f:
        json.dump(ui_devices, f, indent=2)
    print("Wrote xio-devices-ui.json")

    group_summary = summarize_groups_of_interest(devices)
    with open("xio-groups-summary.json", "w", encoding="utf-8") as f:
        json.dump(group_summary, f, indent=2)
    print(
        f"Wrote xio-groups-summary.json with {group_summary['meta']['groupCount']} groups"
    )
    for g in group_summary["groups"]:
        print(f"  {g['name']}: {g['total']} devices")


if __name__ == "__main__":
    main()
