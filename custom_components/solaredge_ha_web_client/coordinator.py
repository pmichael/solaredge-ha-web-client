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
