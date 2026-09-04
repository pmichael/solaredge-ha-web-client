"""Layout parsing."""

from typing import Any

import pytest

from custom_components.solaredge_ha_web_client.models import build_site_snapshot

from .fixtures import (
    SITE_COMPONENTS,
    SITE_ID,
    SITE_INFORMATION,
    equipment_dict,
)


def _snapshot() -> Any:
    return build_site_snapshot(
        site_id=SITE_ID,
        equipment=equipment_dict(),
        site_information=SITE_INFORMATION,
        site_components=SITE_COMPONENTS,
    )


def test_reads_site_facts() -> None:
    """Peak power and timezone drive the forecast and statistics respectively."""
    snapshot = _snapshot()
    assert snapshot.site_id == SITE_ID
    assert snapshot.peak_power_kwp == 11.7
    assert snapshot.timezone == "Asia/Jerusalem"
    assert snapshot.has_meter is False
    assert snapshot.has_storage is False


def test_finds_inverters() -> None:
    snapshot = _snapshot()
    assert [inv.serial for inv in snapshot.inverters] == ["INV-TEST-1"]
    assert snapshot.inverters[0].display_name == "Inverter 1"


def test_finds_optimizers_with_their_ancestry() -> None:
    """Optimizers must know their inverter so devices can nest correctly."""
    snapshot = _snapshot()
    assert [opt.serial for opt in snapshot.optimizers] == ["OPT-TEST-1", "OPT-TEST-2"]
    first = snapshot.optimizers[0]
    assert first.display_name == "1.1.1"
    assert first.inverter_serial == "INV-TEST-1"
    assert first.string_name == "1.1"


def test_ignores_equipment_absent_from_the_filtered_dict() -> None:
    """Retired units linger in `children` but must not become entities."""
    equipment = equipment_dict()
    del equipment["OPT-TEST-2"]
    snapshot = build_site_snapshot(
        site_id=SITE_ID,
        equipment=equipment,
        site_information=SITE_INFORMATION,
        site_components=SITE_COMPONENTS,
    )
    assert [opt.serial for opt in snapshot.optimizers] == ["OPT-TEST-1"]


def test_missing_peak_power_is_none_not_zero() -> None:
    """Zero would render as a real 0 kWp reading; None renders as unknown."""
    snapshot = build_site_snapshot(
        site_id=SITE_ID,
        equipment=equipment_dict(),
        site_information={"siteTimeZone": "Asia/Jerusalem"},
        site_components=SITE_COMPONENTS,
    )
    assert snapshot.peak_power_kwp is None


def test_missing_timezone_raises() -> None:
    """Statistics cannot be placed on a timeline without the site timezone."""
    with pytest.raises(ValueError, match="siteTimeZone"):
        build_site_snapshot(
            site_id=SITE_ID,
            equipment=equipment_dict(),
            site_information={"peakPower": 11.7},
            site_components=SITE_COMPONENTS,
        )


def test_snapshot_is_immutable() -> None:
    """The snapshot is shared across platforms; nothing may mutate it."""
    snapshot = _snapshot()
    with pytest.raises((AttributeError, TypeError)):
        snapshot.site_id = "other"  # type: ignore[misc]


def test_tolerates_a_flat_layout_with_no_strings() -> None:
    """Some layouts hang optimizers straight off the inverter."""
    tree = {
        "type": "SITE",
        "uuid": SITE_ID,
        "children": [
            {
                "type": "INVERTER",
                "serial": "INV-TEST-1",
                "name": "Inverter 1",
                "children": [
                    {
                        "type": "OPTIMIZER",
                        "serial": "OPT-TEST-9",
                        "name": "1.9",
                        "children": [],
                    }
                ],
            }
        ],
    }
    equipment = {"INV-TEST-1": tree["children"][0], "OPT-TEST-9": tree["children"][0]["children"][0]}  # type: ignore[index]
    snapshot = build_site_snapshot(
        site_id=SITE_ID,
        equipment=equipment,
        site_information=SITE_INFORMATION,
        site_components=SITE_COMPONENTS,
    )
    assert snapshot.optimizers[0].string_name == ""
    assert snapshot.optimizers[0].inverter_serial == "INV-TEST-1"
