"""Anonymised payloads shaped like the ones solaredge-web returns."""

from typing import Any

SITE_ID = "SITE-TEST"

# SITE -> INVERTER -> STRING -> OPTIMIZER, the shape async_get_equipment walks.
# OPT-TEST-3 is retired: it keeps the display name of its replacement, which is
# exactly the collision that position-keyed statistics have to survive.
EQUIPMENT_TREE: dict[str, Any] = {
    "type": "SITE",
    "uuid": SITE_ID,
    "name": "Test Site",
    "children": [
        {
            "type": "INVERTER",
            "serial": "INV-TEST-1",
            "name": "Inverter 1",
            "order": 1,
            "children": [
                {
                    "type": "STRING",
                    "uuid": "STR-TEST-1",
                    "name": "1.1",
                    "order": 1,
                    "children": [
                        {
                            "type": "OPTIMIZER",
                            "serial": "OPT-TEST-1",
                            "name": "1.1.1",
                            "children": [],
                        },
                        {
                            "type": "OPTIMIZER",
                            "serial": "OPT-TEST-2",
                            "name": "1.1.2",
                            "children": [],
                        },
                    ],
                }
            ],
        }
    ],
}


def equipment_dict(*, include_inactive: bool = False) -> dict[str, dict[str, Any]]:
    """Flatten EQUIPMENT_TREE the way async_get_equipment does."""
    result: dict[str, dict[str, Any]] = {}

    def walk(node: dict[str, Any]) -> None:
        if node.get("type") not in ("FOLDER", "SITE"):
            device_id = (
                node.get("serial")
                or node.get("properties", {}).get("identifier")
                or node.get("uuid")
            )
            if device_id:
                result[device_id] = node
        for child in node.get("children", []):
            walk(child)

    walk(EQUIPMENT_TREE)
    if include_inactive:
        return result
    return {k: v for k, v in result.items() if v.get("properties", {}).get("status") != "INACTIVE"}


SITE_INFORMATION: dict[str, Any] = {
    "peakPower": 11.7,
    "siteTimeZone": "Asia/Jerusalem",
    "installationDate": "2026-12-02",
}

SITE_COMPONENTS: dict[str, Any] = {
    "hasConsumptionAndGrid": False,
    "hasStorage": False,
    "hasProduction": True,
    "inverterCount": 1,
}
