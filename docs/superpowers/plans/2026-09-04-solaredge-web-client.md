# SolarEdge Web Client Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a HACS custom integration that surfaces per-optimizer SolarEdge data as Home Assistant entities and imports per-module energy history as long-term statistics, replacing HA core's `solaredge` integration.

**Architecture:** A thin wrapper around the `solaredge-web` PyPI package. One `DataUpdateCoordinator` per config entry polls live per-optimizer data every 10 minutes and, when 12 hours have elapsed since the newest stored statistic, imports energy history in the same sequential pass. The integration contains no networking code of its own.

**Tech Stack:** Python 3.14, Home Assistant 2026.9, `solaredge-web`, `aiohttp`, `pytest` with `pytest-homeassistant-custom-component`, `ruff`, `mypy --strict`.

**Design spec:** `c:\Projects\homeassistant-config\docs\superpowers\specs\2026-09-04-solaredge-web-client-design.md`

## Global Constraints

- **Repo root:** `c:\Projects\solaredge-ha-web-client`. All paths below are relative to it.
- **Domain:** `solaredge_ha_web_client`. Must match the folder name under `custom_components/` exactly.
- **Read-only.** No write or control operation against SolarEdge, ever.
- **Only `coordinator.py` may import from `solaredge_web`.** Every other module takes data from `models.py` types.
- **No entity may declare `device_class: energy`.** Cloud energy exists only as statistics. Enforced by a test in Task 15.
- **Peak power sensor carries no device class and no state class.** `kWp` is a nameplate rating and fails unit validation under `device_class: power`.
- **Any entity duplicating a Modbus entity is named with a trailing `(Cloud)`.**
- **Statistic IDs are keyed on panel position, never serial.**
- **Statistics timestamps convert via the site's `siteTimeZone`**, never `dt_util.get_default_time_zone()`.
- **`ValueError` from the library is never caught.** It signals a bad argument from our code.
- **Never commit real credentials, site IDs or serial numbers.** Test fixtures use `SITE-TEST`, `INV-TEST-1`, `OPT-TEST-1`.
- **`GITHUB_OWNER`**: one value you must supply once in Task 1, Step 1 — your GitHub username. It appears in `manifest.json` (2 URLs), `hacs.json` and `README.md`. Everywhere else in this plan is literal.

---

## File Structure

| Path | Responsibility |
|------|----------------|
| `custom_components/solaredge_ha_web_client/const.py` | Domain, config keys, intervals, tunables |
| `custom_components/solaredge_ha_web_client/models.py` | Frozen dataclasses + `build_site_snapshot()` layout parsing |
| `custom_components/solaredge_ha_web_client/coordinator.py` | The only library consumer; live fetch, error mapping, statistics gating |
| `custom_components/solaredge_ha_web_client/statistics.py` | Serial-to-position mapping, hour bucketing, cumulative sums |
| `custom_components/solaredge_ha_web_client/config_flow.py` | User, reauth and options flows |
| `custom_components/solaredge_ha_web_client/entity.py` | Shared base: device info, availability |
| `custom_components/solaredge_ha_web_client/sensor.py` | Optimizer, inverter and site sensors |
| `custom_components/solaredge_ha_web_client/binary_sensor.py` | Alerts, inverter connectivity |
| `custom_components/solaredge_ha_web_client/diagnostics.py` | Redacted dump |
| `custom_components/solaredge_ha_web_client/__init__.py` | Entry setup/unload, device registration |

`models.py` and `statistics.py` are split from `coordinator.py` because both are pure logic over plain data and are where the subtle bugs live; keeping them free of coordinator and library imports is what makes them testable without mocking HTTP.

---

## Task 1: Repo scaffold, tooling and CI

**Files:**
- Create: `.gitignore`, `pyproject.toml`, `requirements_test.txt`, `hacs.json`, `README.md`
- Create: `custom_components/solaredge_ha_web_client/manifest.json`, `const.py`, `__init__.py`
- Create: `.github/workflows/ci.yml`
- Test: `tests/__init__.py`, `tests/conftest.py`, `tests/test_manifest.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `DOMAIN`, `LOGGER`, `CONF_SITE_ID`, `CONF_LIVE_INTERVAL`, `DEFAULT_LIVE_INTERVAL_MINUTES`, `MIN_LIVE_INTERVAL_MINUTES`, `MAX_LIVE_INTERVAL_MINUTES`, `STATISTICS_INTERVAL`, `REQUEST_SPACING_SECONDS`, `MAX_CONSECUTIVE_FAILURES`, `PLATFORMS` from `const.py`.

- [ ] **Step 1: Create the repo and resolve the two external values**

```powershell
New-Item -ItemType Directory -Path c:\Projects\solaredge-ha-web-client
Set-Location c:\Projects\solaredge-ha-web-client
git init
```

Get the `solaredge-web` version HA core currently pins, so we ship a version core
has tested against rather than whatever is newest:

```powershell
curl.exe https://raw.githubusercontent.com/home-assistant/core/dev/homeassistant/components/solaredge/manifest.json
```

Read the `solaredge-web==X.Y.Z` entry out of `requirements`. Use that exact
string wherever this plan writes `solaredge-web==CORE_PIN`. Note your GitHub
username for `GITHUB_OWNER`.

- [ ] **Step 2: Write the failing test**

`tests/test_manifest.py`:

```python
"""The manifest must stay consistent with the package it describes."""

import json
from pathlib import Path

from custom_components.solaredge_ha_web_client.const import DOMAIN

MANIFEST = (
    Path(__file__).parent.parent
    / "custom_components"
    / "solaredge_ha_web_client"
    / "manifest.json"
)


def test_manifest_domain_matches_package() -> None:
    """A domain that disagrees with the folder name fails to load at runtime."""
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert manifest["domain"] == DOMAIN
    assert MANIFEST.parent.name == DOMAIN


def test_manifest_declares_required_keys() -> None:
    """HACS and hassfest both reject a manifest missing any of these."""
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    for key in (
        "domain",
        "name",
        "codeowners",
        "config_flow",
        "documentation",
        "iot_class",
        "issue_tracker",
        "requirements",
        "version",
    ):
        assert key in manifest, f"manifest is missing {key}"
    assert manifest["config_flow"] is True
    assert manifest["iot_class"] == "cloud_polling"


def test_manifest_pins_solaredge_web_exactly() -> None:
    """An unpinned requirement lets an upstream break arrive unannounced."""
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    requirements = manifest["requirements"]
    assert len(requirements) == 1
    assert requirements[0].startswith("solaredge-web==")
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python -m pytest tests/test_manifest.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'custom_components'`

- [ ] **Step 4: Write the scaffold**

`custom_components/solaredge_ha_web_client/manifest.json` — replace `GITHUB_OWNER` and `CORE_PIN`:

```json
{
  "domain": "solaredge_ha_web_client",
  "name": "SolarEdge Web Client",
  "codeowners": ["@GITHUB_OWNER"],
  "config_flow": true,
  "documentation": "https://github.com/GITHUB_OWNER/solaredge-ha-web-client",
  "integration_type": "hub",
  "iot_class": "cloud_polling",
  "issue_tracker": "https://github.com/GITHUB_OWNER/solaredge-ha-web-client/issues",
  "requirements": ["solaredge-web==CORE_PIN"],
  "version": "0.1.0"
}
```

`custom_components/solaredge_ha_web_client/const.py`:

```python
"""Constants for the SolarEdge Web Client integration."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Final

from homeassistant.const import Platform

DOMAIN: Final = "solaredge_ha_web_client"
LOGGER: Final = logging.getLogger(__package__)

PLATFORMS: Final = [Platform.BINARY_SENSOR, Platform.SENSOR]

CONF_SITE_ID: Final = "site_id"
CONF_LIVE_INTERVAL: Final = "live_interval_minutes"

# Optimizers report roughly every 15 minutes, so polling faster than this
# gains nothing and only adds load on an undocumented API.
DEFAULT_LIVE_INTERVAL_MINUTES: Final = 10
MIN_LIVE_INTERVAL_MINUTES: Final = 5
MAX_LIVE_INTERVAL_MINUTES: Final = 60

# Statistics are history, not live state; twice a day is plenty.
STATISTICS_INTERVAL: Final = timedelta(hours=12)

# Deliberate spacing between requests in a cycle. The API publishes no rate
# limits and offers no support channel, so err towards being a polite client.
REQUEST_SPACING_SECONDS: Final = 0.3

# Hold last-known values through brief outages rather than strobing every
# panel entity unavailable on a single failed poll.
MAX_CONSECUTIVE_FAILURES: Final = 3

# Re-import a little before the last stored hour; overwriting is idempotent
# and lets SolarEdge's own corrections land.
STATISTICS_OVERLAP: Final = timedelta(hours=3)
```

`custom_components/solaredge_ha_web_client/__init__.py` — a stub for now, completed in Task 10:

```python
"""The SolarEdge Web Client integration."""
```

`pyproject.toml`:

```toml
[project]
name = "solaredge-ha-web-client"
version = "0.1.0"
description = "Home Assistant integration for per-optimizer SolarEdge data"
requires-python = ">=3.13"

[tool.ruff]
target-version = "py313"
line-length = 100

[tool.ruff.lint]
select = ["ALL"]
ignore = ["D203", "D213", "COM812", "ISC001"]

[tool.ruff.lint.per-file-ignores]
"tests/*" = ["S101", "PLR2004", "ANN401"]

[tool.mypy]
python_version = "3.13"
strict = true
warn_unreachable = true

[[tool.mypy.overrides]]
module = "solaredge_web.*"
ignore_missing_imports = false

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

`requirements_test.txt`:

```
pytest-homeassistant-custom-component
solaredge-web==CORE_PIN
ruff
mypy
```

`hacs.json`:

```json
{
  "name": "SolarEdge Web Client",
  "content_in_root": false,
  "render_readme": true,
  "homeassistant": "2026.9.0"
}
```

`.gitignore`:

```
__pycache__/
*.py[cod]
.venv/
.mypy_cache/
.pytest_cache/
.ruff_cache/
.coverage
htmlcov/
```

`tests/__init__.py` — empty file.

`tests/conftest.py`:

```python
"""Shared fixtures."""

from collections.abc import Generator

import pytest


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(
    enable_custom_integrations: None,
) -> Generator[None]:
    """Custom integrations are not loaded in tests unless explicitly enabled."""
    yield
```

`.github/workflows/ci.yml`:

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:

jobs:
  lint-and-test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.13"
      - run: pip install -r requirements_test.txt
      - run: ruff check .
      - run: ruff format --check .
      - run: mypy custom_components
      - run: pytest --cov=custom_components --cov-report=term-missing

  validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: home-assistant/actions/hassfest@master
      - uses: hacs/action@main
        with:
          category: integration
```

`README.md`:

```markdown
# SolarEdge Web Client

Per-optimizer SolarEdge data for Home Assistant, read from the SolarEdge
monitoring portal with your normal portal username and password. No API key,
and nothing to configure before the V1 API retires.

## What it provides

- Power and today's peak temperature for every optimizer
- Module and optimizer voltage, current and last-measurement time as diagnostics
- Site alert status and per-inverter connectivity
- Per-module, per-string and per-inverter energy history as long-term statistics

## What it does not provide

Site energy for the Energy Dashboard. Use a local Modbus integration for that —
it is faster, needs no cloud, and cannot be rate limited. This integration
deliberately publishes no energy entities so the two cannot be double-counted.

## Installation

Add this repository to HACS as a custom integration repository, install it, then
add the integration from **Settings → Devices & Services** and enter your
SolarEdge portal username, password and site ID.

## Status

Read-only. Built on the [`solaredge-web`](https://github.com/Solarlibs/solaredge-web)
client, which talks to SolarEdge's undocumented portal API. That API is not
guaranteed stable.
```

- [ ] **Step 5: Run tests to verify they pass**

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements_test.txt
.venv\Scripts\python.exe -m pytest tests/test_manifest.py -v
```

Expected: 3 passed.

- [ ] **Step 6: Commit**

```powershell
git add .
git commit -m "feat: scaffold repo, manifest and CI"
```

---

## Task 2: Data models and layout parsing

**Files:**
- Create: `custom_components/solaredge_ha_web_client/models.py`
- Test: `tests/test_models.py`, `tests/fixtures.py`

**Interfaces:**
- Consumes: `const.LOGGER`.
- Produces:
  - `OptimizerInfo(serial, display_name, inverter_serial, string_name)`
  - `InverterInfo(serial, display_name)`
  - `SiteSnapshot(site_id, peak_power_kwp, timezone, has_meter, has_storage, inverters, optimizers)`
  - `LiveData(...)` with per-section `*_ok` flags
  - `build_site_snapshot(site_id, equipment, site_information, site_components) -> SiteSnapshot`

The layout arrives from `async_get_equipment()` as a **flat** dict keyed by device
id, but each value is the original layout node and still carries its `children`,
so the `INVERTER → STRING → OPTIMIZER` hierarchy is recoverable by walking down
from the inverters. Parents are not stored on the nodes, which is why this walks
downwards and records the ancestor as it descends.

Only device ids present in the passed-in `equipment` dict are accepted. The
library already filtered retired units out of that dict, but `children` lists
still contain them — so membership in `equipment` is the filter, and re-deriving
it here would duplicate upstream logic that already documents its reasoning.

- [ ] **Step 1: Write the failing test**

`tests/fixtures.py`:

```python
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
    return {
        k: v
        for k, v in result.items()
        if v.get("properties", {}).get("status") != "INACTIVE"
    }


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
```

`tests/test_models.py`:

```python
"""Layout parsing."""

from typing import Any

import pytest

from custom_components.solaredge_ha_web_client.models import build_site_snapshot

from .fixtures import (
    EQUIPMENT_TREE,
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
```

Note the `EQUIPMENT_TREE` import is unused in the assertions but keeps the
fixture module honest about what shape it flattens; drop it from the import list
if ruff objects.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_models.py -v`
Expected: FAIL — `ImportError: cannot import name 'build_site_snapshot'`

- [ ] **Step 3: Write the implementation**

`custom_components/solaredge_ha_web_client/models.py`:

```python
"""Typed views over the SolarEdge layout and live payloads."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any

from .const import LOGGER

if TYPE_CHECKING:
    from solaredge_web import InverterData, LivePower, OptimizerData


@dataclass(frozen=True, slots=True)
class InverterInfo:
    """A single inverter, as the layout describes it."""

    serial: str
    display_name: str


@dataclass(frozen=True, slots=True)
class OptimizerInfo:
    """A single optimizer and the equipment it hangs off."""

    serial: str
    display_name: str
    inverter_serial: str
    string_name: str


@dataclass(frozen=True, slots=True)
class SiteSnapshot:
    """Static facts about the site, read once per config entry at setup.

    `timezone` is load-bearing rather than decorative: the library returns
    naive site-local timestamps, so statistics cannot be placed on a timeline
    without it.
    """

    site_id: str
    peak_power_kwp: float | None
    timezone: str
    has_meter: bool
    has_storage: bool
    inverters: tuple[InverterInfo, ...]
    optimizers: tuple[OptimizerInfo, ...]

    def optimizer(self, serial: str) -> OptimizerInfo | None:
        """Look up an optimizer by serial."""
        return next((o for o in self.optimizers if o.serial == serial), None)

    def display_names_by_serial(self) -> dict[str, str]:
        """Map every device id to its layout display name.

        Statistics are keyed on position, but the energy payload is keyed on
        serial, so the import needs this translation.
        """
        return {
            **{inv.serial: inv.display_name for inv in self.inverters},
            **{opt.serial: opt.display_name for opt in self.optimizers},
        }


@dataclass(frozen=True, slots=True)
class LiveData:
    """One live poll's results.

    A cycle hits several endpoints and one failing must not discard the others,
    so each section carries its own success flag. An entity whose section failed
    reports unknown while its neighbours keep publishing.
    """

    optimizers: dict[str, OptimizerData] = field(default_factory=dict)
    temperatures: dict[str, float] = field(default_factory=dict)
    inverters: dict[str, InverterData] = field(default_factory=dict)
    live_power: LivePower | None = None
    alert_count: int | None = None
    last_success: datetime | None = None
    optimizers_ok: bool = False
    temperatures_ok: bool = False
    inverters_ok: bool = False
    live_power_ok: bool = False
    alerts_ok: bool = False

    @property
    def any_ok(self) -> bool:
        """True when at least one endpoint answered."""
        return any(
            (
                self.optimizers_ok,
                self.temperatures_ok,
                self.inverters_ok,
                self.live_power_ok,
                self.alerts_ok,
            )
        )


def _as_float(value: Any) -> float | None:
    """Read a value as a float, or None if it is not one."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def build_site_snapshot(
    *,
    site_id: str,
    equipment: dict[str, dict[str, Any]],
    site_information: dict[str, Any],
    site_components: dict[str, Any],
) -> SiteSnapshot:
    """Assemble the static snapshot from three layout payloads.

    `equipment` is the flat dict `async_get_equipment()` returns, already
    filtered of retired units. Its values are the original layout nodes and
    still carry `children`, which is how the inverter/string/optimizer
    hierarchy is recovered here. Nodes reachable through `children` but absent
    from `equipment` are retired and skipped: membership in the filtered dict
    is the filter, rather than re-deriving upstream's INACTIVE rule.
    """
    timezone = site_information.get("siteTimeZone")
    if not timezone:
        msg = (
            "Site information is missing siteTimeZone; statistics timestamps "
            "cannot be resolved without it"
        )
        raise ValueError(msg)

    inverters: list[InverterInfo] = []
    optimizers: list[OptimizerInfo] = []

    def descend(node: dict[str, Any], inverter_serial: str, string_name: str) -> None:
        for child in node.get("children", []):
            child_id = _device_id(child)
            child_type = child.get("type")
            if child_type == "STRING":
                descend(child, inverter_serial, str(child.get("name", "")))
            elif child_type == "OPTIMIZER":
                if child_id and child_id in equipment:
                    optimizers.append(
                        OptimizerInfo(
                            serial=child_id,
                            display_name=_short_name(child.get("name", child_id)),
                            inverter_serial=inverter_serial,
                            string_name=string_name,
                        )
                    )
                elif child_id:
                    LOGGER.debug("Skipping retired optimizer %s", child_id)
            else:
                descend(child, inverter_serial, string_name)

    for device_id, node in equipment.items():
        if node.get("type") != "INVERTER":
            continue
        inverters.append(
            InverterInfo(
                serial=device_id,
                display_name=str(node.get("name", device_id)),
            )
        )
        descend(node, device_id, "")

    LOGGER.debug(
        "Built snapshot for site %s: %s inverters, %s optimizers",
        site_id,
        len(inverters),
        len(optimizers),
    )

    return SiteSnapshot(
        site_id=site_id,
        peak_power_kwp=_as_float(site_information.get("peakPower")),
        timezone=str(timezone),
        has_meter=bool(site_components.get("hasConsumptionAndGrid", False)),
        has_storage=bool(site_components.get("hasStorage", False)),
        inverters=tuple(inverters),
        optimizers=tuple(optimizers),
    )


def _device_id(node: dict[str, Any]) -> str | None:
    """Extract a layout node's device id, matching async_get_equipment."""
    return (
        node.get("serial")
        or node.get("properties", {}).get("identifier")
        or node.get("uuid")
    )


def _short_name(name: Any) -> str:
    """Reduce a layout name to its position token, e.g. 'Module 1.1.7' -> '1.1.7'.

    Names arrive both bare and prefixed depending on equipment kind; HA core
    takes the last space-delimited token for the same reason.
    """
    return str(name).rsplit(" ", 1)[-1]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_models.py -v`
Expected: 8 passed.

- [ ] **Step 5: Commit**

```powershell
git add custom_components/solaredge_ha_web_client/models.py tests/test_models.py tests/fixtures.py
git commit -m "feat: add typed models and layout parsing"
```

---

## Task 3: Error mapping

**Files:**
- Create: `custom_components/solaredge_ha_web_client/coordinator.py`
- Test: `tests/test_error_mapping.py`

**Interfaces:**
- Consumes: `const.LOGGER`.
- Produces: `map_client_error(err: Exception, endpoint: str) -> Exception` in `coordinator.py`, returning `ConfigEntryAuthFailed` or `UpdateFailed` for the caller to raise. Also `SkipFetch` — a sentinel exception meaning "this endpoint is unusable, carry on with the cycle".

The library makes this mapping possible without inspecting error strings: on a
failed login it raises `aiohttp.ClientResponseError` with **status 401**
specifically, its docstring noting this is "so that callers can tell bad
credentials apart from a transient failure".

- [ ] **Step 1: Write the failing test**

`tests/test_error_mapping.py`:

```python
"""Exception mapping. Type, never message text."""

import asyncio
from unittest.mock import Mock

import aiohttp
import pytest

from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.solaredge_ha_web_client.coordinator import (
    SkipFetch,
    map_client_error,
)


def _response_error(status: int) -> aiohttp.ClientResponseError:
    return aiohttp.ClientResponseError(
        request_info=Mock(),
        history=(),
        status=status,
        message=f"HTTP {status}",
    )


@pytest.mark.parametrize("status", [401, 403])
def test_credential_rejection_triggers_reauth(status: int) -> None:
    """Only a definitive rejection may prompt the user for a password."""
    result = map_client_error(_response_error(status), "optimizer data")
    assert isinstance(result, ConfigEntryAuthFailed)


def test_rate_limit_is_retryable() -> None:
    result = map_client_error(_response_error(429), "optimizer data")
    assert isinstance(result, UpdateFailed)


def test_bad_request_skips_only_this_endpoint() -> None:
    """A 400 means the range was too wide; the rest of the cycle is fine."""
    result = map_client_error(_response_error(400), "energy data")
    assert isinstance(result, SkipFetch)


@pytest.mark.parametrize("status", [500, 502, 503])
def test_server_errors_are_retryable(status: int) -> None:
    result = map_client_error(_response_error(status), "optimizer data")
    assert isinstance(result, UpdateFailed)


def test_connection_error_is_retryable() -> None:
    result = map_client_error(aiohttp.ClientError("boom"), "optimizer data")
    assert isinstance(result, UpdateFailed)


def test_timeout_is_retryable() -> None:
    result = map_client_error(asyncio.TimeoutError(), "optimizer data")
    assert isinstance(result, UpdateFailed)


def test_endpoint_name_reaches_the_message() -> None:
    """Without the endpoint, a log line cannot say what actually failed."""
    result = map_client_error(aiohttp.ClientError("boom"), "inverter data")
    assert "inverter data" in str(result)


def test_value_error_is_not_mapped() -> None:
    """A ValueError is our bug. Swallowing it would hide it forever."""
    with pytest.raises(ValueError, match="bad resolution"):
        map_client_error(ValueError("bad resolution"), "energy data")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_error_mapping.py -v`
Expected: FAIL — `ImportError: cannot import name 'SkipFetch'`

- [ ] **Step 3: Write the implementation**

`custom_components/solaredge_ha_web_client/coordinator.py` — the file starts here and grows in Tasks 4, 5 and 14:

```python
"""The single data update coordinator for a SolarEdge site.

The only module permitted to import from `solaredge_web`.
"""

from __future__ import annotations

import asyncio
from http import HTTPStatus

import aiohttp

from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed

from .const import LOGGER


class SkipFetch(Exception):  # noqa: N818
    """One endpoint is unusable but the cycle should continue.

    Raised for failures that will recur identically on retry — a range the API
    rejects, say — where failing the whole refresh would take healthy sensors
    down for a problem confined to one endpoint.
    """


def map_client_error(err: Exception, endpoint: str) -> Exception:
    """Translate a client exception into the coordinator's response.

    Returns the exception to raise. `ValueError` is deliberately re-raised
    rather than mapped: the library raises it for invalid arguments, which
    means our own call was wrong, and converting a bug into a retry would
    hide it.
    """
    if isinstance(err, ValueError):
        raise err

    if isinstance(err, aiohttp.ClientResponseError):
        if err.status in (HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN):
            LOGGER.debug("Credentials rejected while fetching %s", endpoint)
            return ConfigEntryAuthFailed(
                f"SolarEdge rejected the stored credentials while fetching {endpoint}"
            )
        if err.status == HTTPStatus.BAD_REQUEST:
            LOGGER.warning(
                "SolarEdge rejected the request for %s as invalid (HTTP 400); "
                "skipping it this cycle",
                endpoint,
            )
            return SkipFetch(f"SolarEdge rejected the request for {endpoint}")
        return UpdateFailed(f"SolarEdge returned HTTP {err.status} for {endpoint}")

    if isinstance(err, (TimeoutError, asyncio.TimeoutError)):
        return UpdateFailed(f"Timed out fetching {endpoint} from SolarEdge")

    if isinstance(err, aiohttp.ClientError):
        return UpdateFailed(f"Could not reach SolarEdge while fetching {endpoint}: {err}")

    return UpdateFailed(f"Unexpected error fetching {endpoint}: {err}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_error_mapping.py -v`
Expected: 11 passed.

- [ ] **Step 5: Commit**

```powershell
git add custom_components/solaredge_ha_web_client/coordinator.py tests/test_error_mapping.py
git commit -m "feat: map client exceptions to coordinator responses"
```

---

## Task 4: Coordinator live fetch with partial success

**Files:**
- Modify: `custom_components/solaredge_ha_web_client/coordinator.py`
- Test: `tests/test_coordinator_live.py`

**Interfaces:**
- Consumes: `SkipFetch`, `map_client_error`, `models.LiveData`, `models.SiteSnapshot`, `models.build_site_snapshot`, all constants.
- Produces:
  - `type SolarEdgeWebConfigEntry = ConfigEntry[SolarEdgeWebCoordinator]`
  - `SolarEdgeWebCoordinator(hass, entry)` with `.snapshot: SiteSnapshot`, `.data: LiveData`, `.async_load_snapshot()`, `.client`
  - `_async_update_data() -> LiveData`

- [ ] **Step 1: Write the failing test**

`tests/test_coordinator_live.py`:

```python
"""Live fetching, including the partial-failure path."""

from unittest.mock import AsyncMock, Mock, patch

import aiohttp
import pytest
from solaredge_web import LivePower, OptimizerData

from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed

from custom_components.solaredge_ha_web_client.const import CONF_SITE_ID, DOMAIN
from custom_components.solaredge_ha_web_client.coordinator import (
    SolarEdgeWebCoordinator,
)
from pytest_homeassistant_custom_component.common import MockConfigEntry

from .fixtures import SITE_COMPONENTS, SITE_ID, SITE_INFORMATION, equipment_dict


def _entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        unique_id=SITE_ID,
        title="Test Site",
        data={
            CONF_USERNAME: "user@example.com",
            CONF_PASSWORD: "hunter2",
            CONF_SITE_ID: SITE_ID,
        },
    )


def _client(**overrides: object) -> Mock:
    """A stub SolarEdgeWeb with every method this integration calls."""
    client = Mock()
    client.async_get_equipment = AsyncMock(return_value=equipment_dict())
    client.async_get_site_information = AsyncMock(return_value=SITE_INFORMATION)
    client.async_get_site_components = AsyncMock(return_value=SITE_COMPONENTS)
    client.async_get_optimizer_data = AsyncMock(
        return_value={"OPT-TEST-1": OptimizerData(serial="OPT-TEST-1", power=198.0)}
    )
    client.async_get_optimizer_temperatures = AsyncMock(
        return_value={"OPT-TEST-1": 41.5}
    )
    client.async_get_inverter_data = AsyncMock(return_value={})
    client.async_get_live_power = AsyncMock(
        return_value=LivePower(
            current_power=4210.0,
            max_power=11700.0,
            is_communicating=True,
            last_update_time=None,
        )
    )
    client.async_get_alerts = AsyncMock(
        return_value={"totalAlertsCount": 0, "topAlerts": []}
    )
    for name, value in overrides.items():
        setattr(client, name, value)
    return client


async def _coordinator(hass: HomeAssistant, client: Mock) -> SolarEdgeWebCoordinator:
    entry = _entry()
    entry.add_to_hass(hass)
    with patch(
        "custom_components.solaredge_ha_web_client.coordinator.SolarEdgeWeb",
        return_value=client,
    ):
        coordinator = SolarEdgeWebCoordinator(hass, entry)
    await coordinator.async_load_snapshot()
    return coordinator


async def test_successful_cycle_populates_every_section(hass: HomeAssistant) -> None:
    coordinator = await _coordinator(hass, _client())
    data = await coordinator._async_update_data()

    assert data.optimizers["OPT-TEST-1"].power == 198.0
    assert data.temperatures["OPT-TEST-1"] == 41.5
    assert data.live_power is not None
    assert data.alert_count == 0
    assert data.last_success is not None
    assert data.optimizers_ok
    assert data.temperatures_ok
    assert data.live_power_ok
    assert data.alerts_ok


async def test_one_failed_endpoint_does_not_discard_the_others(
    hass: HomeAssistant,
) -> None:
    """A temperature outage must not blank out working power sensors."""
    client = _client(
        async_get_optimizer_temperatures=AsyncMock(
            side_effect=aiohttp.ClientError("boom")
        )
    )
    coordinator = await _coordinator(hass, client)
    data = await coordinator._async_update_data()

    assert data.optimizers_ok is True
    assert data.optimizers["OPT-TEST-1"].power == 198.0
    assert data.temperatures_ok is False
    assert data.temperatures == {}


async def test_total_failure_raises_update_failed(hass: HomeAssistant) -> None:
    """If nothing answered there is no data, and the coordinator must say so."""
    error = AsyncMock(side_effect=aiohttp.ClientError("boom"))
    client = _client(
        async_get_optimizer_data=error,
        async_get_optimizer_temperatures=error,
        async_get_inverter_data=error,
        async_get_live_power=error,
        async_get_alerts=error,
    )
    coordinator = await _coordinator(hass, client)
    with pytest.raises(Exception, match="SolarEdge"):
        await coordinator._async_update_data()


async def test_credential_rejection_propagates_immediately(
    hass: HomeAssistant,
) -> None:
    """Reauth must not wait for the other endpoints to fail too."""
    client = _client(
        async_get_optimizer_data=AsyncMock(
            side_effect=aiohttp.ClientResponseError(
                request_info=Mock(), history=(), status=401, message="denied"
            )
        )
    )
    coordinator = await _coordinator(hass, client)
    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()


async def test_snapshot_is_loaded_once(hass: HomeAssistant) -> None:
    """Static layout must not be refetched on every poll."""
    client = _client()
    coordinator = await _coordinator(hass, client)
    await coordinator._async_update_data()
    await coordinator._async_update_data()
    assert client.async_get_site_information.await_count == 1


async def test_requests_are_spaced(hass: HomeAssistant) -> None:
    """Politeness on an API with no published limits and no support channel."""
    with patch(
        "custom_components.solaredge_ha_web_client.coordinator.asyncio.sleep"
    ) as sleep:
        coordinator = await _coordinator(hass, _client())
        await coordinator._async_update_data()
    assert sleep.await_count >= 4
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_coordinator_live.py -v`
Expected: FAIL — `ImportError: cannot import name 'SolarEdgeWebCoordinator'`

- [ ] **Step 3: Write the implementation**

Append to `coordinator.py`, and extend the import block at the top to match:

```python
# --- add to the existing imports at the top of coordinator.py ---
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from solaredge_web import InverterData, LivePower, OptimizerData, SolarEdgeWeb

from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import (
    CONF_LIVE_INTERVAL,
    CONF_SITE_ID,
    DEFAULT_LIVE_INTERVAL_MINUTES,
    DOMAIN,
    LOGGER,
    REQUEST_SPACING_SECONDS,
)
from .models import LiveData, SiteSnapshot, build_site_snapshot

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

    type SolarEdgeWebConfigEntry = ConfigEntry[SolarEdgeWebCoordinator]
```

```python
class SolarEdgeWebCoordinator(DataUpdateCoordinator[LiveData]):
    """Polls live data and, twice a day, imports energy history.

    One coordinator and one client per config entry, so requests within an
    entry are strictly sequential. That makes overlapping requests on a shared
    login session structurally impossible and removes any need for a lock.
    """

    config_entry: SolarEdgeWebConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: SolarEdgeWebConfigEntry,
    ) -> None:
        """Initialise the coordinator and its single client."""
        interval = config_entry.options.get(
            CONF_LIVE_INTERVAL, DEFAULT_LIVE_INTERVAL_MINUTES
        )
        super().__init__(
            hass,
            LOGGER,
            config_entry=config_entry,
            name=f"{DOMAIN} {config_entry.title}",
            update_interval=timedelta(minutes=interval),
        )
        self.site_id: str = config_entry.data[CONF_SITE_ID]
        self.client = SolarEdgeWeb(
            username=config_entry.data[CONF_USERNAME],
            password=config_entry.data[CONF_PASSWORD],
            site_id=self.site_id,
            session=async_get_clientsession(hass),
        )
        self._snapshot: SiteSnapshot | None = None

    @property
    def snapshot(self) -> SiteSnapshot:
        """The static site layout, loaded once at setup."""
        if self._snapshot is None:
            msg = "Snapshot accessed before async_load_snapshot()"
            raise RuntimeError(msg)
        return self._snapshot

    async def async_load_snapshot(self) -> None:
        """Fetch the static layout once, at entry setup.

        Equipment, site information and components change only when hardware
        does, so refetching them on every poll would triple the request count
        for data that does not move.
        """
        try:
            equipment = await self.client.async_get_equipment()
            await asyncio.sleep(REQUEST_SPACING_SECONDS)
            site_information = await self.client.async_get_site_information()
            await asyncio.sleep(REQUEST_SPACING_SECONDS)
            site_components = await self.client.async_get_site_components()
        except Exception as err:  # noqa: BLE001
            raise map_client_error(err, "site layout") from err

        self._snapshot = build_site_snapshot(
            site_id=self.site_id,
            equipment=equipment,
            site_information=site_information,
            site_components=site_components,
        )

    async def _async_update_data(self) -> LiveData:
        """Run one live cycle, tolerating partial failure."""
        live = await self._async_fetch_live()
        if not live.any_ok:
            raise UpdateFailed(
                f"No SolarEdge endpoint answered for site {self.site_id}"
            )
        return live

    async def _async_fetch_live(self) -> LiveData:
        """Fetch each live endpoint in turn, recording what succeeded."""
        sections: dict[str, Any] = {}
        flags: dict[str, bool] = {}

        for key, endpoint, call in (
            ("optimizers", "optimizer data", self.client.async_get_optimizer_data),
            (
                "temperatures",
                "optimizer temperatures",
                self.client.async_get_optimizer_temperatures,
            ),
            ("inverters", "inverter data", self.client.async_get_inverter_data),
            ("live_power", "live power", self.client.async_get_live_power),
            ("alerts", "alerts", self.client.async_get_alerts),
        ):
            try:
                sections[key] = await call()
                flags[key] = True
            except ConfigEntryAuthFailed:
                raise
            except Exception as err:  # noqa: BLE001
                mapped = map_client_error(err, endpoint)
                if isinstance(mapped, ConfigEntryAuthFailed):
                    raise mapped from err
                LOGGER.debug("Section %s failed: %s", key, mapped)
                flags[key] = False
            await asyncio.sleep(REQUEST_SPACING_SECONDS)

        alerts = sections.get("alerts") or {}
        return LiveData(
            optimizers=sections.get("optimizers") or {},
            temperatures=sections.get("temperatures") or {},
            inverters=sections.get("inverters") or {},
            live_power=sections.get("live_power"),
            alert_count=alerts.get("totalAlertsCount") if flags.get("alerts") else None,
            last_success=dt_util.utcnow(),
            optimizers_ok=flags.get("optimizers", False),
            temperatures_ok=flags.get("temperatures", False),
            inverters_ok=flags.get("inverters", False),
            live_power_ok=flags.get("live_power", False),
            alerts_ok=flags.get("alerts", False),
        )
```

Note `map_client_error` re-raises `ValueError`, so the broad `except Exception`
here does not swallow it — the `raise err` inside the mapper propagates.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_coordinator_live.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```powershell
git add custom_components/solaredge_ha_web_client/coordinator.py tests/test_coordinator_live.py
git commit -m "feat: add live coordinator with partial-success handling"
```

---

## Task 5: Availability after three consecutive failures

**Files:**
- Modify: `custom_components/solaredge_ha_web_client/coordinator.py`
- Test: `tests/test_coordinator_availability.py`

**Interfaces:**
- Produces: `SolarEdgeWebCoordinator.consecutive_failures: int` and `.data_is_stale: bool`.

Entities hold last-known values through brief outages and only go unavailable
after three fully failed cycles. Flipping immediately would strobe every panel
on the dashboard for a single hiccup, and is false precision given the data is
already about 15 minutes old. Staleness is instead made visible by the "Last
successful update" sensor from Task 11.

- [ ] **Step 1: Write the failing test**

`tests/test_coordinator_availability.py`:

```python
"""Availability hysteresis."""

from unittest.mock import AsyncMock, Mock, patch

import aiohttp
from homeassistant.core import HomeAssistant

from custom_components.solaredge_ha_web_client.const import MAX_CONSECUTIVE_FAILURES

from .test_coordinator_live import _client, _coordinator


async def test_starts_healthy(hass: HomeAssistant) -> None:
    coordinator = await _coordinator(hass, _client())
    assert coordinator.consecutive_failures == 0
    assert coordinator.data_is_stale is False


async def test_two_failures_keep_entities_available(hass: HomeAssistant) -> None:
    """One SolarEdge hiccup must not blank twenty panel sensors."""
    error = AsyncMock(side_effect=aiohttp.ClientError("boom"))
    client = _client(
        async_get_optimizer_data=error,
        async_get_optimizer_temperatures=error,
        async_get_inverter_data=error,
        async_get_live_power=error,
        async_get_alerts=error,
    )
    coordinator = await _coordinator(hass, client)

    for expected in (1, 2):
        await coordinator.async_refresh()
        assert coordinator.consecutive_failures == expected
        assert coordinator.data_is_stale is False


async def test_third_failure_marks_data_stale(hass: HomeAssistant) -> None:
    error = AsyncMock(side_effect=aiohttp.ClientError("boom"))
    client = _client(
        async_get_optimizer_data=error,
        async_get_optimizer_temperatures=error,
        async_get_inverter_data=error,
        async_get_live_power=error,
        async_get_alerts=error,
    )
    coordinator = await _coordinator(hass, client)

    for _ in range(MAX_CONSECUTIVE_FAILURES):
        await coordinator.async_refresh()

    assert coordinator.consecutive_failures == MAX_CONSECUTIVE_FAILURES
    assert coordinator.data_is_stale is True


async def test_success_resets_the_counter(hass: HomeAssistant) -> None:
    client = _client()
    coordinator = await _coordinator(hass, client)
    coordinator._consecutive_failures = 2

    await coordinator.async_refresh()

    assert coordinator.consecutive_failures == 0
    assert coordinator.data_is_stale is False


async def test_partial_success_counts_as_success(hass: HomeAssistant) -> None:
    """Some data is not an outage."""
    client = _client(
        async_get_optimizer_temperatures=AsyncMock(
            side_effect=aiohttp.ClientError("boom")
        )
    )
    coordinator = await _coordinator(hass, client)
    coordinator._consecutive_failures = 2

    await coordinator.async_refresh()

    assert coordinator.consecutive_failures == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_coordinator_availability.py -v`
Expected: FAIL — `AttributeError: 'SolarEdgeWebCoordinator' object has no attribute 'consecutive_failures'`

- [ ] **Step 3: Write the implementation**

In `coordinator.py`, add to `__init__`:

```python
        self._consecutive_failures = 0
```

Add these properties to the class:

```python
    @property
    def consecutive_failures(self) -> int:
        """How many cycles in a row have failed outright."""
        return self._consecutive_failures

    @property
    def data_is_stale(self) -> bool:
        """True once failures have run long enough to stop trusting the data."""
        return self._consecutive_failures >= MAX_CONSECUTIVE_FAILURES
```

Replace `_async_update_data` with a version that maintains the counter:

```python
    async def _async_update_data(self) -> LiveData:
        """Run one live cycle, tolerating partial failure."""
        try:
            live = await self._async_fetch_live()
        except ConfigEntryAuthFailed:
            # Reauth is not an outage; the user must act, and the counter
            # would otherwise be meaningless while the flow is pending.
            raise
        except Exception:
            self._consecutive_failures += 1
            raise

        if not live.any_ok:
            self._consecutive_failures += 1
            raise UpdateFailed(
                f"No SolarEdge endpoint answered for site {self.site_id} "
                f"({self._consecutive_failures} consecutive failures)"
            )

        self._consecutive_failures = 0
        return live
```

Add `MAX_CONSECUTIVE_FAILURES` to the `.const` import list.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_coordinator_availability.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```powershell
git add custom_components/solaredge_ha_web_client/coordinator.py tests/test_coordinator_availability.py
git commit -m "feat: hold entities available through brief outages"
```

---

## Task 6: Config flow, user step

**Files:**
- Create: `custom_components/solaredge_ha_web_client/config_flow.py`, `strings.json`, `translations/en.json`
- Test: `tests/test_config_flow.py`

**Interfaces:**
- Consumes: `const` values, `coordinator.map_client_error`.
- Produces: `SolarEdgeWebConfigFlow` with `async_step_user`. Entry data holds `CONF_USERNAME`, `CONF_PASSWORD`, `CONF_SITE_ID`; `unique_id` is the site ID.

Validation calls `async_get_site_information()`, which proves the credentials and
confirms the site is visible to that account in one request.

- [ ] **Step 1: Write the failing test**

`tests/test_config_flow.py`:

```python
"""Config flow: user step."""

from unittest.mock import AsyncMock, Mock, patch

import aiohttp
from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.solaredge_ha_web_client.const import CONF_SITE_ID, DOMAIN
from pytest_homeassistant_custom_component.common import MockConfigEntry

from .fixtures import SITE_ID, SITE_INFORMATION

USER_INPUT = {
    CONF_USERNAME: "user@example.com",
    CONF_PASSWORD: "hunter2",
    CONF_SITE_ID: SITE_ID,
}


def _client(side_effect: object = None) -> Mock:
    client = Mock()
    client.async_get_site_information = AsyncMock(
        return_value=SITE_INFORMATION, side_effect=side_effect
    )
    return client


async def test_user_step_creates_entry(hass: HomeAssistant) -> None:
    with (
        patch(
            "custom_components.solaredge_ha_web_client.config_flow.SolarEdgeWeb",
            return_value=_client(),
        ),
        patch(
            "custom_components.solaredge_ha_web_client.async_setup_entry",
            return_value=True,
        ),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}, data=USER_INPUT
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == USER_INPUT
    assert result["result"].unique_id == SITE_ID


async def test_shows_form_with_no_input(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"


async def test_invalid_auth(hass: HomeAssistant) -> None:
    error = aiohttp.ClientResponseError(
        request_info=Mock(), history=(), status=401, message="denied"
    )
    with patch(
        "custom_components.solaredge_ha_web_client.config_flow.SolarEdgeWeb",
        return_value=_client(side_effect=error),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}, data=USER_INPUT
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def test_cannot_connect(hass: HomeAssistant) -> None:
    with patch(
        "custom_components.solaredge_ha_web_client.config_flow.SolarEdgeWeb",
        return_value=_client(side_effect=aiohttp.ClientError("boom")),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}, data=USER_INPUT
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_duplicate_site_aborts(hass: HomeAssistant) -> None:
    """Two entries for one site would double every request and statistic."""
    MockConfigEntry(domain=DOMAIN, unique_id=SITE_ID, data=USER_INPUT).add_to_hass(hass)

    with patch(
        "custom_components.solaredge_ha_web_client.config_flow.SolarEdgeWeb",
        return_value=_client(),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}, data=USER_INPUT
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_recovers_after_a_failed_attempt(hass: HomeAssistant) -> None:
    """A typo must be correctable without restarting the flow."""
    with patch(
        "custom_components.solaredge_ha_web_client.config_flow.SolarEdgeWeb",
        return_value=_client(side_effect=aiohttp.ClientError("boom")),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}, data=USER_INPUT
        )

    with (
        patch(
            "custom_components.solaredge_ha_web_client.config_flow.SolarEdgeWeb",
            return_value=_client(),
        ),
        patch(
            "custom_components.solaredge_ha_web_client.async_setup_entry",
            return_value=True,
        ),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], USER_INPUT
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_config_flow.py -v`
Expected: FAIL — the flow handler is not registered.

- [ ] **Step 3: Write the implementation**

`custom_components/solaredge_ha_web_client/config_flow.py`:

```python
"""Config flow for SolarEdge Web Client."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from solaredge_web import SolarEdgeWeb

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import CONF_SITE_ID, DOMAIN, LOGGER
from .coordinator import map_client_error

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Required(CONF_SITE_ID): str,
    }
)


class SolarEdgeWebConfigFlow(ConfigFlow, domain=DOMAIN):
    """Collect portal credentials and a site ID."""

    VERSION = 1

    async def _async_validate(self, user_input: dict[str, Any]) -> str | None:
        """Return an error key, or None when the credentials work.

        `async_get_site_information` both authenticates and proves the site is
        visible to this account, so one request validates the whole form.
        """
        client = SolarEdgeWeb(
            username=user_input[CONF_USERNAME],
            password=user_input[CONF_PASSWORD],
            site_id=user_input[CONF_SITE_ID],
            session=async_get_clientsession(self.hass),
        )
        try:
            await client.async_get_site_information()
        except Exception as err:  # noqa: BLE001
            mapped = map_client_error(err, "site information")
            if isinstance(mapped, ConfigEntryAuthFailed):
                return "invalid_auth"
            LOGGER.debug("Validation failed: %s", mapped)
            return "cannot_connect"
        return None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_SITE_ID])
            self._abort_if_unique_id_configured()

            error = await self._async_validate(user_input)
            if error is None:
                return self.async_create_entry(
                    title=f"SolarEdge {user_input[CONF_SITE_ID]}",
                    data=user_input,
                )
            errors["base"] = error

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_SCHEMA, errors=errors
        )
```

`custom_components/solaredge_ha_web_client/strings.json`:

```json
{
  "config": {
    "step": {
      "user": {
        "title": "SolarEdge portal credentials",
        "description": "Sign in with the same username and password you use at monitoring.solaredge.com. Your site ID appears in the portal URL.",
        "data": {
          "username": "Username",
          "password": "Password",
          "site_id": "Site ID"
        }
      },
      "reauth_confirm": {
        "title": "Re-enter your SolarEdge password",
        "description": "SolarEdge rejected the stored password for {site_id}.",
        "data": {
          "password": "Password"
        }
      }
    },
    "error": {
      "invalid_auth": "SolarEdge rejected those credentials.",
      "cannot_connect": "Could not reach SolarEdge. Check your connection and try again."
    },
    "abort": {
      "already_configured": "That site is already configured.",
      "reauth_successful": "Re-authentication was successful."
    }
  },
  "options": {
    "step": {
      "init": {
        "title": "Polling options",
        "description": "Optimizers report roughly every 15 minutes, so polling faster than 5 minutes adds load without adding data.",
        "data": {
          "live_interval_minutes": "Minutes between polls"
        }
      }
    }
  }
}
```

Copy that file verbatim to `custom_components/solaredge_ha_web_client/translations/en.json`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_config_flow.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```powershell
git add custom_components/solaredge_ha_web_client/config_flow.py custom_components/solaredge_ha_web_client/strings.json custom_components/solaredge_ha_web_client/translations tests/test_config_flow.py
git commit -m "feat: add config flow user step"
```

---

## Task 7: Reauth and options flows

**Files:**
- Modify: `custom_components/solaredge_ha_web_client/config_flow.py`
- Test: `tests/test_config_flow_reauth.py`, `tests/test_options_flow.py`

**Interfaces:**
- Produces: `async_step_reauth`, `async_step_reauth_confirm`, `async_get_options_flow`, `SolarEdgeWebOptionsFlow`.

Reauth asks for the password only, preserving username and site ID — the user is
being told their password stopped working, so re-typing an email address is
friction for no purpose.

- [ ] **Step 1: Write the failing tests**

`tests/test_config_flow_reauth.py`:

```python
"""Reauth flow."""

from unittest.mock import AsyncMock, Mock, patch

import aiohttp
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.solaredge_ha_web_client.const import CONF_SITE_ID, DOMAIN
from pytest_homeassistant_custom_component.common import MockConfigEntry

from .fixtures import SITE_ID, SITE_INFORMATION

ENTRY_DATA = {
    CONF_USERNAME: "user@example.com",
    CONF_PASSWORD: "old-password",
    CONF_SITE_ID: SITE_ID,
}


def _client(side_effect: object = None) -> Mock:
    client = Mock()
    client.async_get_site_information = AsyncMock(
        return_value=SITE_INFORMATION, side_effect=side_effect
    )
    return client


async def test_reauth_updates_only_the_password(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(domain=DOMAIN, unique_id=SITE_ID, data=ENTRY_DATA)
    entry.add_to_hass(hass)

    result = await entry.start_reauth_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"
    assert set(result["data_schema"].schema) == {CONF_PASSWORD}

    with (
        patch(
            "custom_components.solaredge_ha_web_client.config_flow.SolarEdgeWeb",
            return_value=_client(),
        ),
        patch(
            "custom_components.solaredge_ha_web_client.async_setup_entry",
            return_value=True,
        ),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_PASSWORD: "new-password"}
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_PASSWORD] == "new-password"
    assert entry.data[CONF_USERNAME] == "user@example.com"
    assert entry.data[CONF_SITE_ID] == SITE_ID


async def test_reauth_rejects_a_still_wrong_password(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(domain=DOMAIN, unique_id=SITE_ID, data=ENTRY_DATA)
    entry.add_to_hass(hass)
    result = await entry.start_reauth_flow(hass)

    error = aiohttp.ClientResponseError(
        request_info=Mock(), history=(), status=401, message="denied"
    )
    with patch(
        "custom_components.solaredge_ha_web_client.config_flow.SolarEdgeWeb",
        return_value=_client(side_effect=error),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_PASSWORD: "still-wrong"}
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}
    assert entry.data[CONF_PASSWORD] == "old-password"
```

`tests/test_options_flow.py`:

```python
"""Options flow."""

import pytest
import voluptuous as vol
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.solaredge_ha_web_client.const import (
    CONF_LIVE_INTERVAL,
    DEFAULT_LIVE_INTERVAL_MINUTES,
    DOMAIN,
    MAX_LIVE_INTERVAL_MINUTES,
    MIN_LIVE_INTERVAL_MINUTES,
)
from pytest_homeassistant_custom_component.common import MockConfigEntry

from .test_config_flow_reauth import ENTRY_DATA
from .fixtures import SITE_ID


async def test_options_flow_stores_the_interval(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(domain=DOMAIN, unique_id=SITE_ID, data=ENTRY_DATA)
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_LIVE_INTERVAL: 20}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_LIVE_INTERVAL] == 20


@pytest.mark.parametrize(
    "value",
    [MIN_LIVE_INTERVAL_MINUTES - 1, MAX_LIVE_INTERVAL_MINUTES + 1],
)
async def test_options_flow_rejects_out_of_range(
    hass: HomeAssistant, value: int
) -> None:
    """Below the floor the API has nothing new to give."""
    entry = MockConfigEntry(domain=DOMAIN, unique_id=SITE_ID, data=ENTRY_DATA)
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    with pytest.raises(vol.Invalid):
        await hass.config_entries.options.async_configure(
            result["flow_id"], {CONF_LIVE_INTERVAL: value}
        )


async def test_default_is_offered(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(domain=DOMAIN, unique_id=SITE_ID, data=ENTRY_DATA)
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {})

    assert entry.options[CONF_LIVE_INTERVAL] == DEFAULT_LIVE_INTERVAL_MINUTES
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_config_flow_reauth.py tests/test_options_flow.py -v`
Expected: FAIL — `Handler does not support step reauth_confirm` and `does not support options flow`.

- [ ] **Step 3: Write the implementation**

Add to `config_flow.py`:

```python
# --- additional imports ---
from collections.abc import Mapping

from homeassistant.config_entries import ConfigEntry, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv

from .const import (
    CONF_LIVE_INTERVAL,
    DEFAULT_LIVE_INTERVAL_MINUTES,
    MAX_LIVE_INTERVAL_MINUTES,
    MIN_LIVE_INTERVAL_MINUTES,
)

STEP_REAUTH_SCHEMA = vol.Schema({vol.Required(CONF_PASSWORD): str})
```

Add these methods to `SolarEdgeWebConfigFlow`:

```python
    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Start reauth. Only the password is in question."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Collect a replacement password, keeping username and site ID."""
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            candidate = {**entry.data, CONF_PASSWORD: user_input[CONF_PASSWORD]}
            error = await self._async_validate(candidate)
            if error is None:
                return self.async_update_reload_and_abort(entry, data=candidate)
            errors["base"] = error

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=STEP_REAUTH_SCHEMA,
            errors=errors,
            description_placeholders={"site_id": entry.data[CONF_SITE_ID]},
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> SolarEdgeWebOptionsFlow:
        """Return the options flow."""
        return SolarEdgeWebOptionsFlow()


class SolarEdgeWebOptionsFlow(OptionsFlow):
    """Adjust how often live data is polled."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the options step."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        current = self.config_entry.options.get(
            CONF_LIVE_INTERVAL, DEFAULT_LIVE_INTERVAL_MINUTES
        )
        schema = vol.Schema(
            {
                vol.Optional(CONF_LIVE_INTERVAL, default=current): vol.All(
                    cv.positive_int,
                    vol.Range(
                        min=MIN_LIVE_INTERVAL_MINUTES,
                        max=MAX_LIVE_INTERVAL_MINUTES,
                    ),
                )
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_config_flow_reauth.py tests/test_options_flow.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```powershell
git add custom_components/solaredge_ha_web_client/config_flow.py tests/test_config_flow_reauth.py tests/test_options_flow.py
git commit -m "feat: add reauth and options flows"
```

---

## Task 8: Statistics — identifiers, timezone and bucketing

**Files:**
- Create: `custom_components/solaredge_ha_web_client/statistics.py`
- Test: `tests/test_statistics_mapping.py`

**Interfaces:**
- Consumes: `models.SiteSnapshot`, `const.DOMAIN`, `const.LOGGER`.
- Produces:
  - `statistic_id_for(site_id: str, kind: str, display_name: str) -> str`
  - `resolve_site_timezone(hass, snapshot) -> tzinfo`
  - `bucket_energy(energy_data, snapshot, tzinfo) -> dict[str, list[tuple[datetime, float]]]` keyed by statistic ID, values ordered `(aware hour start, Wh)`

`EnergyData.values` is keyed by **serial** while statistic IDs are keyed on
**position**, so this module owns that translation. A serial with no match in the
snapshot is logged and skipped, not silently dropped — that is what a mid-run
hardware change looks like and it should be visible.

- [ ] **Step 1: Write the failing test**

`tests/test_statistics_mapping.py`:

```python
"""Statistic identifiers, timezone handling and bucketing."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from homeassistant.core import HomeAssistant
from solaredge_web import EnergyData

from custom_components.solaredge_ha_web_client.models import build_site_snapshot
from custom_components.solaredge_ha_web_client.statistics import (
    bucket_energy,
    resolve_site_timezone,
    statistic_id_for,
)

from .fixtures import SITE_COMPONENTS, SITE_ID, SITE_INFORMATION, equipment_dict


def _snapshot() -> object:
    return build_site_snapshot(
        site_id=SITE_ID,
        equipment=equipment_dict(),
        site_information=SITE_INFORMATION,
        site_components=SITE_COMPONENTS,
    )


def test_statistic_id_uses_position_not_serial() -> None:
    """A replaced optimizer keeps its position, so history stays continuous."""
    assert (
        statistic_id_for(SITE_ID, "opt", "1.1.7")
        == "solaredge_ha_web_client:site_test_opt_1_1_7"
    )


def test_statistic_id_slugifies_the_site() -> None:
    assert statistic_id_for("My Site!", "inv", "Inverter 1").startswith(
        "solaredge_ha_web_client:my_site_inv_"
    )


def test_statistic_id_is_stable() -> None:
    """Statistic IDs are a persistent contract; drift orphans history."""
    assert (
        statistic_id_for(SITE_ID, "opt", "1.1.1")
        == statistic_id_for(SITE_ID, "opt", "1.1.1")
    )


async def test_resolves_the_site_timezone_not_the_ha_one(
    hass: HomeAssistant,
) -> None:
    """Core attaches HA's timezone here, which is wrong for a site abroad."""
    hass.config.time_zone = "UTC"
    snapshot = build_site_snapshot(
        site_id=SITE_ID,
        equipment=equipment_dict(),
        site_information={**SITE_INFORMATION, "siteTimeZone": "America/Los_Angeles"},
        site_components=SITE_COMPONENTS,
    )
    tzinfo = await resolve_site_timezone(hass, snapshot)
    assert tzinfo == ZoneInfo("America/Los_Angeles")


async def test_unknown_timezone_raises(hass: HomeAssistant) -> None:
    snapshot = build_site_snapshot(
        site_id=SITE_ID,
        equipment=equipment_dict(),
        site_information={**SITE_INFORMATION, "siteTimeZone": "Mars/Olympus"},
        site_components=SITE_COMPONENTS,
    )
    with pytest.raises(ValueError, match="Mars/Olympus"):
        await resolve_site_timezone(hass, snapshot)


def test_buckets_are_site_local_converted_to_utc() -> None:
    """A naive 08:00 site-local reading is 05:00Z in Jerusalem summer time."""
    tzinfo = ZoneInfo("Asia/Jerusalem")
    energy = [
        EnergyData(
            start_time=datetime(2026, 9, 4, 8, 0),
            values={"OPT-TEST-1": 420.0},
        )
    ]
    buckets = bucket_energy(energy, _snapshot(), tzinfo)
    key = statistic_id_for(SITE_ID, "opt", "1.1.1")

    start, value = buckets[key][0]
    assert value == 420.0
    assert start.utcoffset().total_seconds() == 3 * 3600
    assert start.hour == 8


def test_absent_serial_counts_as_zero_for_that_hour() -> None:
    """No report means no energy, which for a running sum is zero, not a gap."""
    tzinfo = ZoneInfo("Asia/Jerusalem")
    energy = [
        EnergyData(start_time=datetime(2026, 9, 4, 8, 0), values={"OPT-TEST-1": 420.0})
    ]
    buckets = bucket_energy(energy, _snapshot(), tzinfo)
    key = statistic_id_for(SITE_ID, "opt", "1.1.2")

    assert buckets[key][0][1] == 0.0


def test_unknown_serial_is_skipped_not_imported() -> None:
    """A serial absent from the layout is a hardware change, not a data point."""
    tzinfo = ZoneInfo("Asia/Jerusalem")
    energy = [
        EnergyData(
            start_time=datetime(2026, 9, 4, 8, 0),
            values={"OPT-TEST-1": 420.0, "OPT-UNKNOWN": 999.0},
        )
    ]
    buckets = bucket_energy(energy, _snapshot(), tzinfo)

    assert not any("unknown" in key for key in buckets)


def test_buckets_are_time_ordered() -> None:
    """Cumulative sums are only correct if applied in order."""
    tzinfo = ZoneInfo("Asia/Jerusalem")
    energy = [
        EnergyData(start_time=datetime(2026, 9, 4, 9, 0), values={"OPT-TEST-1": 2.0}),
        EnergyData(start_time=datetime(2026, 9, 4, 8, 0), values={"OPT-TEST-1": 1.0}),
    ]
    buckets = bucket_energy(energy, _snapshot(), tzinfo)
    key = statistic_id_for(SITE_ID, "opt", "1.1.1")

    starts = [start for start, _ in buckets[key]]
    assert starts == sorted(starts)


def test_inverters_get_their_own_series() -> None:
    tzinfo = ZoneInfo("Asia/Jerusalem")
    energy = [
        EnergyData(start_time=datetime(2026, 9, 4, 8, 0), values={"INV-TEST-1": 800.0})
    ]
    buckets = bucket_energy(energy, _snapshot(), tzinfo)
    key = statistic_id_for(SITE_ID, "inv", "1")

    assert buckets[key][0][1] == 800.0
```

Note the inverter display name `"Inverter 1"` reduces to `"1"` through
`_short_name`, which is why the expected key is `inv_1`.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_statistics_mapping.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named '...statistics'`

- [ ] **Step 3: Write the implementation**

`custom_components/solaredge_ha_web_client/statistics.py`:

```python
"""Long-term statistics import for per-module energy history."""

from __future__ import annotations

from datetime import datetime, tzinfo
from typing import TYPE_CHECKING

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util, slugify

from .const import DOMAIN, LOGGER

if TYPE_CHECKING:
    from solaredge_web import EnergyData

    from .models import SiteSnapshot


def statistic_id_for(site_id: str, kind: str, display_name: str) -> str:
    """Build a statistic ID keyed on equipment position.

    Position rather than serial: a replaced optimizer reports a new serial but
    keeps its position, and serial-keyed history would split in two at exactly
    the moment continuous history matters most.
    """
    return f"{DOMAIN}:{slugify(site_id)}_{kind}_{slugify(display_name)}"


async def resolve_site_timezone(
    hass: HomeAssistant, snapshot: SiteSnapshot
) -> tzinfo:
    """Resolve the site's IANA timezone name to a tzinfo.

    The site's own timezone, never Home Assistant's. The library documents
    energy timestamps as naive site-local, so using the local timezone would
    shift every imported hour for a site in another zone.
    """
    resolved = await dt_util.async_get_time_zone(snapshot.timezone)
    if resolved is None:
        msg = f"SolarEdge reported an unknown site timezone: {snapshot.timezone}"
        raise ValueError(msg)
    return resolved


def bucket_energy(
    energy_data: list[EnergyData],
    snapshot: SiteSnapshot,
    site_tz: tzinfo,
) -> dict[str, list[tuple[datetime, float]]]:
    """Turn serial-keyed hourly energy into statistic-ID-keyed ordered series.

    Every known optimizer and inverter gets an entry for every hour in the
    payload. An hour a device did not report is zero rather than absent: for a
    running sum, "no production" and "no data" both mean the total did not move,
    and leaving a gap would make the next cumulative value look like a spike.
    """
    kinds = {
        **{inv.serial: ("inv", inv.display_name) for inv in snapshot.inverters},
        **{opt.serial: ("opt", opt.display_name) for opt in snapshot.optimizers},
    }
    buckets: dict[str, list[tuple[datetime, float]]] = {
        statistic_id_for(snapshot.site_id, kind, name): [] for kind, name in kinds.values()
    }

    unknown: set[str] = set()
    for entry in sorted(energy_data, key=lambda e: e.start_time):
        start = entry.start_time.replace(tzinfo=site_tz)
        for serial in entry.values:
            if serial not in kinds:
                unknown.add(serial)
        for serial, (kind, name) in kinds.items():
            key = statistic_id_for(snapshot.site_id, kind, name)
            buckets[key].append((start, float(entry.values.get(serial, 0.0))))

    if unknown:
        LOGGER.info(
            "Skipping %s equipment id(s) present in the energy data but absent "
            "from the site layout; this is expected after a hardware change: %s",
            len(unknown),
            ", ".join(sorted(unknown)),
        )

    return buckets
```

Strings are intentionally not given their own series: their totals are summed
from the same child optimizers already being imported, so a string series is
derivable from data the recorder already holds.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_statistics_mapping.py -v`
Expected: 10 passed.

- [ ] **Step 5: Commit**

```powershell
git add custom_components/solaredge_ha_web_client/statistics.py tests/test_statistics_mapping.py
git commit -m "feat: add statistic identifiers and energy bucketing"
```

---

## Task 9: Statistics — cumulative sums

**Files:**
- Modify: `custom_components/solaredge_ha_web_client/statistics.py`
- Test: `tests/test_statistics_sums.py`

**Interfaces:**
- Produces: `async_import_energy(hass, snapshot, entry_title, energy_data) -> int` returning the number of series written.

**This is the highest-risk code in the integration.** `async_add_external_statistics`
expects *cumulative* sums, not hourly deltas, so each run must read the last
stored sum and accumulate onto it. Getting it wrong produces Energy Dashboard
resets or step changes.

Port HA core's baseline approach rather than inventing one: query
`statistics_during_period` for the hour immediately before the window and take
its `sum`; if nothing is there, fall back to `get_last_statistics` and use that
value **only if its start precedes the window**; otherwise start at `0.0`. That
fallback is what lets an integration offline longer than the fetched window
resume without a discontinuity.

- [ ] **Step 1: Write the failing test**

`tests/test_statistics_sums.py`:

```python
"""Cumulative sums. The highest-risk logic in the integration."""

from datetime import datetime, timedelta
from unittest.mock import patch

from homeassistant.components.recorder import Recorder
from homeassistant.components.recorder.models import StatisticMeanType
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from solaredge_web import EnergyData

from custom_components.solaredge_ha_web_client.models import build_site_snapshot
from custom_components.solaredge_ha_web_client.statistics import (
    async_import_energy,
    statistic_id_for,
)

from .fixtures import SITE_COMPONENTS, SITE_ID, SITE_INFORMATION, equipment_dict


def _snapshot() -> object:
    return build_site_snapshot(
        site_id=SITE_ID,
        equipment=equipment_dict(),
        site_information=SITE_INFORMATION,
        site_components=SITE_COMPONENTS,
    )


def _energy(hours: list[tuple[int, float]]) -> list[EnergyData]:
    return [
        EnergyData(
            start_time=datetime(2026, 9, 4, hour, 0), values={"OPT-TEST-1": value}
        )
        for hour, value in hours
    ]


async def test_sums_accumulate_across_hours(
    recorder_mock: Recorder, hass: HomeAssistant
) -> None:
    """Sums must be a running total, not a repeat of each hourly value."""
    written: list[object] = []
    with patch(
        "custom_components.solaredge_ha_web_client.statistics."
        "async_add_external_statistics",
        side_effect=lambda _hass, _meta, stats: written.append(stats),
    ):
        await async_import_energy(
            hass, _snapshot(), "Test Site", _energy([(8, 100.0), (9, 200.0), (10, 50.0)])
        )

    key = statistic_id_for(SITE_ID, "opt", "1.1.1")
    series = next(
        stats
        for stats, meta in zip(written, [], strict=False)
        if meta["statistic_id"] == key
    ) if False else written[0]
    sums = [row["sum"] for row in series]
    assert sums == [100.0, 300.0, 350.0]
    assert [row["state"] for row in series] == [100.0, 200.0, 50.0]


async def test_sums_continue_from_the_stored_baseline(
    recorder_mock: Recorder, hass: HomeAssistant
) -> None:
    """Restarting must not reset a panel's lifetime total to zero."""
    written: list[list[dict[str, float]]] = []
    with (
        patch(
            "custom_components.solaredge_ha_web_client.statistics."
            "async_add_external_statistics",
            side_effect=lambda _h, _m, stats: written.append(stats),
        ),
        patch(
            "custom_components.solaredge_ha_web_client.statistics."
            "_async_get_baselines",
            return_value={
                statistic_id_for(SITE_ID, "opt", "1.1.1"): 5000.0,
                statistic_id_for(SITE_ID, "opt", "1.1.2"): 0.0,
                statistic_id_for(SITE_ID, "inv", "1"): 0.0,
            },
        ),
    ):
        await async_import_energy(
            hass, _snapshot(), "Test Site", _energy([(8, 100.0), (9, 200.0)])
        )

    sums = [row["sum"] for row in written[0]]
    assert sums == [5100.0, 5300.0]


async def test_reimporting_the_same_hours_does_not_double_count(
    recorder_mock: Recorder, hass: HomeAssistant
) -> None:
    """Overlapping windows are normal; they must overwrite, not accumulate."""
    calls: list[list[dict[str, float]]] = []
    with (
        patch(
            "custom_components.solaredge_ha_web_client.statistics."
            "async_add_external_statistics",
            side_effect=lambda _h, _m, stats: calls.append(stats),
        ),
        patch(
            "custom_components.solaredge_ha_web_client.statistics."
            "_async_get_baselines",
            return_value={
                statistic_id_for(SITE_ID, "opt", "1.1.1"): 0.0,
                statistic_id_for(SITE_ID, "opt", "1.1.2"): 0.0,
                statistic_id_for(SITE_ID, "inv", "1"): 0.0,
            },
        ),
    ):
        payload = _energy([(8, 100.0), (9, 200.0)])
        await async_import_energy(hass, _snapshot(), "Test Site", payload)
        await async_import_energy(hass, _snapshot(), "Test Site", payload)

    assert [row["sum"] for row in calls[0]] == [100.0, 300.0]
    assert [row["sum"] for row in calls[1]] == [100.0, 300.0]


async def test_metadata_declares_no_mean(
    recorder_mock: Recorder, hass: HomeAssistant
) -> None:
    """An hourly energy total has no meaningful mean, and we supply none."""
    metadata: list[dict[str, object]] = []
    with patch(
        "custom_components.solaredge_ha_web_client.statistics."
        "async_add_external_statistics",
        side_effect=lambda _h, meta, _s: metadata.append(meta),
    ):
        await async_import_energy(hass, _snapshot(), "Test Site", _energy([(8, 1.0)]))

    assert metadata[0]["mean_type"] is StatisticMeanType.NONE
    assert metadata[0]["has_sum"] is True
    assert metadata[0]["unit_of_measurement"] == "Wh"
    assert metadata[0]["source"] == "solaredge_ha_web_client"


async def test_empty_payload_writes_nothing(
    recorder_mock: Recorder, hass: HomeAssistant
) -> None:
    """An empty response is a failed fetch, not a day of zeros."""
    with patch(
        "custom_components.solaredge_ha_web_client.statistics."
        "async_add_external_statistics"
    ) as add:
        written = await async_import_energy(hass, _snapshot(), "Test Site", [])

    assert written == 0
    add.assert_not_called()


async def test_every_series_is_written(
    recorder_mock: Recorder, hass: HomeAssistant
) -> None:
    """Two optimizers and one inverter."""
    with patch(
        "custom_components.solaredge_ha_web_client.statistics."
        "async_add_external_statistics"
    ) as add:
        written = await async_import_energy(
            hass, _snapshot(), "Test Site", _energy([(8, 1.0)])
        )

    assert written == 3
    assert add.call_count == 3
```

If the first test's awkward `next(...) if False else written[0]` construction
survives review, simplify it to `written[0]` — only one series carries
`OPT-TEST-1` values, and it is written first because `snapshot.inverters` is
iterated after optimizers only if you order it that way. Assert on the
statistic ID from the metadata instead if ordering proves fragile.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_statistics_sums.py -v`
Expected: FAIL — `ImportError: cannot import name 'async_import_energy'`

- [ ] **Step 3: Write the implementation**

Append to `statistics.py`, extending the imports:

```python
# --- additional imports ---
from datetime import timedelta

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import (
    StatisticData,
    StatisticMeanType,
    StatisticMetaData,
)
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    get_last_statistics,
    statistics_during_period,
)
from homeassistant.const import UnitOfEnergy
from homeassistant.util.unit_conversion import EnergyConverter
```

```python
async def async_import_energy(
    hass: HomeAssistant,
    snapshot: SiteSnapshot,
    entry_title: str,
    energy_data: list[EnergyData],
) -> int:
    """Import hourly energy history as external statistics.

    Returns the number of series written.
    """
    if not energy_data:
        LOGGER.warning(
            "SolarEdge returned no energy data for site %s; skipping import",
            snapshot.site_id,
        )
        return 0

    site_tz = await resolve_site_timezone(hass, snapshot)
    buckets = bucket_energy(energy_data, snapshot, site_tz)
    if not buckets:
        return 0

    window_start = min(
        rows[0][0] for rows in buckets.values() if rows
    )
    baselines = await _async_get_baselines(hass, set(buckets), window_start)

    names = _display_names(snapshot)
    written = 0
    for statistic_id, rows in buckets.items():
        if not rows:
            continue
        running = baselines.get(statistic_id, 0.0)
        statistics: list[StatisticData] = []
        for start, value in rows:
            running += value
            statistics.append(StatisticData(start=start, state=value, sum=running))

        metadata = StatisticMetaData(
            mean_type=StatisticMeanType.NONE,
            has_sum=True,
            name=f"{entry_title} {names.get(statistic_id, statistic_id)}",
            source=DOMAIN,
            statistic_id=statistic_id,
            unit_class=EnergyConverter.UNIT_CLASS,
            unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        )
        LOGGER.debug("Writing %s statistics for %s", len(statistics), statistic_id)
        async_add_external_statistics(hass, metadata, statistics)
        written += 1

    return written


def _display_names(snapshot: SiteSnapshot) -> dict[str, str]:
    """Map statistic ID back to a human-readable equipment name."""
    names: dict[str, str] = {}
    for inv in snapshot.inverters:
        names[statistic_id_for(snapshot.site_id, "inv", inv.display_name)] = (
            f"Inverter {inv.display_name}"
        )
    for opt in snapshot.optimizers:
        names[statistic_id_for(snapshot.site_id, "opt", opt.display_name)] = (
            f"Module {opt.display_name}"
        )
    return names


async def _async_get_baselines(
    hass: HomeAssistant,
    statistic_ids: set[str],
    window_start: datetime,
) -> dict[str, float]:
    """Read the cumulative sum standing immediately before the import window.

    Ported from HA core's solaredge coordinator, which solves this against the
    same endpoints. Two lookups: the hour before the window, then a fallback to
    the newest statistic on record, accepted only if it predates the window.
    Without the fallback, an integration offline longer than the fetched window
    would restart every panel's total from zero.
    """
    before = window_start - timedelta(hours=1)
    recorder = get_instance(hass)

    during = await recorder.async_add_executor_job(
        statistics_during_period,
        hass,
        before,
        before + timedelta(seconds=1),
        statistic_ids,
        "hour",
        None,
        {"sum"},
    )

    baselines: dict[str, float] = {}
    for statistic_id in statistic_ids:
        rows = during.get(statistic_id)
        if rows:
            baselines[statistic_id] = float(rows[0]["sum"] or 0.0)
            continue

        last = await recorder.async_add_executor_job(
            get_last_statistics, hass, 1, statistic_id, True, {"sum"}
        )
        candidate = last.get(statistic_id) if last else None
        if candidate and candidate[0]["start"] < window_start.timestamp():
            baselines[statistic_id] = float(candidate[0]["sum"] or 0.0)
        else:
            # New install, or statistics cleared from developer tools.
            baselines[statistic_id] = 0.0

    return baselines
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_statistics_sums.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```powershell
git add custom_components/solaredge_ha_web_client/statistics.py tests/test_statistics_sums.py
git commit -m "feat: import energy history as cumulative statistics"
```

---

## Task 10: Entry setup, devices and platform forwarding

**Files:**
- Modify: `custom_components/solaredge_ha_web_client/__init__.py`
- Create: `custom_components/solaredge_ha_web_client/entity.py`
- Test: `tests/test_init.py`

**Interfaces:**
- Consumes: `SolarEdgeWebCoordinator`, `SolarEdgeWebConfigEntry`, `PLATFORMS`.
- Produces:
  - `async_setup_entry`, `async_unload_entry`, `async_reload_entry`
  - `entry.runtime_data` is the coordinator
  - `SolarEdgeWebEntity(CoordinatorEntity[SolarEdgeWebCoordinator])` base with `_attr_has_entity_name = True` and an `available` property honouring `data_is_stale`
  - `site_device_info`, `inverter_device_info`, `optimizer_device_info` helpers

Devices nest site → inverter → optimizer via `via_device`. Strings are not
devices: Home Assistant has no good concept for them and the rows would be
clutter, so the string name rides along as an optimizer attribute.

- [ ] **Step 1: Write the failing test**

`tests/test_init.py`:

```python
"""Entry setup, teardown and the device tree."""

from unittest.mock import patch

import aiohttp
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from custom_components.solaredge_ha_web_client.const import DOMAIN

from .test_coordinator_live import _client, _entry


async def _setup(hass: HomeAssistant, client: object) -> object:
    entry = _entry()
    entry.add_to_hass(hass)
    with patch(
        "custom_components.solaredge_ha_web_client.coordinator.SolarEdgeWeb",
        return_value=client,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


async def test_setup_succeeds_and_stores_the_coordinator(
    hass: HomeAssistant,
) -> None:
    entry = await _setup(hass, _client())
    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data is not None


async def test_devices_nest_optimizer_under_inverter_under_site(
    hass: HomeAssistant,
) -> None:
    """Flat devices would make twenty optimizers unreadable in the UI."""
    entry = await _setup(hass, _client())
    registry = dr.async_get(hass)

    site = registry.async_get_device(identifiers={(DOMAIN, "SITE-TEST")})
    inverter = registry.async_get_device(identifiers={(DOMAIN, "INV-TEST-1")})
    optimizer = registry.async_get_device(identifiers={(DOMAIN, "OPT-TEST-1")})

    assert site is not None
    assert inverter is not None
    assert optimizer is not None
    assert inverter.via_device_id == site.id
    assert optimizer.via_device_id == inverter.id


async def test_setup_retries_when_the_layout_is_unreachable(
    hass: HomeAssistant,
) -> None:
    from unittest.mock import AsyncMock

    client = _client(
        async_get_equipment=AsyncMock(side_effect=aiohttp.ClientError("boom"))
    )
    entry = await _setup(hass, client)
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_unload_succeeds(hass: HomeAssistant) -> None:
    entry = await _setup(hass, _client())
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_changing_options_reloads_the_entry(hass: HomeAssistant) -> None:
    """A new interval must take effect without a restart."""
    from custom_components.solaredge_ha_web_client.const import CONF_LIVE_INTERVAL

    entry = await _setup(hass, _client())
    with patch(
        "custom_components.solaredge_ha_web_client.coordinator.SolarEdgeWeb",
        return_value=_client(),
    ):
        hass.config_entries.async_update_entry(
            entry, options={CONF_LIVE_INTERVAL: 30}
        )
        await hass.async_block_till_done()

    assert entry.runtime_data.update_interval.total_seconds() == 30 * 60
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_init.py -v`
Expected: FAIL — setup does nothing, so the entry never reaches `LOADED`.

- [ ] **Step 3: Write the implementation**

`custom_components/solaredge_ha_web_client/__init__.py`:

```python
"""The SolarEdge Web Client integration."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from .const import DOMAIN, PLATFORMS
from .coordinator import SolarEdgeWebConfigEntry, SolarEdgeWebCoordinator
from .entity import inverter_device_info, optimizer_device_info, site_device_info


async def async_setup_entry(
    hass: HomeAssistant, entry: SolarEdgeWebConfigEntry
) -> bool:
    """Set up a SolarEdge site from a config entry."""
    coordinator = SolarEdgeWebCoordinator(hass, entry)
    await coordinator.async_load_snapshot()
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    _async_register_devices(hass, entry, coordinator)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: SolarEdgeWebConfigEntry
) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_reload_entry(
    hass: HomeAssistant, entry: SolarEdgeWebConfigEntry
) -> None:
    """Reload when the options change, so a new interval takes effect."""
    await hass.config_entries.async_reload(entry.entry_id)


def _async_register_devices(
    hass: HomeAssistant,
    entry: SolarEdgeWebConfigEntry,
    coordinator: SolarEdgeWebCoordinator,
) -> None:
    """Register site, inverters and optimizers up front.

    Registering here rather than letting entities imply devices means the
    hierarchy exists even for equipment whose entities are all disabled by
    default.
    """
    registry = dr.async_get(hass)
    snapshot = coordinator.snapshot

    registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        **site_device_info(snapshot),
    )
    for inverter in snapshot.inverters:
        registry.async_get_or_create(
            config_entry_id=entry.entry_id,
            **inverter_device_info(snapshot, inverter, coordinator.data),
        )
    for optimizer in snapshot.optimizers:
        registry.async_get_or_create(
            config_entry_id=entry.entry_id,
            **optimizer_device_info(snapshot, optimizer, coordinator.data),
        )
```

`custom_components/solaredge_ha_web_client/entity.py`:

```python
"""Shared device info and entity base."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN

if TYPE_CHECKING:
    from .coordinator import SolarEdgeWebCoordinator
    from .models import InverterInfo, LiveData, OptimizerInfo, SiteSnapshot

MANUFACTURER = "SolarEdge"


def site_device_info(snapshot: SiteSnapshot) -> DeviceInfo:
    """Device info for the site itself."""
    return DeviceInfo(
        identifiers={(DOMAIN, snapshot.site_id)},
        manufacturer=MANUFACTURER,
        name=f"SolarEdge Site {snapshot.site_id}",
        model="Monitoring site",
        entry_type=None,
    )


def inverter_device_info(
    snapshot: SiteSnapshot,
    inverter: InverterInfo,
    live: LiveData | None,
) -> DeviceInfo:
    """Device info for an inverter, hung off the site."""
    data = (live.inverters if live else {}).get(inverter.serial)
    return DeviceInfo(
        identifiers={(DOMAIN, inverter.serial)},
        manufacturer=data.manufacturer if data and data.manufacturer else MANUFACTURER,
        name=inverter.display_name,
        model=data.model if data and data.model else None,
        sw_version=data.cpu_version if data else None,
        serial_number=inverter.serial,
        via_device=(DOMAIN, snapshot.site_id),
    )


def optimizer_device_info(
    snapshot: SiteSnapshot,
    optimizer: OptimizerInfo,
    live: LiveData | None,
) -> DeviceInfo:
    """Device info for an optimizer, hung off its inverter."""
    data = (live.optimizers if live else {}).get(optimizer.serial)
    return DeviceInfo(
        identifiers={(DOMAIN, optimizer.serial)},
        manufacturer=MANUFACTURER,
        name=f"Optimizer {optimizer.display_name}",
        model=data.model if data and data.model else None,
        serial_number=optimizer.serial,
        via_device=(DOMAIN, optimizer.inverter_serial),
    )


class SolarEdgeWebEntity(CoordinatorEntity["SolarEdgeWebCoordinator"]):
    """Base for every entity in this integration."""

    _attr_has_entity_name = True

    @property
    def available(self) -> bool:
        """Whether this entity has data worth trusting.

        Last-known values are held through brief outages; only a sustained
        failure marks the data stale. Flipping on the first failed poll would
        strobe every panel entity for a single hiccup, and would be false
        precision anyway given the source refreshes about every 15 minutes.
        """
        return super().available and not self.coordinator.data_is_stale
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_init.py -v`
Expected: 5 passed. The two platform modules do not exist yet, so add
placeholder `sensor.py` and `binary_sensor.py` containing only
`async_setup_entry` stubs that add no entities if forwarding errors; Tasks 11
and 12 replace them.

- [ ] **Step 5: Commit**

```powershell
git add custom_components/solaredge_ha_web_client/__init__.py custom_components/solaredge_ha_web_client/entity.py tests/test_init.py
git commit -m "feat: wire entry setup and the device tree"
```

---

## Task 11: Sensors

**Files:**
- Create: `custom_components/solaredge_ha_web_client/sensor.py`
- Test: `tests/test_sensor.py`

**Interfaces:**
- Consumes: `SolarEdgeWebEntity`, device-info helpers, `LiveData`.
- Produces: sensor entities for every optimizer, inverter and the site.

Unique IDs are `{site_id}_{serial}_{key}` for equipment sensors and
`{site_id}_{key}` for site sensors, and are a persistent contract — changing one
orphans the user's history and customisations.

- [ ] **Step 1: Write the failing test**

`tests/test_sensor.py`:

```python
"""Sensor entities."""

from unittest.mock import AsyncMock, patch

import aiohttp
from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from custom_components.solaredge_ha_web_client.const import MAX_CONSECUTIVE_FAILURES

from .test_coordinator_live import _client
from .test_init import _setup


async def test_optimizer_power_is_enabled_and_correct(
    hass: HomeAssistant,
) -> None:
    await _setup(hass, _client())
    state = hass.states.get("sensor.optimizer_1_1_1_power")
    assert state is not None
    assert state.state == "198.0"
    assert state.attributes["device_class"] == SensorDeviceClass.POWER
    assert state.attributes["state_class"] == SensorStateClass.MEASUREMENT
    assert state.attributes["unit_of_measurement"] == "W"


async def test_optimizer_temperature_is_named_as_a_daily_maximum(
    hass: HomeAssistant,
) -> None:
    """The endpoint returns a max over a range, so the name must not imply live."""
    await _setup(hass, _client())
    state = hass.states.get("sensor.optimizer_1_1_1_max_temperature_today")
    assert state is not None
    assert state.state == "41.5"
    assert state.attributes["device_class"] == SensorDeviceClass.TEMPERATURE


async def test_voltage_and_current_are_disabled_by_default(
    hass: HomeAssistant,
) -> None:
    """Twenty optimizers times five sensors is mostly noise."""
    entry = await _setup(hass, _client())
    registry = er.async_get(hass)

    for suffix in ("module_voltage", "optimizer_voltage", "current", "last_measurement"):
        rows = [
            e
            for e in er.async_entries_for_config_entry(registry, entry.entry_id)
            if e.unique_id.endswith(suffix)
        ]
        assert rows, f"no entity found for {suffix}"
        assert all(e.disabled_by is er.RegistryEntryDisabler.INTEGRATION for e in rows)


async def test_peak_power_has_no_device_or_state_class(
    hass: HomeAssistant,
) -> None:
    """kWp is a nameplate rating; device_class power would fail unit validation."""
    await _setup(hass, _client())
    state = hass.states.get("sensor.solaredge_site_site_test_peak_power")
    assert state is not None
    assert state.state == "11.7"
    assert "device_class" not in state.attributes
    assert "state_class" not in state.attributes


async def test_cloud_sensors_are_labelled_cloud(hass: HomeAssistant) -> None:
    """Without the qualifier these sit next to Modbus entities, disagreeing."""
    await _setup(hass, _client())
    state = hass.states.get("sensor.solaredge_site_site_test_site_power_cloud")
    assert state is not None
    assert "Cloud" in state.attributes["friendly_name"]


async def test_last_successful_update_is_present(hass: HomeAssistant) -> None:
    """Availability holds stale values, so staleness must be observable."""
    await _setup(hass, _client())
    state = hass.states.get("sensor.solaredge_site_site_test_last_successful_update")
    assert state is not None
    assert state.state != STATE_UNKNOWN


async def test_failed_section_yields_unknown_not_a_stale_number(
    hass: HomeAssistant,
) -> None:
    client = _client(
        async_get_optimizer_temperatures=AsyncMock(
            side_effect=aiohttp.ClientError("boom")
        )
    )
    await _setup(hass, client)

    assert hass.states.get("sensor.optimizer_1_1_1_power").state == "198.0"
    assert (
        hass.states.get("sensor.optimizer_1_1_1_max_temperature_today").state
        == STATE_UNKNOWN
    )


async def test_sustained_failure_marks_entities_unavailable(
    hass: HomeAssistant,
) -> None:
    entry = await _setup(hass, _client())
    coordinator = entry.runtime_data

    error = AsyncMock(side_effect=aiohttp.ClientError("boom"))
    coordinator.client.async_get_optimizer_data = error
    coordinator.client.async_get_optimizer_temperatures = error
    coordinator.client.async_get_inverter_data = error
    coordinator.client.async_get_live_power = error
    coordinator.client.async_get_alerts = error

    for _ in range(MAX_CONSECUTIVE_FAILURES):
        await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert hass.states.get("sensor.optimizer_1_1_1_power").state == STATE_UNAVAILABLE


async def test_unique_ids_are_stable_and_distinct(hass: HomeAssistant) -> None:
    entry = await _setup(hass, _client())
    registry = er.async_get(hass)
    rows = er.async_entries_for_config_entry(registry, entry.entry_id)
    unique_ids = [e.unique_id for e in rows]

    assert len(unique_ids) == len(set(unique_ids))
    assert "SITE-TEST_OPT-TEST-1_power" in unique_ids
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_sensor.py -v`
Expected: FAIL — no sensor entities exist.

- [ ] **Step 3: Write the implementation**

`custom_components/solaredge_ha_web_client/sensor.py`:

```python
"""Sensor platform."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    EntityCategory,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfPower,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .entity import (
    SolarEdgeWebEntity,
    inverter_device_info,
    optimizer_device_info,
    site_device_info,
)
from .models import InverterInfo, LiveData, OptimizerInfo, SiteSnapshot

if TYPE_CHECKING:
    from .coordinator import SolarEdgeWebConfigEntry, SolarEdgeWebCoordinator


@dataclass(frozen=True, kw_only=True)
class OptimizerSensorDescription(SensorEntityDescription):
    """Describes an optimizer sensor."""

    value_fn: Callable[[LiveData, str], Any]
    section_ok_fn: Callable[[LiveData], bool]


@dataclass(frozen=True, kw_only=True)
class InverterSensorDescription(SensorEntityDescription):
    """Describes an inverter sensor."""

    value_fn: Callable[[LiveData, str], Any]
    section_ok_fn: Callable[[LiveData], bool]


@dataclass(frozen=True, kw_only=True)
class SiteSensorDescription(SensorEntityDescription):
    """Describes a site sensor."""

    value_fn: Callable[[LiveData, SiteSnapshot], Any]
    section_ok_fn: Callable[[LiveData], bool]


OPTIMIZER_SENSORS: tuple[OptimizerSensorDescription, ...] = (
    OptimizerSensorDescription(
        key="power",
        translation_key="power",
        name="Power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        value_fn=lambda live, serial: getattr(
            live.optimizers.get(serial), "power", None
        ),
        section_ok_fn=lambda live: live.optimizers_ok,
    ),
    OptimizerSensorDescription(
        key="max_temperature_today",
        translation_key="max_temperature_today",
        # Named a maximum because the endpoint returns the highest reading over
        # a date range, not an instantaneous one. It resets at local midnight.
        name="Max temperature today",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        value_fn=lambda live, serial: live.temperatures.get(serial),
        section_ok_fn=lambda live: live.temperatures_ok,
    ),
    OptimizerSensorDescription(
        key="module_voltage",
        translation_key="module_voltage",
        name="Module voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda live, serial: getattr(
            live.optimizers.get(serial), "voltage", None
        ),
        section_ok_fn=lambda live: live.optimizers_ok,
    ),
    OptimizerSensorDescription(
        key="optimizer_voltage",
        translation_key="optimizer_voltage",
        name="Optimizer voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda live, serial: getattr(
            live.optimizers.get(serial), "optimizer_voltage", None
        ),
        section_ok_fn=lambda live: live.optimizers_ok,
    ),
    OptimizerSensorDescription(
        key="current",
        translation_key="current",
        name="Current",
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda live, serial: getattr(
            live.optimizers.get(serial), "current", None
        ),
        section_ok_fn=lambda live: live.optimizers_ok,
    ),
    OptimizerSensorDescription(
        key="last_measurement",
        translation_key="last_measurement",
        name="Last measurement",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda live, serial: getattr(
            live.optimizers.get(serial), "last_measurement", None
        ),
        section_ok_fn=lambda live: live.optimizers_ok,
    ),
)

INVERTER_SENSORS: tuple[InverterSensorDescription, ...] = (
    InverterSensorDescription(
        key="ac_power_cloud",
        translation_key="ac_power_cloud",
        # "(Cloud)" distinguishes this from the Modbus sensor of the same
        # meaning, which is local, faster, and will disagree by minutes.
        name="AC power (Cloud)",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        value_fn=lambda live, serial: getattr(
            live.inverters.get(serial), "power", None
        ),
        section_ok_fn=lambda live: live.inverters_ok,
    ),
    InverterSensorDescription(
        key="status_cloud",
        translation_key="status_cloud",
        name="Status (Cloud)",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda live, serial: getattr(
            live.inverters.get(serial), "status", None
        ),
        section_ok_fn=lambda live: live.inverters_ok,
    ),
)

SITE_SENSORS: tuple[SiteSensorDescription, ...] = (
    SiteSensorDescription(
        key="site_power_cloud",
        translation_key="site_power_cloud",
        name="Site power (Cloud)",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        value_fn=lambda live, _snapshot: getattr(
            live.live_power, "current_power", None
        ),
        section_ok_fn=lambda live: live.live_power_ok,
    ),
    SiteSensorDescription(
        key="peak_power",
        translation_key="peak_power",
        name="Peak power",
        # Deliberately no device class and no state class: kWp is a nameplate
        # rating, not a measurement, and no HA device class accepts the unit.
        native_unit_of_measurement="kWp",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda _live, snapshot: snapshot.peak_power_kwp,
        section_ok_fn=lambda _live: True,
    ),
    SiteSensorDescription(
        key="last_successful_update",
        translation_key="last_successful_update",
        name="Last successful update",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda live, _snapshot: live.last_success,
        section_ok_fn=lambda _live: True,
    ),
    SiteSensorDescription(
        key="alert_count",
        translation_key="alert_count",
        name="Open alerts",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda live, _snapshot: live.alert_count,
        section_ok_fn=lambda live: live.alerts_ok,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SolarEdgeWebConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up sensors."""
    coordinator = entry.runtime_data
    snapshot = coordinator.snapshot

    entities: list[SensorEntity] = [
        SolarEdgeSiteSensor(coordinator, description) for description in SITE_SENSORS
    ]
    entities += [
        SolarEdgeInverterSensor(coordinator, inverter, description)
        for inverter in snapshot.inverters
        for description in INVERTER_SENSORS
    ]
    entities += [
        SolarEdgeOptimizerSensor(coordinator, optimizer, description)
        for optimizer in snapshot.optimizers
        for description in OPTIMIZER_SENSORS
    ]
    async_add_entities(entities)


class SolarEdgeOptimizerSensor(SolarEdgeWebEntity, SensorEntity):
    """A sensor for one optimizer."""

    entity_description: OptimizerSensorDescription

    def __init__(
        self,
        coordinator: SolarEdgeWebCoordinator,
        optimizer: OptimizerInfo,
        description: OptimizerSensorDescription,
    ) -> None:
        """Initialise the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._optimizer = optimizer
        self._attr_unique_id = (
            f"{coordinator.snapshot.site_id}_{optimizer.serial}_{description.key}"
        )
        self._attr_device_info = optimizer_device_info(
            coordinator.snapshot, optimizer, coordinator.data
        )
        self._attr_extra_state_attributes = {
            "string": optimizer.string_name,
            "position": optimizer.display_name,
        }

    @property
    def native_value(self) -> Any:
        """Return the reading, or None when its section failed this cycle."""
        live = self.coordinator.data
        if not self.entity_description.section_ok_fn(live):
            return None
        return self.entity_description.value_fn(live, self._optimizer.serial)


class SolarEdgeInverterSensor(SolarEdgeWebEntity, SensorEntity):
    """A sensor for one inverter."""

    entity_description: InverterSensorDescription

    def __init__(
        self,
        coordinator: SolarEdgeWebCoordinator,
        inverter: InverterInfo,
        description: InverterSensorDescription,
    ) -> None:
        """Initialise the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._inverter = inverter
        self._attr_unique_id = (
            f"{coordinator.snapshot.site_id}_{inverter.serial}_{description.key}"
        )
        self._attr_device_info = inverter_device_info(
            coordinator.snapshot, inverter, coordinator.data
        )

    @property
    def native_value(self) -> Any:
        """Return the reading, or None when its section failed this cycle."""
        live = self.coordinator.data
        if not self.entity_description.section_ok_fn(live):
            return None
        return self.entity_description.value_fn(live, self._inverter.serial)


class SolarEdgeSiteSensor(SolarEdgeWebEntity, SensorEntity):
    """A site-level sensor."""

    entity_description: SiteSensorDescription

    def __init__(
        self,
        coordinator: SolarEdgeWebCoordinator,
        description: SiteSensorDescription,
    ) -> None:
        """Initialise the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.snapshot.site_id}_{description.key}"
        self._attr_device_info = site_device_info(coordinator.snapshot)

    @property
    def native_value(self) -> Any:
        """Return the reading, or None when its section failed this cycle."""
        live = self.coordinator.data
        if not self.entity_description.section_ok_fn(live):
            return None
        return self.entity_description.value_fn(live, self.coordinator.snapshot)

    @property
    def available(self) -> bool:
        """Peak power and last-update stay available; they are not live reads."""
        if self.entity_description.key in ("peak_power", "last_successful_update"):
            return True
        return super().available
```

Add the matching `entity` block to `strings.json` and `translations/en.json` so
the names are translatable; the `name=` values above are the fallbacks.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_sensor.py -v`
Expected: 9 passed. Entity IDs in the assertions depend on the friendly names
Home Assistant generates; if any lookup misses, read the actual ID from
`hass.states.async_entity_ids("sensor")` and correct the test rather than
renaming the entity.

- [ ] **Step 5: Commit**

```powershell
git add custom_components/solaredge_ha_web_client/sensor.py custom_components/solaredge_ha_web_client/strings.json custom_components/solaredge_ha_web_client/translations tests/test_sensor.py
git commit -m "feat: add optimizer, inverter and site sensors"
```

---

## Task 12: Binary sensors

**Files:**
- Create: `custom_components/solaredge_ha_web_client/binary_sensor.py`
- Test: `tests/test_binary_sensor.py`

**Interfaces:**
- Produces: a site `problem` binary sensor from the alert count, and a
  `connectivity` binary sensor per inverter from `InverterData.status`.

- [ ] **Step 1: Write the failing test**

`tests/test_binary_sensor.py`:

```python
"""Binary sensor entities."""

from unittest.mock import AsyncMock

import aiohttp
from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from solaredge_web import InverterData

from .test_coordinator_live import _client
from .test_init import _setup


async def test_no_alerts_is_off(hass: HomeAssistant) -> None:
    await _setup(hass, _client())
    state = hass.states.get("binary_sensor.solaredge_site_site_test_alerts")
    assert state is not None
    assert state.state == STATE_OFF
    assert state.attributes["device_class"] == BinarySensorDeviceClass.PROBLEM


async def test_open_alerts_is_on_and_carries_detail(hass: HomeAssistant) -> None:
    client = _client(
        async_get_alerts=AsyncMock(
            return_value={
                "totalAlertsCount": 2,
                "topAlerts": [{"name": "Panel underperforming"}],
            }
        )
    )
    await _setup(hass, client)
    state = hass.states.get("binary_sensor.solaredge_site_site_test_alerts")
    assert state.state == STATE_ON
    assert state.attributes["alert_count"] == 2


async def test_failed_alert_fetch_is_unknown_not_off(hass: HomeAssistant) -> None:
    """Reporting 'no problem' when we do not know is the dangerous failure."""
    client = _client(
        async_get_alerts=AsyncMock(side_effect=aiohttp.ClientError("boom"))
    )
    await _setup(hass, client)
    state = hass.states.get("binary_sensor.solaredge_site_site_test_alerts")
    assert state.state == STATE_UNKNOWN


async def test_inverter_connectivity_follows_status(hass: HomeAssistant) -> None:
    client = _client(
        async_get_inverter_data=AsyncMock(
            return_value={
                "INV-TEST-1": InverterData(serial="INV-TEST-1", status="ACTIVE")
            }
        )
    )
    await _setup(hass, client)
    state = hass.states.get("binary_sensor.inverter_1_connectivity")
    assert state is not None
    assert state.state == STATE_ON


async def test_inverter_connectivity_off_when_not_active(
    hass: HomeAssistant,
) -> None:
    client = _client(
        async_get_inverter_data=AsyncMock(
            return_value={
                "INV-TEST-1": InverterData(serial="INV-TEST-1", status="DISABLED")
            }
        )
    )
    await _setup(hass, client)
    assert hass.states.get("binary_sensor.inverter_1_connectivity").state == STATE_OFF
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_binary_sensor.py -v`
Expected: FAIL — no binary sensors exist.

- [ ] **Step 3: Write the implementation**

`custom_components/solaredge_ha_web_client/binary_sensor.py`:

```python
"""Binary sensor platform."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .entity import SolarEdgeWebEntity, inverter_device_info, site_device_info

if TYPE_CHECKING:
    from .coordinator import SolarEdgeWebConfigEntry, SolarEdgeWebCoordinator
    from .models import InverterInfo

ACTIVE_STATUSES = {"ACTIVE", "ON_GRID", "PRODUCING"}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SolarEdgeWebConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up binary sensors."""
    coordinator = entry.runtime_data
    entities: list[BinarySensorEntity] = [SolarEdgeAlertsBinarySensor(coordinator)]
    entities += [
        SolarEdgeInverterConnectivity(coordinator, inverter)
        for inverter in coordinator.snapshot.inverters
    ]
    async_add_entities(entities)


class SolarEdgeAlertsBinarySensor(SolarEdgeWebEntity, BinarySensorEntity):
    """Whether the site has open alerts."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_name = "Alerts"

    def __init__(self, coordinator: SolarEdgeWebCoordinator) -> None:
        """Initialise the sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.snapshot.site_id}_alerts"
        self._attr_device_info = site_device_info(coordinator.snapshot)

    @property
    def is_on(self) -> bool | None:
        """True when alerts are open, None when the fetch failed.

        None rather than False on failure: reporting "no problem" when the
        answer is unknown is the one wrong answer that matters here.
        """
        live = self.coordinator.data
        if not live.alerts_ok or live.alert_count is None:
            return None
        return live.alert_count > 0

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose the count alongside the boolean."""
        return {"alert_count": self.coordinator.data.alert_count}


class SolarEdgeInverterConnectivity(SolarEdgeWebEntity, BinarySensorEntity):
    """Whether an inverter is reporting as active."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_name = "Connectivity"

    def __init__(
        self, coordinator: SolarEdgeWebCoordinator, inverter: InverterInfo
    ) -> None:
        """Initialise the sensor."""
        super().__init__(coordinator)
        self._inverter = inverter
        self._attr_unique_id = (
            f"{coordinator.snapshot.site_id}_{inverter.serial}_connectivity"
        )
        self._attr_device_info = inverter_device_info(
            coordinator.snapshot, inverter, coordinator.data
        )

    @property
    def is_on(self) -> bool | None:
        """True when the inverter reports an active status."""
        live = self.coordinator.data
        if not live.inverters_ok:
            return None
        data = live.inverters.get(self._inverter.serial)
        if data is None or data.status is None:
            return None
        return data.status.upper() in ACTIVE_STATUSES
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_binary_sensor.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```powershell
git add custom_components/solaredge_ha_web_client/binary_sensor.py tests/test_binary_sensor.py
git commit -m "feat: add alert and inverter connectivity binary sensors"
```

---

## Task 13: Statistics gating in the coordinator

**Files:**
- Modify: `custom_components/solaredge_ha_web_client/coordinator.py`
- Test: `tests/test_coordinator_statistics.py`

**Interfaces:**
- Consumes: `statistics.async_import_energy`, `statistics.statistic_id_for`, `const.STATISTICS_INTERVAL`, `const.STATISTICS_OVERLAP`.
- Produces: `SolarEdgeWebCoordinator._async_maybe_import_statistics()`, called at the end of each successful cycle.

Gating is on **elapsed time**, read from the recorder, not a cycle counter. The
recorder already knows when we last wrote, so nothing needs persisting; this is
self-healing across restarts and correct at any poll interval.

The import runs in its **own error boundary**. Live data is the cycle's product
and statistics are a side effect: a twice-daily history import must never take
twenty live panel sensors down with it.

- [ ] **Step 1: Write the failing test**

`tests/test_coordinator_statistics.py`:

```python
"""Statistics gating and its error boundary."""

from datetime import timedelta
from unittest.mock import AsyncMock, patch

import aiohttp
from homeassistant.components.recorder import Recorder
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.solaredge_ha_web_client.const import STATISTICS_INTERVAL

from .test_coordinator_live import _client, _coordinator


async def test_imports_when_no_statistics_exist(
    recorder_mock: Recorder, hass: HomeAssistant
) -> None:
    """A fresh install must backfill rather than wait twelve hours."""
    client = _client(async_get_energy_data=AsyncMock(return_value=[]))
    coordinator = await _coordinator(hass, client)

    with (
        patch(
            "custom_components.solaredge_ha_web_client.coordinator."
            "async_import_energy",
            new=AsyncMock(return_value=3),
        ) as import_energy,
        patch(
            "custom_components.solaredge_ha_web_client.coordinator."
            "_async_newest_statistic_time",
            new=AsyncMock(return_value=None),
        ),
    ):
        await coordinator._async_update_data()

    import_energy.assert_awaited_once()


async def test_skips_when_statistics_are_recent(
    recorder_mock: Recorder, hass: HomeAssistant
) -> None:
    client = _client(async_get_energy_data=AsyncMock(return_value=[]))
    coordinator = await _coordinator(hass, client)
    recent = dt_util.utcnow() - timedelta(hours=1)

    with (
        patch(
            "custom_components.solaredge_ha_web_client.coordinator."
            "async_import_energy",
            new=AsyncMock(return_value=0),
        ) as import_energy,
        patch(
            "custom_components.solaredge_ha_web_client.coordinator."
            "_async_newest_statistic_time",
            new=AsyncMock(return_value=recent),
        ),
    ):
        await coordinator._async_update_data()

    import_energy.assert_not_awaited()


async def test_imports_once_the_interval_has_elapsed(
    recorder_mock: Recorder, hass: HomeAssistant
) -> None:
    client = _client(async_get_energy_data=AsyncMock(return_value=[]))
    coordinator = await _coordinator(hass, client)
    stale = dt_util.utcnow() - STATISTICS_INTERVAL - timedelta(minutes=1)

    with (
        patch(
            "custom_components.solaredge_ha_web_client.coordinator."
            "async_import_energy",
            new=AsyncMock(return_value=3),
        ) as import_energy,
        patch(
            "custom_components.solaredge_ha_web_client.coordinator."
            "_async_newest_statistic_time",
            new=AsyncMock(return_value=stale),
        ),
    ):
        await coordinator._async_update_data()

    import_energy.assert_awaited_once()


async def test_statistics_failure_does_not_fail_the_cycle(
    recorder_mock: Recorder, hass: HomeAssistant
) -> None:
    """Live sensors must survive a broken history import."""
    client = _client(
        async_get_energy_data=AsyncMock(side_effect=aiohttp.ClientError("boom"))
    )
    coordinator = await _coordinator(hass, client)

    with patch(
        "custom_components.solaredge_ha_web_client.coordinator."
        "_async_newest_statistic_time",
        new=AsyncMock(return_value=None),
    ):
        data = await coordinator._async_update_data()

    assert data.optimizers["OPT-TEST-1"].power == 198.0
    assert coordinator.consecutive_failures == 0


async def test_statistics_failure_does_not_trigger_reauth_alone(
    recorder_mock: Recorder, hass: HomeAssistant
) -> None:
    """A 401 on the energy endpoint is still a credential problem."""
    from unittest.mock import Mock

    from homeassistant.exceptions import ConfigEntryAuthFailed
    import pytest

    client = _client(
        async_get_energy_data=AsyncMock(
            side_effect=aiohttp.ClientResponseError(
                request_info=Mock(), history=(), status=401, message="denied"
            )
        )
    )
    coordinator = await _coordinator(hass, client)

    with (
        patch(
            "custom_components.solaredge_ha_web_client.coordinator."
            "_async_newest_statistic_time",
            new=AsyncMock(return_value=None),
        ),
        pytest.raises(ConfigEntryAuthFailed),
    ):
        await coordinator._async_update_data()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_coordinator_statistics.py -v`
Expected: FAIL — `AttributeError: module has no attribute '_async_newest_statistic_time'`

- [ ] **Step 3: Write the implementation**

Add to `coordinator.py`, extending imports:

```python
# --- additional imports ---
from datetime import datetime

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.statistics import get_last_statistics

from .const import STATISTICS_INTERVAL, STATISTICS_OVERLAP
from .statistics import async_import_energy, statistic_id_for
```

Call the gate at the end of `_async_update_data`, just before returning:

```python
        self._consecutive_failures = 0
        await self._async_maybe_import_statistics()
        return live
```

Add these to the class:

```python
    async def _async_maybe_import_statistics(self) -> None:
        """Import energy history if the interval has elapsed.

        Wrapped in its own error boundary: live data is this cycle's product
        and statistics are a side effect, so a failed history import must not
        take the live sensors down with it. A credential rejection is the one
        exception — that is not specific to statistics and the user has to act.
        """
        try:
            if not await self._async_statistics_are_due():
                return

            LOGGER.debug("Importing energy statistics for site %s", self.site_id)
            energy_data = await self.client.async_get_energy_data()
            await async_import_energy(
                self.hass,
                self.snapshot,
                self.config_entry.title,
                energy_data,
            )
        except ConfigEntryAuthFailed:
            raise
        except Exception as err:  # noqa: BLE001
            mapped = map_client_error(err, "energy data")
            if isinstance(mapped, ConfigEntryAuthFailed):
                raise mapped from err
            LOGGER.warning("Energy statistics import failed: %s", mapped)

    async def _async_statistics_are_due(self) -> bool:
        """Whether enough time has passed since the newest stored statistic.

        Elapsed time from the recorder rather than a cycle counter: the
        recorder already knows when we last wrote, so no state needs
        persisting, and the gate stays correct across restarts and at any poll
        interval.
        """
        reference = statistic_id_for(
            self.site_id, "opt", self.snapshot.optimizers[0].display_name
        ) if self.snapshot.optimizers else None
        if reference is None:
            return False

        newest = await _async_newest_statistic_time(self.hass, reference)
        if newest is None:
            return True
        return dt_util.utcnow() - newest >= STATISTICS_INTERVAL


async def _async_newest_statistic_time(
    hass: HomeAssistant, statistic_id: str
) -> datetime | None:
    """Return when the newest stored statistic for this ID starts."""
    rows = await get_instance(hass).async_add_executor_job(
        get_last_statistics, hass, 1, statistic_id, True, {"sum"}
    )
    entries = rows.get(statistic_id) if rows else None
    if not entries:
        return None
    return dt_util.utc_from_timestamp(entries[0]["start"])
```

The gate reads one reference series rather than all of them: every series is
written in the same pass, so their newest timestamps move together, and checking
one avoids twenty recorder round-trips per poll.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_coordinator_statistics.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```powershell
git add custom_components/solaredge_ha_web_client/coordinator.py tests/test_coordinator_statistics.py
git commit -m "feat: gate statistics import on elapsed time"
```

---

## Task 14: Diagnostics

**Files:**
- Create: `custom_components/solaredge_ha_web_client/diagnostics.py`
- Test: `tests/test_diagnostics.py`

**Interfaces:**
- Produces: `async_get_config_entry_diagnostics(hass, entry) -> dict[str, Any]`.

Diagnostics get pasted into public issue trackers, so credentials, site ID and
serials are all redacted.

- [ ] **Step 1: Write the failing test**

`tests/test_diagnostics.py`:

```python
"""Diagnostics redaction."""

import json

from homeassistant.core import HomeAssistant

from custom_components.solaredge_ha_web_client.diagnostics import (
    async_get_config_entry_diagnostics,
)

from .test_coordinator_live import _client
from .test_init import _setup


async def test_secrets_are_redacted(hass: HomeAssistant) -> None:
    """These get pasted into public issue trackers."""
    entry = await _setup(hass, _client())
    result = await async_get_config_entry_diagnostics(hass, entry)
    dumped = json.dumps(result)

    assert "hunter2" not in dumped
    assert "user@example.com" not in dumped
    assert "SITE-TEST" not in dumped
    assert "OPT-TEST-1" not in dumped
    assert "INV-TEST-1" not in dumped


async def test_useful_shape_survives(hass: HomeAssistant) -> None:
    """Redaction must not leave the dump useless for debugging."""
    entry = await _setup(hass, _client())
    result = await async_get_config_entry_diagnostics(hass, entry)

    assert result["snapshot"]["optimizer_count"] == 2
    assert result["snapshot"]["inverter_count"] == 1
    assert result["snapshot"]["timezone"] == "Asia/Jerusalem"
    assert result["snapshot"]["peak_power_kwp"] == 11.7
    assert result["live"]["optimizers_ok"] is True
    assert result["live"]["optimizer_readings"] == 1
    assert result["consecutive_failures"] == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_diagnostics.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named '...diagnostics'`

- [ ] **Step 3: Write the implementation**

`custom_components/solaredge_ha_web_client/diagnostics.py`:

```python
"""Diagnostics support."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.core import HomeAssistant

if TYPE_CHECKING:
    from .coordinator import SolarEdgeWebConfigEntry


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: SolarEdgeWebConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry.

    Reports counts and flags rather than payloads. Serials, site IDs and
    credentials are all identifying, and a diagnostics dump is something users
    paste into public issue trackers — so this reports the shape of the data,
    which is what actually helps debugging, and none of its identifiers.
    """
    coordinator = entry.runtime_data
    snapshot = coordinator.snapshot
    live = coordinator.data

    return {
        "snapshot": {
            "inverter_count": len(snapshot.inverters),
            "optimizer_count": len(snapshot.optimizers),
            "timezone": snapshot.timezone,
            "peak_power_kwp": snapshot.peak_power_kwp,
            "has_meter": snapshot.has_meter,
            "has_storage": snapshot.has_storage,
            "strings": sorted({opt.string_name for opt in snapshot.optimizers}),
        },
        "live": {
            "optimizers_ok": live.optimizers_ok,
            "temperatures_ok": live.temperatures_ok,
            "inverters_ok": live.inverters_ok,
            "live_power_ok": live.live_power_ok,
            "alerts_ok": live.alerts_ok,
            "optimizer_readings": len(live.optimizers),
            "temperature_readings": len(live.temperatures),
            "inverter_readings": len(live.inverters),
            "alert_count": live.alert_count,
            "last_success": live.last_success.isoformat() if live.last_success else None,
        },
        "consecutive_failures": coordinator.consecutive_failures,
        "data_is_stale": coordinator.data_is_stale,
        "update_interval_seconds": (
            coordinator.update_interval.total_seconds()
            if coordinator.update_interval
            else None
        ),
    }
```

`strings` leaks nothing: string names are positions like `1.1`, not identifiers.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_diagnostics.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```powershell
git add custom_components/solaredge_ha_web_client/diagnostics.py tests/test_diagnostics.py
git commit -m "feat: add redacted diagnostics"
```

---

## Task 15: Structural guard tests

**Files:**
- Test: `tests/test_structural_guards.py`

**Interfaces:**
- Consumes: every platform module.

These tests encode decisions that are cheap to violate by accident and expensive
to discover in production. They assert on structure rather than behaviour, and
their job is to fail loudly if someone later adds a "convenient" energy sensor.

- [ ] **Step 1: Write the failing test**

`tests/test_structural_guards.py`:

```python
"""Guards for decisions that are easy to break and costly to discover late."""

from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from custom_components.solaredge_ha_web_client.sensor import (
    INVERTER_SENSORS,
    OPTIMIZER_SENSORS,
    SITE_SENSORS,
)

from .test_coordinator_live import _client
from .test_init import _setup

ALL_DESCRIPTIONS = (*OPTIMIZER_SENSORS, *INVERTER_SENSORS, *SITE_SENSORS)


def test_no_sensor_declares_the_energy_device_class() -> None:
    """The load-bearing guard.

    Cloud energy lives only in statistics. An enabled total_increasing kWh
    sensor would appear in the Energy Dashboard's solar source picker beside
    the Modbus sensor, and selecting both would silently double production
    forever. Power cannot be added as an energy source by mistake; energy can.
    """
    offenders = [
        d.key for d in ALL_DESCRIPTIONS if d.device_class == SensorDeviceClass.ENERGY
    ]
    assert offenders == []


def test_no_sensor_is_a_total_increasing_series() -> None:
    """Belt and braces: the state class that makes a sensor Energy-eligible."""
    offenders = [
        d.key
        for d in ALL_DESCRIPTIONS
        if d.state_class
        in (SensorStateClass.TOTAL, SensorStateClass.TOTAL_INCREASING)
    ]
    assert offenders == []


def test_peak_power_declares_no_classes() -> None:
    """kWp fails unit validation under device_class power."""
    peak = next(d for d in SITE_SENSORS if d.key == "peak_power")
    assert peak.device_class is None
    assert peak.state_class is None
    assert peak.native_unit_of_measurement == "kWp"


def test_cloud_duplicates_are_labelled() -> None:
    """Anything duplicating a Modbus entity must say it is the cloud copy."""
    for description in (*INVERTER_SENSORS, *SITE_SENSORS):
        if description.key.endswith("_cloud"):
            assert "(Cloud)" in (description.name or "")


def test_diagnostic_optimizer_sensors_are_disabled_by_default() -> None:
    """Twenty optimizers times five enabled sensors is unusable."""
    for description in OPTIMIZER_SENSORS:
        if description.key in ("power", "max_temperature_today"):
            assert description.entity_registry_enabled_default is not False
        else:
            assert description.entity_registry_enabled_default is False


async def test_every_entity_belongs_to_a_device(hass: HomeAssistant) -> None:
    """An orphan entity cannot be found in the UI."""
    entry = await _setup(hass, _client())
    registry = er.async_get(hass)
    rows = er.async_entries_for_config_entry(registry, entry.entry_id)

    assert rows
    assert all(row.device_id is not None for row in rows)
```

- [ ] **Step 2: Run tests**

Run: `.venv\Scripts\python.exe -m pytest tests/test_structural_guards.py -v`
Expected: 6 passed immediately — these codify choices already made. If any fail,
the implementation drifted from the spec and the implementation is what needs
fixing, not the test.

- [ ] **Step 3: Commit**

```powershell
git add tests/test_structural_guards.py
git commit -m "test: guard energy device class and entity defaults"
```

---

## Task 16: Full suite, typing and release readiness

**Files:**
- Modify: `README.md`, `custom_components/solaredge_ha_web_client/manifest.json`
- Create: `docs/migration.md`

- [ ] **Step 1: Run the whole suite with coverage**

```powershell
.venv\Scripts\python.exe -m pytest --cov=custom_components --cov-report=term-missing
```

Expected: all tests pass. Investigate any uncovered branch in `statistics.py` or
`coordinator.py` specifically; those two carry the risk.

- [ ] **Step 2: Lint and type-check**

```powershell
.venv\Scripts\python.exe -m ruff check .
.venv\Scripts\python.exe -m ruff format --check .
.venv\Scripts\python.exe -m mypy custom_components
```

Expected: clean. Do not silence a `mypy` complaint with `type: ignore` without a
comment saying what makes it safe.

- [ ] **Step 3: Write the migration guide**

`docs/migration.md`:

```markdown
# Migrating from HA core's `solaredge`

The order matters. Step 1 is a prerequisite, not a preference.

## 1. Repoint the Energy Dashboard first

Core's integration feeds the Energy Dashboard's solar source. Removing it before
repointing that source silently stops solar recording, and the gap is not
recoverable.

In **Settings → Dashboards → Energy**, set the solar production source to your
local Modbus energy sensor, then confirm in **Developer tools → Statistics**
that it is recording.

## 2. Remove the core integration

Delete the `SolarEdge` config entry in **Settings → Devices & Services**.

Core's per-module statistics stay in the recorder as orphaned series. They
remain queryable in **Developer tools → Statistics** but stop updating.

## 3. Install this integration

Add it through HACS, then configure it with your portal username, password and
site ID.

## What changes

Per-panel history restarts from the changeover. This integration keys its
statistics on panel position, where core keyed on serial, so the two sets do not
join up. That was chosen deliberately over squatting on core's statistic IDs:
position-keyed history survives an optimizer replacement, which serial-keyed
history does not.

This integration publishes no energy entities, so it cannot be selected as an
Energy Dashboard source. That is intentional — it is what makes double-counting
against your Modbus sensor impossible rather than merely unlikely.
```

- [ ] **Step 4: Link the guide from the README**

Add to `README.md` under Installation:

```markdown
## Migrating from the core SolarEdge integration

Read [docs/migration.md](docs/migration.md) before removing the core entry —
the Energy Dashboard has to be repointed first, or solar recording stops
silently.
```

- [ ] **Step 5: Commit and push for CI**

```powershell
git add README.md docs/migration.md custom_components/solaredge_ha_web_client/manifest.json
git commit -m "docs: add migration guide"
```

Create the GitHub repo and push. hassfest and the HACS action run on push and
will flag manifest or structural problems that local tests cannot see.

- [ ] **Step 6: Install and verify against the real site**

Add the repo to HACS as a custom repository, install, restart, and configure.
Then check, in order:

1. Devices show optimizers nested under the inverter under the site.
2. Each optimizer has a power sensor with a plausible daytime value.
3. `sensor.*_peak_power` reads 11.7.
4. **Developer tools → Statistics** lists `solaredge_ha_web_client:*` series
   within about an hour, with sums that only ever increase.
5. **Settings → Devices & Services → SolarEdge Web Client → Download
   diagnostics** contains no serials or site ID.
6. The Energy Dashboard's solar source is still the Modbus sensor, and this
   integration's entities do not appear in its picker.

---

## Self-Review

**Spec coverage.** Every spec section maps to a task: scope and non-goals shape
the entity tables in Tasks 11 and 12; architecture and the single coordinator are
Tasks 4, 5 and 13; the data model is Task 2; the device tree is Task 10; entities
are Tasks 11 and 12; statistics identifiers, metadata, import window and
cumulative sums are Tasks 8 and 9; config flow and reauth policy are Tasks 6 and
7; the error-handling matrix is Task 3, with the partial-success and
error-boundary requirements in Tasks 4 and 13; availability hysteresis is Task 5;
migration is Task 16; the test plan is distributed throughout with the structural
guards collected in Task 15; diagnostics redaction is Task 14.

**Two spec items are deliberately not implemented.** The spec's *Open risks*
section names quantifying the derived-versus-measured energy discrepancy via
`async_get_energy_totals()`, and its *Future scope* names the layout endpoint and
upstreaming. Both are explicitly deferred there, so neither has a task.

**Known rough edges to fix during execution.** Two places lean on assumptions
that only running the code will settle:

- Entity ID strings in the Task 11 and 12 assertions depend on the friendly
  names Home Assistant generates from device and entity names. Read the real IDs
  and correct the tests if they miss; do not rename entities to satisfy them.
- `tests/test_statistics_sums.py::test_sums_accumulate_across_hours` picks the
  written series by list position, which is fragile. Assert against the
  `statistic_id` in the captured metadata instead.

**Type consistency.** `LiveData` field and flag names are identical across
Tasks 2, 4, 11, 12 and 14. `statistic_id_for(site_id, kind, display_name)` takes
the same three arguments in Tasks 8, 9 and 13. `map_client_error(err, endpoint)`
is called identically in Tasks 4, 6 and 13. Device-info helpers keep the
`(snapshot, info, live)` signature in Tasks 10, 11 and 12. `_async_get_baselines`
and `_async_newest_statistic_time` are patched in tests at the exact module paths
where Tasks 9 and 13 define them.
