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

# Internal-only: UFIT group to highlight in the UI.
# This ID never gets written to JSON.
UFIT_GROUP_ID = os.environ.get(
    "XIO_UFIT_GROUP_ID",
    "5128cb10-3b9f-4ad9-9e68-284b5e7f1460",  # your known group id
)

# Fallback label if we can't find a group name in XiO
UFIT_DEFAULT_LABEL = os.environ.get("XIO_UFIT_LABEL", "UFIT Learning Space")


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
    Global/account summary JSON (xio-summary.json).

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


def _get_group_name(dev_obj):
    """
    Try to pull a human-readable group name from the device object.

    Adjust these keys if XiO uses different field names for group names.
    """
    return (
        dev_obj.get("device-groupname")
        or dev_obj.get("group-name")
        or dev_obj.get("groupName")
        or dev_obj.get("device-group")
        or dev_obj.get("Group Name")
        or None
    )


def summarize_groups(devices, highlight_group_id=None, default_highlight_label=None):
    """
    Per-group status from the full account device list.

    We group internally by groupId, but we DO NOT expose groupId
    in the JSON output. Instead we expose:

    {
      "meta": { "generatedAtUtc": "..." },
      "groups": [
        {
          "name": "Some XiO Group",
          "deviceCounts": { "Online": n, "Offline": n, ... },
          "totalDevices": n,
          "onlinePct": 42.5
        },
        ...
      ],
      "highlight": {
        "label": "UFIT Learning Space",
        "deviceCounts": { ... },
        "totalDevices": n,
        "onlinePct": 50.0
      }
    }
    """
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
        name = _get_group_name(dev_obj)

        if gid not in groups_raw:
            groups_raw[gid] = {
                "name": name,
                "deviceCounts": {},
                "totalDevices": 0,
            }

        g = groups_raw[gid]

        if not g["name"] and name:
            g["name"] = name

        g["deviceCounts"][status] = g["deviceCounts"].get(status, 0) + 1
        g["totalDevices"] += 1

    groups_list = []
    highlight_data = None


    sorted_items = sorted(
        groups_raw.items(),
        key=lambda kv: ((kv[1]["name"] or "").lower(), kv[0])
    )

    for idx, (gid, g) in enumerate(sorted_items, start=1):
        counts = g["deviceCounts"]
        total = g["totalDevices"]
        online = counts.get("Online", 0)
        online_pct = round((online / total) * 100, 1) if total else 0.0

        display_name = g["name"] or f"Group {idx}"

        group_obj = {
            "name": display_name,
            "deviceCounts": counts,
            "totalDevices": total,
            "onlinePct": online_pct,
        }
        groups_list.append(group_obj)


        if highlight_group_id and gid == highlight_group_id:
            label = display_name
            if not g["name"] and default_highlight_label:

                label = default_highlight_label

            highlight_data = {
                "label": label,
                "deviceCounts": counts,
                "totalDevices": total,
                "onlinePct": online_pct,
            }

    if not highlight_data and sorted_items:
        gid_top, g_top = sorted_items[0]
        counts = g_top["deviceCounts"]
        total = g_top["totalDevices"]
        online = counts.get("Online", 0)
        online_pct = round((online / total) * 100, 1) if total else 0.0

        label = g_top["name"] or default_highlight_label or "Highlighted Group"

        highlight_data = {
            "label": label,
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
        default_highlight_label=UFIT_DEFAULT_LABEL,
    )
    with open("xio-groups-status.json", "w", encoding="utf-8") as f:
        json.dump(groups_summary, f, indent=2)
    print("Wrote xio-groups-status.json")


if __name__ == "__main__":
    main()
