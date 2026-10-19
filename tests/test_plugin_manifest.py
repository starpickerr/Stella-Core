"""Manifest validation for sample packages."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.plugins.manifest import ManifestError, load_manifest, validate_manifest


def test_sample_alpha_and_beta_load():
    for name in ("alpha", "beta"):
        manifest = load_manifest(Path("samples/plugins") / name)
        assert manifest["manifestVersion"] == 1
        assert manifest["id"].startswith("stella.sample.")


def test_rejects_missing_contribution():
    with pytest.raises(ManifestError):
        validate_manifest(
            {
                "manifestVersion": 1,
                "id": "stella.sample.bad",
                "name": "Bad",
                "version": "1.0.0",
                "hostApi": "^1.0.0",
                "contributes": {},
                "permissions": [],
            }
        )


def test_rejects_bad_plugin_id():
    with pytest.raises(ManifestError):
        validate_manifest(
            {
                "manifestVersion": 1,
                "id": "BadId",
                "name": "Bad",
                "version": "1.0.0",
                "hostApi": "^1.0.0",
                "contributes": {"tools": ["x"]},
                "permissions": [],
            }
        )
