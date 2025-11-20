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

# --------------------------------------------------------------------
# Only summarize the groups you actually care about.
# Keys = XiO group IDs, Values = friendly names used in JSON/UI.
# --------------------------------------------------------------------
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


def fetch_group_devices(group_id):
    """
    GET /api/v1/group/accountid/{accountid}/groupid/{groupid}/devices
    Returns all devices for a specific group.
    """
    url = f"{BASE_URL}/api/v1/group/accountid/{ACCOUNT_ID}/groupid/{group_id}/devices"
    resp = requests.get(url, headers=HEADERS, timeout=30)

    if resp.status_code == 429:
        raise SystemExit(
            f"XiO API returned 429 Too Many Requests for group {group_id}.\n"
            "Try reducing the workflow frequency or number of groups."
        )

    resp.raise_for_status()
    data = resp.json()
    return _extract_list(data)


def summarize_devices(devices):
    """
    Given a list of devices, return (status_counts, total, onlinePct).
    """
    status_counts = {}

    for d in devices:
        dev_obj = d.get("device") if isinstance(d.get("device"), dict) else d
        status = dev_obj.get("device-status", "Unknown")
        status_counts[status] = status_counts.get(status, 0) + 1

    total_devices = len(devices)
    online = status_counts.get("Online", 0)
    online_pct = round((online / total_devices) * 100, 1) if total_devices else 0.0

    return status_counts, total_devices, online_pct


def build_ui_devices(devices):
    """
    Minimal devices payload: name + onlineStatus for UI tables if needed.
    """
    ui_devices = []

    for d in devices:
        dev_obj = d.get("device") if isinstance(d.get("device"), dict) else d
        name = (
            dev_obj.get("device-name")
            or dev_obj.get("Name")
            or dev_obj.get("name")
        )
        status = (
            dev_obj.get("device-status")
            or dev_obj.get("Online Status")
            or dev_obj.get("status")
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


def main():
    print("Fetching XiO devices for configured groups...")
    all_devices = []
    group_summaries = []

    # Pull devices for each group ID
    for group_id, label in GROUPS_OF_INTEREST.items():
        print(f"- Group: {label} ({group_id})")
        devices = fetch_group_devices(group_id)
        print(f"  Fetched {len(devices)} devices")

        all_devices.extend(devices)

        counts, total, online_pct = summarize_devices(devices)
        group_summaries.append(
            {
                "name": label,
                "counts": counts,
                "total": total,
                "onlinePct": online_pct,
            }
        )

    now_iso = datetime.now(timezone.utc).isoformat()


    global_counts, global_total, global_online_pct = summarize_devices(all_devices)

    summary_json = {
        "device": {
            "counts": global_counts,
            "total": global_total,
            "onlinePct": global_online_pct,
        },
        "meta": {
            "generatedAtUtc": now_iso,
        },
    }

    with open("xio-summary.json", "w", encoding="utf-8") as f:
        json.dump(summary_json, f, indent=2)
    print("Wrote xio-summary.json")

    ui_devices_json = build_ui_devices(all_devices)
    with open("xio-devices-ui.json", "w", encoding="utf-8") as f:
        json.dump(ui_devices_json, f, indent=2)
    print("Wrote xio-devices-ui.json")

    groups_summary_json = {
        "groups": group_summaries,
        "meta": {
            "generatedAtUtc": now_iso,
            "groupCount": len(group_summaries),
        },
    }

    with open("xio-groups-summary.json", "w", encoding="utf-8") as f:
        json.dump(groups_summary_json, f, indent=2)
    print("Wrote xio-groups-summary.json")


if __name__ == "__main__":
    main()
