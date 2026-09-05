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
