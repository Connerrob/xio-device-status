from datetime import datetime, timezone
import json
import os
import time
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


SCAN_BATCH_SIZE = 1500 


def _first(d, *keys):
    if not isinstance(d, dict):
        return None
    for k in keys:
        v = d.get(k)
        if v not in (None, "", []):
            return v
    return None


def _extract_device_list(data):
    if isinstance(data, list):
        return data

    if isinstance(data, dict):
        for key in ("Devices", "devices", "items", "DeviceList"):
            if key in data and isinstance(data[key], list):
                return data[key]

    return []


def fetch_account_devices():
    """
    Same account-devices call as in xio_summary.py.
    We only use this to get the list of device IDs.
    """
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


def load_firmware_metadata():
    """
    Load existing firmware metadata if it exists.

    Structure:
    {
      "meta": {...},
      "devices": {
        "<device-id>": {
          "name": "...",
          "device_model": "...",
          "firmware": "...",
          "serial": "...",
          "mac_address": "...",
          "lastStatusFetchUtc": "..."
        },
        ...
      }
    }
    """
    try:
        with open("xio-firmware-metadata.json", "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return {"meta": {}, "devices": {}}

    meta = data.get("meta", {})
    devices = data.get("devices", {})
    if not isinstance(devices, dict):
        devices = {}
    return {"meta": meta, "devices": devices}


def save_firmware_metadata(meta_obj):
    meta_obj["meta"]["lastUpdatedUtc"] = datetime.now(timezone.utc).isoformat()
    with open("xio-firmware-metadata.json", "w", encoding="utf-8") as f:
        json.dump(meta_obj, f, indent=2)
    print(
        f"Wrote xio-firmware-metadata.json "
        f"({len(meta_obj.get('devices', {}))} devices with metadata)"
    )


def fetch_device_status(device_id):
    """
    Call Device Status (V1) for a single device:
    GET /api/v1/device/accountid/{accountid}/deviceid/{deviceid}/status
    """
    url = f"{BASE_URL}/api/v1/device/accountid/{ACCOUNT_ID}/deviceid/{device_id}/status"
    resp = requests.get(url, headers=HEADERS, timeout=30)

    if resp.status_code == 429:
        raise SystemExit(
            "XiO API returned 429 Too Many Requests for Device Status.\n"
            "Stopping scan and will continue on next scheduled run."
        )

    resp.raise_for_status()
    return resp.json()


def main():
    print("Loading existing firmware metadata (if any)...")
    meta_obj = load_firmware_metadata()
    firmware_devices = meta_obj["devices"]
    state = meta_obj.get("meta", {})

    print("Fetching account devices list for firmware scan...")
    account_devices = fetch_account_devices()
    print(f"Fetched {len(account_devices)} devices from account {ACCOUNT_ID}")

    # Build a stable, ordered list of device IDs
    device_ids = []
    device_id_to_name = {}
    device_id_to_model = {}

    for d in account_devices:
        dev = d.get("device") if isinstance(d.get("device"), dict) else d
        dev_id = _first(dev, "device-id", "DeviceId", "DeviceID", "id")
        if not dev_id:
            continue
        name = _first(dev, "device-name", "Name", "name")
        model = _first(dev, "device-model", "Device-Model", "Model", "model")

        device_ids.append(dev_id)
        device_id_to_name[dev_id] = name
        device_id_to_model[dev_id] = model

    if not device_ids:
        print("No device IDs found; nothing to scan.")
        return

    device_ids = sorted(set(device_ids))
    total_devices = len(device_ids)

    last_index = int(state.get("lastScanIndex", 0))
    batch_size = min(SCAN_BATCH_SIZE, total_devices)
    print(
        f"Beginning firmware/status scan from index {last_index} "
        f"for up to {batch_size} devices..."
    )

    scanned = 0
    now_iso = datetime.now(timezone.utc).isoformat()

    for i in range(batch_size):
        idx = (last_index + i) % total_devices
        dev_id = device_ids[idx]
        name = device_id_to_name.get(dev_id)
        model = device_id_to_model.get(dev_id)

        print(f"Scanning status for device {dev_id} ({name or 'Unnamed'})...")

        try:
            status_payload = fetch_device_status(dev_id)
        except SystemExit as e:
            print(str(e))
            break

        dev_obj = status_payload.get("device", {})
        network = status_payload.get("network", {})

        firmware = _first(
            dev_obj,
            "firmware-version",
            "Firmware-Version",
            "firmwareVersion",
            "FirmwareVersion",
        )
        serial = _first(
            dev_obj,
            "serial-number",
            "Serial-Number",
            "serialNumber",
            "SerialNumber",
        )

        mac_address = _first(
            network,
            "nic-1-mac-address",
            "nic-2-mac-address",
            "Nic-1-Mac-Address",
            "Nic-2-Mac-Address",
        )

        firmware_devices[dev_id] = {
            "name": name or dev_obj.get("device-name"),
            "device_model": model or dev_obj.get("device-model"),
            "firmware": firmware,
            "serial": serial,
            "mac_address": mac_address,
            "lastStatusFetchUtc": now_iso,
        }

        scanned += 1
        time.sleep(0.2)

    new_index = (last_index + scanned) % total_devices
    state["lastScanIndex"] = new_index
    state["lastDeviceCount"] = total_devices
    state["scanBatchSize"] = SCAN_BATCH_SIZE
    meta_obj["meta"] = state

    print(f"Scanned {scanned} devices this run; next scan will start at index {new_index}.")
    save_firmware_metadata(meta_obj)


if __name__ == "__main__":
    main()
