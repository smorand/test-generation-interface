"""The shipped JSON schema must describe the tests the pipeline actually writes.

Nothing validated against this file, so it drifted: it still described bloc_id and
business_rule, fields removed with the chunk pipeline. This test is what keeps it true.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "src" / "tgi" / "schemas" / "test_schema.json"


@pytest.fixture
def schema() -> dict[str, Any]:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _a_generated_test() -> dict[str, Any]:
    """A test in the shape the generator and the coverage phase produce."""
    return {
        "id": "TEST-0101",
        "scenario_id": "SC-001",
        "name": "Synchronisation nominale",
        "description": "Valide le cas nominal",
        "requirement_refs": ["F01.EU01.CU01.EM01"],
        "steps": [{"order": 1, "description": "Une GAC est creee", "expected_result": "Elle est visible"}],
        "data_rows": [],
        "status": "draft",
        "created_at": "2026-08-09T20:22:06.527687+00:00",
        "updated_at": "2026-08-09T20:22:06.527687+00:00",
    }


def test_schema_describes_a_generated_test(schema: dict[str, Any]) -> None:
    test = _a_generated_test()
    assert set(schema["required"]) == set(test)
    assert set(schema["properties"]) >= set(test)
    assert schema["additionalProperties"] is False


def test_coverage_note_is_allowed_but_not_required(schema: dict[str, Any]) -> None:
    """Phase 3 adds it when it completes a test, so it must pass without being mandatory."""
    assert "coverage_note" in schema["properties"]
    assert "coverage_note" not in schema["required"]


def test_the_shape_matches_what_the_generator_writes(schema: dict[str, Any]) -> None:
    """Read the fields straight from the agents, so a rename in code breaks this test."""
    generator = (SCHEMA_PATH.parents[1] / "agents" / "scenario_generator.py").read_text(encoding="utf-8")
    coverage = (SCHEMA_PATH.parents[1] / "agents" / "coverage.py").read_text(encoding="utf-8")
    for field in ("scenario_id", "requirement_refs", "data_rows", "steps", "status"):
        assert f'"{field}"' in generator, field
        assert field in schema["properties"], field
    assert '"coverage_note"' in coverage


def test_the_removed_chunk_era_fields_are_gone(schema: dict[str, Any]) -> None:
    assert "bloc_id" not in schema["properties"]
    assert "business_rule" not in schema["properties"]
