from datetime import datetime, timezone
import json
import os
import requests

BASE_URL = "https://api.crestron.io"

ACCOUNT_ID = os.environ.get("XIO_ACCOUNT_ID")
SUB_KEY = os.environ.get("XIO_SUBSCRIPTION_KEY")


GROUP_ID = os.environ.get(
    "XIO_GROUP_ID",
    "5128cb10-3b9f-4ad9-9e68-284b5e7f1460"
)

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

        for key in ("Devices", "devices", "items", "DeviceList"):
            if key in data and isinstance(data[key], list):
                return data[key]
        return []
    elif isinstance(data, list):
        return data
    else:
        return []


def fetch_rooms():
    """
    OPTIONAL: only if/when you have a rooms endpoint in XiO.
    This will not crash the whole script if the endpoint is missing.
    """
    url = f"{BASE_URL}/api/v1/room/accountid/{ACCOUNT_ID}/rooms"
    resp = requests.get(url, headers=HEADERS, timeout=30)

    if resp.status_code in (404, 501):
        print("Rooms endpoint not available (status", resp.status_code, ") – skipping rooms.")
        return []

    if resp.status_code == 429:
        print("XiO rooms API returned 429 Too Many Requests – skipping rooms this run.")
        return []

    resp.raise_for_status()
    data = resp.json()

    if isinstance(data, dict):
        for key in ("Rooms", "rooms", "items"):
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
    """
    Minimal devices payload: name + onlineStatus
    """
    ui_devices = []

    for d in devices:

        dev_obj = d.get("device") if isinstance(d.get("device"), dict) else d

        ui_devices.append({
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
        })

    return {
        "devices": ui_devices,
        "meta": {
            "generatedAtUtc": datetime.now(timezone.utc).isoformat(),
        },
    }


def build_ui_rooms(rooms):
    """
    Minimal rooms payload: roomName + occupied
    """
    ui_rooms = []

    for r in rooms:
        ui_rooms.append({
            "roomName": (
                r.get("room-name")
                or r.get("Room Name")
                or r.get("roomName")
            ),
            "occupied": (
                r.get("occupied")
                or r.get("Occupied")
                or r.get("occupancy-status")
            ),
        })

    return {
        "rooms": ui_rooms,
        "meta": {
            "generatedAtUtc": datetime.now(timezone.utc).isoformat(),
        },
    }


def filter_devices_by_group(devices, group_id):
    """
    Filter the devices list down to a specific XiO group.

    We look for 'device-groupid' on either the root object or inside 'device'.
    """
    if not group_id:
        return []

    group_devices = []

    for d in devices:

        dev_obj = d.get("device") if isinstance(d.get("device"), dict) else d

        dev_group = (
            dev_obj.get("device-groupid")  
            or dev_obj.get("groupId")
        )

        if dev_group == group_id:
            group_devices.append(d)

    return group_devices


def main():
    print("Fetching devices from XiO Cloud...")
    devices = fetch_devices()
    print(f"Fetched {len(devices)} devices total for account {ACCOUNT_ID}")


    summary = summarize(devices)
    summary["meta"]["scope"] = "account"
    summary["meta"]["groupId"] = None

    with open("xio-summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    print("Wrote xio-summary.json")

    ui_devices = build_ui_devices(devices)
    ui_devices["meta"]["scope"] = "account"
    ui_devices["meta"]["groupId"] = None

    with open("xio-devices-ui.json", "w", encoding="utf-8") as f:
        json.dump(ui_devices, f, indent=2)
    print("Wrote xio-devices-ui.json")

    if GROUP_ID:
        group_devices = filter_devices_by_group(devices, GROUP_ID)
        if group_devices:
            print(f"Found {len(group_devices)} devices in group {GROUP_ID}")

            group_summary = summarize(group_devices)
            group_summary["meta"]["scope"] = "group"
            group_summary["meta"]["groupId"] = GROUP_ID

            with open("xio-summary-group.json", "w", encoding="utf-8") as f:
                json.dump(group_summary, f, indent=2)
            print("Wrote xio-summary-group.json")

            ui_group_devices = build_ui_devices(group_devices)
            ui_group_devices["meta"]["scope"] = "group"
            ui_group_devices["meta"]["groupId"] = GROUP_ID

            with open("xio-devices-ui-group.json", "w", encoding="utf-8") as f:
                json.dump(ui_group_devices, f, indent=2)
            print("Wrote xio-devices-ui-group.json")
        else:
            print(f"No devices matched group {GROUP_ID}; skipping group JSON.")

    try:
        rooms = fetch_rooms()
    except Exception as e:
        print("Error fetching rooms; skipping rooms for this run:", e)
    else:
        if rooms:
            print(f"Fetched {len(rooms)} rooms")
            ui_rooms = build_ui_rooms(rooms)
            with open("xio-rooms-ui.json", "w", encoding="utf-8") as f:
                json.dump(ui_rooms, f, indent=2)
            print("Wrote xio-rooms-ui.json")
        else:
            print("No rooms returned; skipping xio-rooms-ui.json write.")


if __name__ == "__main__":
    main()
