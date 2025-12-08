import os
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone

import requests

BASE_URL = os.environ.get(
    "SASSAFRAS_BASE_URL",
    "https://at-keyserver.it.ufl.edu/api/v2",
)
ACCESS_TOKEN = os.environ["SASSAFRAS_TOKEN"]

FIELDS = "ID,Ident,Name,Division,Status,Allowed"

STATUS_LABELS = {
    0: "Offline",
    2: "Available",
    4: "In Use",
}
ALLOWED_STATUS = set(STATUS_LABELS.keys())

DEDICATED_ALLOWED_VALUES = {"4", 4}

BUILDING_PATTERNS = {
    "Classrooms": ["classroom support"],
    "Marston Science Library": ["marston"],
    "Library West": ["lbw", "lw "],
    "Smathers Library": ["smathers"],
    "Antevy Hall": ["arch"],
    "Architecture & Fine Arts Library": ["afa library"],
    "Health Science Center Library": ["hscl"],
    "Education Library": ["norman library", "edu"],
    "Computer Science & Engineering": ["cse", "computer science"],
    "Norman Hall": ["nrn 1st floor", "norman hall"],
    "Newell Hall": ["newell"],
    "Weil Hall": ["weil"],
    "Turlington Hall": ["turlington"],
    "Holland Law": ["law library"],
    "Hawkins Center": ["uaa"],
    "McCarty Hall B": ["mccb"],
    "Hub": ["hub 120"],
}


def normalize_status(raw_status):
    if raw_status is None:
        return None

    try:
        code = int(raw_status)
    except (TypeError, ValueError):
        code = None

    if code is not None:
        if code == 1:

            return None
        if code == 3:

            return 2
        return code

    s = str(raw_status).strip().lower()
    if s.startswith("off"):
        return 0
    if "idle" in s:
        return 2
    if "avail" in s or "online" in s:
        return 2
    if "in use" in s or "active" in s:
        return 4
    return None


def get_building_name(division: str) -> str:
    text = (division or "").lower()

    for building, patterns in BUILDING_PATTERNS.items():
        for pattern in patterns:
            if pattern in text:
                return building

    if division and len(division.split()) <= 3:
        return division

    return "Other / Ungrouped"


def fetch_all_computers():
    url = f"{BASE_URL}/computer/items"
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Accept": "application/json",
    }
    params = {"fields": FIELDS}

    resp = requests.get(url, headers=headers, params=params, timeout=180)
    resp.raise_for_status()
    return resp.json()


def is_dedicated(allowed_val):
    if allowed_val is None:
        return False


    if allowed_val in DEDICATED_ALLOWED_VALUES:
        return True


    as_str = str(allowed_val).strip().lower()
    if as_str in DEDICATED_ALLOWED_VALUES:
        return True

    return False


def build_summary(computers):
    overall = Counter()
    by_division = defaultdict(Counter)
    by_building = defaultdict(Counter)
    building_divisions = defaultdict(set)

    seen_keys = set()

    for comp in computers:
        key = (
            comp.get("ID")
            or comp.get("Ident")
            or comp.get("ident")
            or comp.get("Name")
        )
        if key:
            if key in seen_keys:
                continue
            seen_keys.add(key)

        div_name_raw = comp.get("Division") or ""
        div_name_lower = div_name_raw.lower()

        # Exclude UFApps, LabVDI, and MADE@UF
        if (
            "ufapps" in div_name_lower
            or "labvdi" in div_name_lower
            or "made@uf" in div_name_lower
        ):
            continue


        allowed_val = comp.get("Allowed", None)
        if not is_dedicated(allowed_val):
            continue

        raw_status = comp.get("Status")
        status = normalize_status(raw_status)
        if status not in ALLOWED_STATUS:
            continue

        division = div_name_raw or "Unassigned"
        building = get_building_name(division)

        overall[status] += 1
        by_division[division][status] += 1
        by_building[building][status] += 1
        building_divisions[building].add(division)

    overall_list = [
        {
            "status_code": code,
            "status_label": STATUS_LABELS[code],
            "count": count,
        }
        for code, count in sorted(overall.items())
    ]

    divisions_list = []
    for division, counts in sorted(by_division.items()):
        statuses = [
            {
                "status_code": code,
                "status_label": STATUS_LABELS[code],
                "count": count,
            }
            for code, count in sorted(counts.items())
        ]
        divisions_list.append({
            "division": division,
            "total": sum(counts.values()),
            "statuses": statuses,
        })

    buildings_list = []
    for building, counts in sorted(by_building.items()):
        statuses = [
            {
                "status_code": code,
                "status_label": STATUS_LABELS[code],
                "count": count,
            }
            for code, count in sorted(counts.items())
        ]
        buildings_list.append({
            "building": building,
            "total": sum(counts.values()),
            "statuses": statuses,
            "divisions": sorted(building_divisions[building]),
        })

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status_labels": STATUS_LABELS,
        "overall": overall_list,
        "divisions": divisions_list,
        "buildings": buildings_list,
        "total_computers": sum(s["count"] for s in overall_list),
    }


def main():
    computers = fetch_all_computers()
    summary = build_summary(computers)

    out_path = "sassafras-computer-summary.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    print(f"Wrote {out_path}")
    print(f"Total Dedicated computers counted (deduped): {summary['total_computers']}")


if __name__ == "__main__":
    main()
