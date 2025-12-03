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


def _first(dev, *keys):
    """
    Return the first non-empty value from dev for any of the given keys.
    Helps normalize XiO's inconsistent field naming.
    """
    if not isinstance(dev, dict):
        return None
    for k in keys:
        v = dev.get(k)
        if v not in (None, "", []):
            return v
    return None


def _extract_device_list(data):
    """
    Account Devices sometimes returns a list directly, sometimes wrapped.

    Tries common wrappers like Devices/devices/items/DeviceList.
    """
    if isinstance(data, list):
        return data

    if isinstance(data, dict):
        for key in ("Devices", "devices", "items", "DeviceList"):
            if key in data and isinstance(data[key], list):
                return data[key]

    return []


def _extract_group_list(data):
    if isinstance(data, list):
        return data

    if isinstance(data, dict):
        for key in ("Groups", "groups", "items"):
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
    """
    Overall status summary (all devices) for xio-summary.json
    """
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


def fetch_account_groups():
    url = f"{BASE_URL}/api/v1/group/accountid/{ACCOUNT_ID}/groups"
    resp = requests.get(url, headers=HEADERS, timeout=30)

    if resp.status_code == 429:
        raise SystemExit(
            "XiO API returned 429 Too Many Requests for Account Groups.\n"
            "This is a V1 endpoint; try again after at least five minutes."
        )

    resp.raise_for_status()
    raw = resp.json()
    groups = _extract_group_list(raw)

    if not groups and isinstance(raw, dict):
        return {
            "groups": raw,
            "meta": {
                "generatedAtUtc": datetime.now(timezone.utc).isoformat(),
                "source": "v1 Account Groups (dict)",
            },
        }

    return {
        "groups": groups,
        "meta": {
            "generatedAtUtc": datetime.now(timezone.utc).isoformat(),
            "source": "v1 Account Groups",
        },
    }


def refresh_group_tree_file():
    print("Fetching account group tree from XiO Cloud...")
    data = fetch_account_groups()
    groups = data.get("groups")

    if isinstance(groups, list):
        group_count = len(groups)
    elif isinstance(groups, dict):
        group_count = len(groups)
    else:
        group_count = 0

    with open("xio-groups-tree.json", "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    print(f"Wrote xio-groups-tree.json with {group_count} groups (raw count)")


def load_group_tree_parent_map():
    try:
        with open("xio-groups-tree.json", "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        print("WARNING: xio-groups-tree.json not found; group summaries will be empty.")
        return {}

    raw_groups = data.get("groups", data)
    groups_list = _extract_group_list(raw_groups)

    if not isinstance(groups_list, list) and isinstance(raw_groups, dict):
        groups_list = [v for v in raw_groups.values() if isinstance(v, dict)]

    if not isinstance(groups_list, list) or not groups_list:
        print("WARNING: xio-groups-tree.json did not contain a recognizable groups list.")
        return {}

    sample = None
    for g in groups_list:
        if isinstance(g, dict):
            sample = g
            break

    if not sample:
        print("WARNING: No valid group dicts found in xio-groups-tree.json.")
        return {}

    id_candidates = ("id", "groupid", "GroupId", "GroupID", "group-id")
    parent_candidates = (
        "ParentGroupId",
        "parentGroupId",
        "parent-groupid",
        "GroupParentId",
        "ParentId",
    )

    id_key = next((k for k in id_candidates if k in sample), None)
    parent_key = next((k for k in parent_candidates if k in sample), None)

    if not id_key:
        print("WARNING: Could not detect a group ID field in group tree; skipping group summaries.")
        return {}

    if not parent_key:
        print("WARNING: Could not detect a parent group field in group tree; will treat groups as flat.")

    parent_map = {}
    for g in groups_list:
        if not isinstance(g, dict):
            continue
        gid = g.get(id_key)
        if not gid:
            continue
        parent = g.get(parent_key) if parent_key else None
        parent_map[gid] = parent

    print(
        f"Loaded {len(parent_map)} groups from xio-groups-tree.json "
        f"(id field='{id_key}', parent field='{parent_key or 'None'}')"
    )
    return parent_map


def find_interest_root_group(device_group_id, parent_map):
    visited = set()
    gid = device_group_id

    while gid and gid not in visited:
        if gid in GROUP_IDS_OF_INTEREST:
            return gid

        visited.add(gid)
        gid = parent_map.get(gid)

    return None


def summarize_groups_of_interest(devices, parent_map):

    counts_by_label = {label: {} for label in GROUPS_OF_INTEREST.values()}

    for d in devices:
        dev = d.get("device") if isinstance(d.get("device"), dict) else d
        dev_group_id = dev.get("device-groupid")
        if not dev_group_id:
            continue

        root_gid = find_interest_root_group(dev_group_id, parent_map)
        if not root_gid:
            continue

        label = GROUPS_OF_INTEREST[root_gid]
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


def build_power_bi_flat_files(devices, group_summary=None):
    """
    Build flat, Power BI–friendly JSON files:

      - xio-devices-flat.json : one row per device
      - xio-rooms-flat.json   : one row per room (counts)
      - xio-groups-flat.json  : one row per group of interest (optional)

    These are meant to be consumed directly by Power BI via 'Get data -> Web'.
    """
    devices_flat = []
    rooms_map = {}

    for d in devices:
        dev = d.get("device") if isinstance(d.get("device"), dict) else d

        device_id = _first(dev, "device-id", "DeviceId", "DeviceID", "id")
        name = _first(dev, "device-name", "Name", "name")
        status = _first(dev, "device-status", "Online Status", "status")
        group_id = _first(dev, "device-groupid", "GroupId", "groupId")

        room_name = _first(dev, "room-name", "roomName", "RoomName")
        building_name = _first(
            dev,
            "building-name",
            "buildingName",
            "BuildingName",
            "building",
            "location-buildingname",
        )

        model = _first(dev, "device-model", "Model", "model")
        serial = _first(dev, "serial-number", "serialNumber", "SerialNumber")
        firmware = _first(dev, "firmware-version", "firmwareVersion", "FirmwareVersion")
        last_seen = _first(dev, "last-contact", "lastContact", "LastContact")

        devices_flat.append(
            {
                "device_id": device_id,
                "name": name,
                "status": status,
                "group_id": group_id,
                "room_name": room_name,
                "building_name": building_name,
                "model": model,
                "serial_number": serial,
                "firmware": firmware,
                "last_seen": last_seen,
            }
        )


        room_key = (building_name, room_name)
        if room_key not in rooms_map:
            rooms_map[room_key] = {
                "building_name": building_name,
                "room_name": room_name,
                "device_count": 0,
                "online_count": 0,
                "offline_count": 0,
            }

        rooms_map[room_key]["device_count"] += 1
        status_l = str(status).lower()
        if status_l == "online":
            rooms_map[room_key]["online_count"] += 1
        elif status_l == "offline":
            rooms_map[room_key]["offline_count"] += 1

    now_iso = datetime.now(timezone.utc).isoformat()


    rooms_list = []
    for (building_name, room_name), counts in rooms_map.items():
        room_id = f"{building_name or 'Unknown'}|{room_name or 'Unknown'}"
        rooms_list.append(
            {
                "room_id": room_id,
                "building_name": counts["building_name"],
                "room_name": counts["room_name"],
                "device_count": counts["device_count"],
                "online_count": counts["online_count"],
                "offline_count": counts["offline_count"],
                "last_updated": now_iso,
            }
        )

    groups_flat = []
    if group_summary and isinstance(group_summary, dict):
        meta = group_summary.get("meta", {})
        groups = group_summary.get("groups", [])
        for g in groups:
            if not isinstance(g, dict):
                continue
            counts = g.get("counts", {}) or {}
            total = g.get("total", 0)
            online = counts.get("Online", 0)
            offline = counts.get("Offline", 0)

            groups_flat.append(
                {
                    "group_name": g.get("name"),
                    "total_devices": total,
                    "online_count": online,
                    "offline_count": offline,
                    "online_pct": g.get("onlinePct", 0.0),
                    "last_updated": meta.get("generatedAtUtc", now_iso),
                }
            )

    with open("xio-devices-flat.json", "w", encoding="utf-8") as f:
        json.dump(devices_flat, f, indent=2)

    with open("xio-rooms-flat.json", "w", encoding="utf-8") as f:
        json.dump(rooms_list, f, indent=2)

    with open("xio-groups-flat.json", "w", encoding="utf-8") as f:
        json.dump(groups_flat, f, indent=2)

    print(
        f"Wrote xio-devices-flat.json ({len(devices_flat)} devices), "
        f"xio-rooms-flat.json ({len(rooms_list)} rooms), "
        f"xio-groups-flat.json ({len(groups_flat)} groups)"
    )


def main():
    if len(sys.argv) > 1 and sys.argv[1] in ("--refresh-groups", "refresh-groups"):
        refresh_group_tree_file()
        return

    print("Fetching *account* devices from XiO Cloud (single v1 call)...")
    devices = fetch_account_devices()
    print(f"Fetched {len(devices)} devices from account {ACCOUNT_ID}")

    # Global summary
    summary = summarize_overall(devices)
    with open("xio-summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    print("Wrote xio-summary.json")

    ui_devices = build_ui_devices(devices)
    with open("xio-devices-ui.json", "w", encoding="utf-8") as f:
        json.dump(ui_devices, f, indent=2)
    print("Wrote xio-devices-ui.json")

    parent_map = load_group_tree_parent_map()
    group_summary = None

    if parent_map:
        group_summary = summarize_groups_of_interest(devices, parent_map)
        with open("xio-groups-summary.json", "w", encoding="utf-8") as f:
            json.dump(group_summary, f, indent=2)
        print(
            f"Wrote xio-groups-summary.json with {group_summary['meta']['groupCount']} groups"
        )
        for g in group_summary["groups"]:
            print(f"  {g['name']}: {g['total']} devices")
    else:
        print("Skipped writing xio-groups-summary.json (no group tree loaded).")

    build_power_bi_flat_files(devices, group_summary)


if __name__ == "__main__":
    main()
