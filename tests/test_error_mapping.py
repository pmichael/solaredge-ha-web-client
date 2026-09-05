"""Exception mapping. Type, never message text."""

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
    result = map_client_error(TimeoutError(), "optimizer data")
    assert isinstance(result, UpdateFailed)


def test_endpoint_name_reaches_the_message() -> None:
    """Without the endpoint, a log line cannot say what actually failed."""
    result = map_client_error(aiohttp.ClientError("boom"), "inverter data")
    assert "inverter data" in str(result)


def test_value_error_is_not_mapped() -> None:
    """A ValueError is our bug. Swallowing it would hide it forever."""
    with pytest.raises(ValueError, match="bad resolution"):
        map_client_error(ValueError("bad resolution"), "energy data")
