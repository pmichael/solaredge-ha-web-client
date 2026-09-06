"""The single data update coordinator for a SolarEdge site.

The only module permitted to import from `solaredge_web`.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from http import HTTPStatus
from typing import Any

import aiohttp
from homeassistant.components.recorder.statistics import get_last_statistics
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.recorder import get_instance
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util
from solaredge_web import SolarEdgeWeb

from .const import (
    CONF_LIVE_INTERVAL,
    CONF_SITE_ID,
    DEFAULT_LIVE_INTERVAL_MINUTES,
    DOMAIN,
    LOGGER,
    MAX_CONSECUTIVE_FAILURES,
    REQUEST_SPACING_SECONDS,
    STATISTICS_INTERVAL,
)
from .models import LiveData, SiteSnapshot, build_site_snapshot
from .statistics import async_import_energy, statistic_id_for

type SolarEdgeWebConfigEntry = ConfigEntry[SolarEdgeWebCoordinator]


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


async def async_validate_login(
    hass: HomeAssistant,
    username: str,
    password: str,
    site_id: str,
) -> str | None:
    """Return a flow error key, or None when the credentials work.

    `async_get_site_information` both authenticates and proves the site is
    visible to this account, so one request validates the whole form.
    """
    client = SolarEdgeWeb(
        username=username,
        password=password,
        site_id=site_id,
        session=async_get_clientsession(hass),
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
        interval = config_entry.options.get(CONF_LIVE_INTERVAL, DEFAULT_LIVE_INTERVAL_MINUTES)
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
        self._consecutive_failures = 0
        self._last_statistics_attempt: datetime | None = None

    @property
    def consecutive_failures(self) -> int:
        """How many cycles in a row have failed outright."""
        return self._consecutive_failures

    @property
    def data_is_stale(self) -> bool:
        """True once failures have run long enough to stop trusting the data."""
        return self._consecutive_failures >= MAX_CONSECUTIVE_FAILURES

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
        except Exception as err:
            raise map_client_error(err, "site layout") from err

        self._snapshot = build_site_snapshot(
            site_id=self.site_id,
            equipment=equipment,
            site_information=site_information,
            site_components=site_components,
        )

    async def _async_update_data(self) -> LiveData:
        """Run one live cycle, tolerating partial failure."""
        try:
            live = await self._async_fetch_live()
        except ConfigEntryAuthFailed:
            # Reauth is not an outage; the user must act, and the counter
            # would otherwise be meaningless while the flow is pending.
            raise
        except ValueError:
            # Library ValueError is a caller bug, not a SolarEdge outage.
            raise
        except Exception:
            self._consecutive_failures += 1
            if self.data_is_stale:
                self.async_update_listeners()
            raise

        if not live.any_ok:
            self._consecutive_failures += 1
            if self.data_is_stale:
                self.async_update_listeners()
            raise UpdateFailed(
                f"No SolarEdge endpoint answered for site {self.site_id} "
                f"({self._consecutive_failures} consecutive failures)"
            )

        self._consecutive_failures = 0
        await self._async_maybe_import_statistics()
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
            except Exception as err:
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

    async def _async_maybe_import_statistics(self) -> None:
        """Import energy history if the interval has elapsed.

        Wrapped in its own error boundary: live data is this cycle's product
        and statistics are a side effect, so a failed history import must not
        take the live sensors down with it. A credential rejection is the one
        exception — that is not specific to statistics and the user has to act.
        """
        attempted = False
        try:
            if not await self._async_statistics_are_due():
                return

            LOGGER.debug("Importing energy statistics for site %s", self.site_id)
            attempted = True
            energy_data = await self.client.async_get_energy_data()
            self._last_statistics_attempt = dt_util.utcnow()
            await async_import_energy(
                self.hass,
                self.snapshot,
                self.config_entry.title,
                energy_data,
            )
        except ConfigEntryAuthFailed:
            raise
        except ValueError:
            # Library ValueError is a caller bug, not a soft statistics failure.
            raise
        except Exception as err:
            mapped = map_client_error(err, "energy data")
            if isinstance(mapped, ConfigEntryAuthFailed):
                raise mapped from err
            if attempted:
                self._last_statistics_attempt = dt_util.utcnow()
            LOGGER.warning("Energy statistics import failed: %s", mapped)

    async def _async_statistics_are_due(self) -> bool:
        """Whether enough time has passed since the newest stored statistic.

        Elapsed time from the recorder rather than a cycle counter: the
        recorder already knows when we last wrote, so no state needs
        persisting, and the gate stays correct across restarts and at any poll
        interval.
        """
        reference = (
            statistic_id_for(self.site_id, "opt", self.snapshot.optimizers[0].display_name)
            if self.snapshot.optimizers
            else None
        )
        if reference is None:
            return False

        now = dt_util.utcnow()
        if (
            self._last_statistics_attempt is not None
            and now - self._last_statistics_attempt < STATISTICS_INTERVAL
        ):
            return False

        newest = await _async_newest_statistic_time(self.hass, reference)
        if newest is None:
            return True
        return now - newest >= STATISTICS_INTERVAL


async def _async_newest_statistic_time(hass: HomeAssistant, statistic_id: str) -> datetime | None:
    """Return when the newest stored statistic for this ID starts."""
    rows = await get_instance(hass).async_add_executor_job(
        get_last_statistics,
        hass,
        1,
        statistic_id,
        True,  # noqa: FBT003 — convert_units is positional on HA's helper
        {"sum"},
    )
    entries = rows.get(statistic_id) if rows else None
    if not entries:
        return None
    return dt_util.utc_from_timestamp(entries[0]["start"])
