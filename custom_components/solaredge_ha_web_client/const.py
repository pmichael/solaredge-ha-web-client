"""Constants for the SolarEdge Web Client integration."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Final

DOMAIN: Final = "solaredge_ha_web_client"
LOGGER: Final = logging.getLogger(__package__)

# String values match homeassistant.const.Platform. Avoid importing HA here so
# manifest unit tests can run without the full Core test harness.
PLATFORMS: Final = ["binary_sensor", "sensor"]

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
