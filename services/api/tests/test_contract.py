"""M9-01 kontrak: setiap endpoint di docs/API_SPEC.yaml ada di server dan sebaliknya."""

import re
from pathlib import Path

import yaml

from app.main import app

SPEC = Path(__file__).resolve().parents[3] / "docs" / "API_SPEC.yaml"
METHODS = {"get", "post", "put", "patch", "delete"}
# Halaman HTML tanpa login (include_in_schema=False), tetap didokumentasikan di spec.
HIDDEN = {("GET", "/ops/probe")}


def _routes(paths: dict[str, dict[str, object]]) -> set[tuple[str, str]]:
    return {
        (m.upper(), re.sub(r"\{[^}]+\}", "{}", p.removeprefix("/api/v1")))
        for p, ops in paths.items()
        for m in ops
        if m in METHODS
    }


def test_spec_matches_server_routes() -> None:
    spec = _routes(yaml.safe_load(SPEC.read_text())["paths"])
    server = _routes(app.openapi()["paths"]) | HIDDEN
    assert spec - server == set(), "di spec tapi tidak ada di server"
    assert server - spec == set(), "di server tapi belum didokumentasikan di spec"
