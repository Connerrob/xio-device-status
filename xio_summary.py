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


GROUPS_OF_INTEREST = {
    "4b8e5e57-861e-4a73-84d8-f1687ded87ca": "Malachowsky Hall",
    "ce2a359d-bc31-487b-98da-34c586a721e0": "Scheduling Panels",
    "9f292bd3-2a30-4c65-88fe-d0aa7873ea83": "UF Libraries",
    "ec748315-bcff-443d-b2d9-519d653ae43c": "UFIT AV Install Group",
    "1b7d0227-f9db-47a0-94ed-14d5d6e9261f": "UFIT Conference Rooms",
    "5128cb10-3b9f-4ad9-9e68-284b5e7f1460": "UFIT Learning Spaces",
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


def fetch_devices():

    url = f"{BASE_URL}/api/v1/device/accountid/{ACCOUNT_ID}/devices"
    resp = requests.get(url, headers=HEADERS, timeout=30)

    if resp.status_code == 429:
        raise SystemExit(
            "XiO API returned 429 Too Many Requests for Account Devices.\n"
            "V1 API calls are limited to 1 request per 5 minutes."
        )

    resp.raise_for_status()
    data = resp.json()
    devices = _extract_list(data)

    if not devices and isinstance(data, dict):
        values = [v for v in data.values() if isinstance(v, dict)]
        if values:
            return values

    return devices


def summarize_overall(devices):

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


def build_ui_devices(devices):

    ui_devices = []

    for d in devices:
        dev_obj = d.get("device") if isinstance(d.get("device"), dict) else d
        ui_devices.append(
            {
                "name": (
                    dev_obj.get("device-name")
                    or dev_obj.get("Name")
                    or dev_obj.get("name")
                ),
                "onlineStatus": (
                    dev_obj.get("device-status")
                    or dev_obj.get("Online Status")
                    or dev_obj.get("status")
                ),
            }
        )

    return {
        "devices": ui_devices,
        "meta": {
            "generatedAtUtc": datetime.now(timezone.utc).isoformat(),
        },
    }


def summarize_groups_of_interest(devices, groups_of_interest):
    """
    {
      "groups": [
        {
          "name": "UFIT Learning Spaces",
          "counts": { "Online": n, "Offline": n, ... },
          "total": N,
          "onlinePct": X.X
        },
        ...
      ],
      "meta": { ... }
    }
    """

    counts_by_name = {}


    for label in groups_of_interest.values():
        counts_by_name[label] = {}

    for d in devices:
        dev_obj = d.get("device") if isinstance(d.get("device"), dict) else d
        group_id = (
            dev_obj.get("device-groupid")
            or dev_obj.get("groupId")
            or dev_obj.get("group-id")
        )
        if not group_id:
            continue

        if group_id not in groups_of_interest:

            continue

        label = groups_of_interest[group_id]

        status = dev_obj.get("device-status", "Unknown")
        group_counts = counts_by_name.setdefault(label, {})
        group_counts[status] = group_counts.get(status, 0) + 1


    group_summaries = []
    for label, status_counts in counts_by_name.items():
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
    print("Fetching devices from XiO Cloud...")
    devices = fetch_devices()
    print(f"Fetched {len(devices)} devices")

    summary = summarize_overall(devices)
    with open("xio-summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    print("Wrote xio-summary.json")


    ui_devices = build_ui_devices(devices)
    with open("xio-devices-ui.json", "w", encoding="utf-8") as f:
        json.dump(ui_devices, f, indent=2)
    print("Wrote xio-devices-ui.json")


    group_summary = summarize_groups_of_interest(devices, GROUPS_OF_INTEREST)
    with open("xio-groups-summary.json", "w", encoding="utf-8") as f:
        json.dump(group_summary, f, indent=2)
    print(
        f"Wrote xio-groups-summary.json with {group_summary['meta']['groupCount']} groups"
    )


if __name__ == "__main__":
    main()
