"""
tests/test_parser.py — Unit tests for parser.py using a hardcoded mock Java string.
No Neo4j. No I/O.
"""
import pytest
from ingestion.parser import parse_java_source
from ingestion.models import ClassData, MethodData

MOCK_JAVA = """
package com.amrit.api.controller;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/patient")
public class PatientController {

    @Autowired
    private PatientService patientService;

    @PostMapping("/register")
    public ResponseEntity<Patient> registerPatient(@RequestBody Patient patient) {
        Patient saved = patientService.register(patient);
        return ResponseEntity.ok(saved);
    }

    @GetMapping("/find")
    public ResponseEntity<Patient> findPatient(@RequestParam String id) {
        Patient found = patientService.find(id);
        return ResponseEntity.ok(found);
    }
}
"""

MOCK_FILE_PATH = "/fake/repo/PatientController.java"


@pytest.fixture
def parsed() -> ClassData:
    return parse_java_source(MOCK_JAVA, MOCK_FILE_PATH)


# ── Class-level assertions ─────────────────────────────────────────────────

def test_class_name(parsed: ClassData) -> None:
    assert parsed.name == "PatientController"


def test_file_path(parsed: ClassData) -> None:
    assert parsed.file_path == MOCK_FILE_PATH


def test_stereotype_is_rest_controller(parsed: ClassData) -> None:
    assert parsed.stereotype == "RestController"


def test_autowired_deps(parsed: ClassData) -> None:
    assert "PatientService" in parsed.autowired_deps


# ── Method-level assertions ────────────────────────────────────────────────

def test_two_methods_extracted(parsed: ClassData) -> None:
    assert len(parsed.methods) == 2


def test_post_mapping_method(parsed: ClassData) -> None:
    post_method = next(
        (m for m in parsed.methods if m.http_method == "PostMapping"), None
    )
    assert post_method is not None, "No PostMapping method found"
    assert post_method.name == "registerPatient"
    assert post_method.endpoint == "/register"
    assert "patientService.register" in post_method.source_code


def test_get_mapping_method(parsed: ClassData) -> None:
    get_method = next(
        (m for m in parsed.methods if m.http_method == "GetMapping"), None
    )
    assert get_method is not None, "No GetMapping method found"
    assert get_method.name == "findPatient"
    assert get_method.endpoint == "/find"
    assert "patientService.find" in get_method.source_code


def test_source_code_non_empty(parsed: ClassData) -> None:
    for method in parsed.methods:
        assert method.source_code.strip(), f"Empty source_code for {method.name}"


def test_method_names_match_expected(parsed: ClassData) -> None:
    names = {m.name for m in parsed.methods}
    assert names == {"registerPatient", "findPatient"}