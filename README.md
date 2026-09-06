# SolarEdge Web Client

Per-optimizer SolarEdge data for Home Assistant, read from the SolarEdge
monitoring portal with your normal portal username and password. No API key,
and nothing to configure before the V1 API retires.

## What it provides

- Power and today's peak temperature for every optimizer
- Module and optimizer voltage, current and last-measurement time as diagnostics
- Site alert status and per-inverter running state
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
