"""BOL parser + full pipeline acceptance tests (including the FINAL
ACCEPTANCE TEST example from the project spec)."""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import bol_parser, mcode_engine  # noqa: E402
from engine.validation import build_result  # noqa: E402


ACCEPTANCE_BOL = """SHIP FROM:
ABC INDUSTRIES

SHIP TO:
XYZ STORES
ATTN: JOHN SMITH

PO #: 458921

HANDLING UNITS:
2 SKIDS

SPECIAL INSTRUCTIONS:
DO NOT STACK
LIFT GATE DELIVERY
CALL 24 HRS BEFORE DELIVERY
PHONE: 555-1234
"""


def run_pipeline(text):
    parsed = bol_parser.parse_text(text)
    engine_result = mcode_engine.analyze_lines(parsed["lines"])
    return build_result(parsed["lines"], engine_result, source_type="paste", input_preview=text[:200])


def codes_of(result):
    return [e["code"] for e in result["entries"]]


def find(result, code):
    for e in result["entries"]:
        if e["code"] == code:
            return e
    return None


def test_parser_sections():
    parsed = bol_parser.parse_text(ACCEPTANCE_BOL)
    sections = [ln["section"] for ln in parsed["lines"]]
    assert "consignee" in sections
    assert "handling" in sections
    assert "special" in sections


def test_acceptance_basic_mappings():
    """The six expected core results from the FINAL ACCEPTANCE TEST."""
    result = run_pipeline(ACCEPTANCE_BOL)
    codes = codes_of(result)

    assert "MM" in codes
    assert "MA" in codes
    assert "MPO" in codes
    assert "MDOUBL" in codes
    assert "MLIFT" in codes
    assert "M24" in codes

    # Values
    assert find(result, "MM")["value"] == "2 SKDS"
    assert find(result, "MA")["value"] == "JOHN SMITH"
    assert find(result, "MPO")["value"] == "458921"
    assert find(result, "M24")["value"] == "555-1234"
    # M24 must carry the detected phone number.
    assert find(result, "M24")["phone"] == "555-1234"


def test_acceptance_statuses_confirmed():
    result = run_pipeline(ACCEPTANCE_BOL)
    for code in ("MM", "MA", "MPO", "MDOUBL", "MLIFT", "M24"):
        assert find(result, code)["status"] == "CONFIRMED", code


def test_acceptance_traceability():
    """Every suggestion must explain WHY it was generated."""
    result = run_pipeline(ACCEPTANCE_BOL)
    m = find(result, "MDOUBL")
    assert m["source_text"] == "DO NOT STACK"
    assert m["matched_trigger"] == "do not stack"
    assert m["rule_source"] == "data/mcode_rules.json"
    assert m["confidence"] == "Exact Rule Match"


def test_acceptance_suggested_entries():
    """Suggested Tenet/EBS entries match the spec's expected panel."""
    result = run_pipeline(ACCEPTANCE_BOL)
    suggested = result["suggested_entries"]
    pairs = [(s["code"], s["value"]) for s in suggested]
    expected = [
        ("MM", "2 SKDS"),
        ("MA", "JOHN SMITH"),
        ("MPO", "458921"),
        ("MDOUBL", "DO NOT STACK"),
        ("MLIFT", "LIFT GATE DELIVERY"),
        ("M24", "555-1234"),
    ]
    assert pairs == expected


def test_acceptance_no_conflicts():
    result = run_pipeline(ACCEPTANCE_BOL)
    assert result["conflicts"] == []


def test_full_workflow_with_payment_and_description():
    bol = """SHIP FROM: ABC INDUSTRIES
SHIP TO: XYZ STORES
ATTN: JOHN SMITH
FREIGHT TERMS: PREPAID
PO #: 458921
HANDLING UNITS: 2 SKIDS
DESCRIPTION: AUTO PARTS
NMFC: 123456
CLASS: 70
SPECIAL INSTRUCTIONS:
DO NOT STACK
LIFT GATE DELIVERY
CALL 24 HRS BEFORE DELIVERY
PHONE: 555-1234
"""
    result = run_pipeline(bol)
    assert find(result, "MM") is not None
    assert find(result, "MA") is not None
    assert find(result, "MPO") is not None
    # Payment explicitly printed -> CONFIRMED
    assert result["payment"]["term"] == "PREPAID"
    assert result["payment"]["status"] == "CONFIRMED"
    assert result["payment"]["explicit"] is True
    # Description with NMFC + class -> CONFIRMED values found
    assert result["description"]["nmfc"] == "123456"
    assert result["description"]["class"] == "70"


def test_missing_payment_is_not_detected():
    result = run_pipeline(ACCEPTANCE_BOL)
    assert result["payment"]["status"] == "NOT DETECTED"
    assert "VERIFY" in result["payment"]["note"]


def test_mbr_missing_zip_warns():
    bol = """SHIP TO:
XYZ STORES
123 MAIN ST
ANYTOWN
"""
    result = run_pipeline(bol)
    assert find(result, "MBR") is not None
    assert find(result, "MBR")["status"] == "VERIFY"


def test_mbr_no_false_positive_with_zip():
    bol = """SHIP TO:
XYZ STORES
123 MAIN ST
ANYTOWN OH 12345
"""
    result = run_pipeline(bol)
    assert find(result, "MBR") is None


def test_mbr_no_false_positive_without_address():
    # Company name only, no street address -> no MBR.
    result = run_pipeline(ACCEPTANCE_BOL)
    assert find(result, "MBR") is None