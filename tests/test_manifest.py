"""The manifest must stay consistent with the package it describes."""

import json
from pathlib import Path

from custom_components.solaredge_ha_web_client.const import DOMAIN

MANIFEST = (
    Path(__file__).parent.parent / "custom_components" / "solaredge_ha_web_client" / "manifest.json"
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
    assert requirements == ["solaredge-web==0.5.0"]
    req_file = MANIFEST.parents[2] / "requirements_test.txt"
    assert "solaredge-web==0.5.0" in req_file.read_text(encoding="utf-8")
