from datetime import datetime, timezone
import json
import os
import requests

BASE_URL = "https://api.crestron.io"

ACCOUNT_ID = os.environ.get("XIO_ACCOUNT_ID")
SUB_KEY = os.environ.get("XIO_SUBSCRIPTION_KEY")


GROUP_ID = os.environ.get(
    "XIO_GROUP_ID",
    "5128cb10-3b9f-4ad9-9e68-284b5e7f1460",
)

if not ACCOUNT_ID or not SUB_KEY:
    raise SystemExit("Missing XIO_ACCOUNT_ID or XIO_SUBSCRIPTION_KEY env vars")

HEADERS = {
    "XiO-subscription-key": SUB_KEY,
    "Accept": "application/json",
}


def _extract_list(data):

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


def fetch_group_devices(account_id, group_id):

    if not group_id:
        return []

    url = f"{BASE_URL}/api/v1/group/accountid/{account_id}/groupid/{group_id}/devices"
    resp = requests.get(url, headers=HEADERS, timeout=30)

    if resp.status_code == 429:
        raise SystemExit(
            "XiO group API returned 429 Too Many Requests.\n"
            "You’ve hit the rate limit; wait a few minutes before running again."
        )

    if resp.status_code == 404:
        print(f"Group {group_id} not found (404). Returning empty list.")
        return []

    resp.raise_for_status()
    data = resp.json()
    return _extract_list(data)


def summarize(devices):

    status_counts = {}
    for d in devices:
        # Handle flat or nested device objects
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


def build_group_devices_payload(devices, group_id):

    group_devices = []

    for d in devices:
        dev_obj = d.get("device") if isinstance(d.get("device"), dict) else d

        group_id_value = (
            dev_obj.get("device-groupid")
            or dev_obj.get("groupId")
            or dev_obj.get("group-id")
            or group_id 
        )

        group_devices.append({
            "id": dev_obj.get("device-id") or dev_obj.get("id"),
            "name": (
                dev_obj.get("device-name")
                or dev_obj.get("Name")
                or dev_obj.get("name")
            ),
            "status": (
                dev_obj.get("device-status")
                or dev_obj.get("status")
                or dev_obj.get("Online Status")
            ),
            "groupId": group_id_value,
            "roomName": (
                dev_obj.get("room-name")
                or dev_obj.get("Room Name")
                or dev_obj.get("roomName")
            ),
        })

    return {
        "groupId": group_id,
        "deviceCount": len(group_devices),
        "devices": group_devices,
        "meta": {
            "generatedAtUtc": datetime.now(timezone.utc).isoformat(),
        },
    }


def main():

    print("Fetching *account* devices from XiO Cloud...")
    account_devices = fetch_account_devices()
    print(f"Fetched {len(account_devices)} devices for account {ACCOUNT_ID}")

    summary = summarize(account_devices)
    with open("xio-summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    print("Wrote xio-summary.json")


    print(f"Fetching *group* devices for group {GROUP_ID}...")
    group_devices = fetch_group_devices(ACCOUNT_ID, GROUP_ID)
    print(f"Fetched {len(group_devices)} devices for group {GROUP_ID}")

    group_payload = build_group_devices_payload(group_devices, GROUP_ID)
    with open("xio-group-devices.json", "w", encoding="utf-8") as f:
        json.dump(group_payload, f, indent=2)

    print(
        f"Wrote xio-group-devices.json for group {GROUP_ID} "
        f"with {group_payload['deviceCount']} devices"
    )


if __name__ == "__main__":
    main()
