"""Appointment vs call-before logic tests (critical distinction).

APPOINTMENT = scheduling/arranging delivery.
CALL-BEFORE = notification prior to delivery.
Phone presence and time-specific rules affect the code chosen.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import mcode_engine  # noqa: E402


def analyze_lines(lines):
    result = mcode_engine.analyze_lines(lines)
    return result["entries"], result["warnings"], result["conflicts"]


def codes_of(entries):
    return [e["code"] for e in entries]


def test_call_for_appointment_with_phone():
    entries, _, _ = analyze_lines([
        {"section": "special", "text": "CALL FOR APPOINTMENT"},
        {"section": "special", "text": "PHONE: 555-0100"},
    ])
    assert "MCA" in codes_of(entries)
    assert "MCFA" not in codes_of(entries)


def test_call_for_appointment_without_phone():
    entries, _, _ = analyze_lines([
        {"section": "special", "text": "CALL FOR APPOINTMENT"},
    ])
    assert "MCFA" in codes_of(entries)
    assert "MCA" not in codes_of(entries)


def test_call_before_with_phone():
    entries, _, _ = analyze_lines([
        {"section": "special", "text": "CALL BEFORE DELIVERY"},
        {"section": "special", "text": "PHONE: 555-0100"},
    ])
    assert "MCALLB" in codes_of(entries)
    assert "MBEFOR" not in codes_of(entries)


def test_call_before_without_phone():
    entries, _, _ = analyze_lines([
        {"section": "special", "text": "CALL BEFORE DELIVERY"},
    ])
    assert "MBEFOR" in codes_of(entries)
    assert "MCALLB" not in codes_of(entries)


def test_call_24_hrs_before_with_phone():
    entries, _, _ = analyze_lines([
        {"section": "special", "text": "CALL 24 HRS BEFORE DELIVERY"},
        {"section": "special", "text": "PHONE: 555-1234"},
    ])
    assert "M24" in codes_of(entries)
    # Time-specific rule takes precedence over generic MCALLB/MBEFOR.
    assert "MCALLB" not in codes_of(entries)
    assert "MBEFOR" not in codes_of(entries)


def test_call_24_hrs_before_without_phone_warns():
    entries, warnings, _ = analyze_lines([
        {"section": "special", "text": "CALL 24 HRS BEFORE DELIVERY"},
    ])
    assert "M24" in codes_of(entries)
    assert any("phone number" in w.lower() for w in warnings)


def test_call_for_appointment_48_hrs_before():
    entries, _, _ = analyze_lines([
        {"section": "special", "text": "CALL FOR APPOINTMENT 48 HRS BEFORE DELIVERY"},
    ])
    assert "M48" in codes_of(entries)


def test_call_for_appointment_72_hrs_before():
    entries, _, _ = analyze_lines([
        {"section": "special", "text": "CALL FOR APPOINTMENT 72 HOURS BEFORE DELIVERY"},
    ])
    assert "M72A" in codes_of(entries)


def test_call_for_appointment_24_hrs_before():
    entries, _, _ = analyze_lines([
        {"section": "special", "text": "CALL FOR APPOINTMENT 24 HRS BEFORE DELIVERY"},
    ])
    assert "MADV" in codes_of(entries)


def test_call_1_hour_before():
    entries, _, _ = analyze_lines([
        {"section": "special", "text": "CALL 1 HOUR BEFORE DELIVERY"},
    ])
    assert "M1HO" in codes_of(entries)


def test_call_2_hours_before():
    entries, _, _ = analyze_lines([
        {"section": "special", "text": "CALL 2 HOURS BEFORE DELIVERY"},
    ])
    assert "M2B4" in codes_of(entries)


def test_notify_prior_to_delivery():
    entries, _, _ = analyze_lines([
        {"section": "special", "text": "NOTIFY PRIOR TO DELIVERY"},
    ])
    assert "MNOTI" in codes_of(entries)


def test_no_appointment_necessary():
    entries, _, _ = analyze_lines([
        {"section": "special", "text": "NO APPOINTMENT NECESSARY"},
    ])
    assert "MNDA" in codes_of(entries)


def test_appointment_vs_no_appointment_conflict():
    entries, _, conflicts = analyze_lines([
        {"section": "special", "text": "CALL FOR APPOINTMENT 555-0100"},
        {"section": "special", "text": "NO APPOINTMENT NECESSARY"},
    ])
    assert "MCA" in codes_of(entries)
    assert "MNDA" in codes_of(entries)
    assert len(conflicts) == 1
    assert conflicts[0]["type"] == "appointment"


def test_call_prior_to_delivery():
    entries, _, _ = analyze_lines([
        {"section": "special", "text": "CALL PRIOR TO DELIVERY 555-0100"},
    ])
    assert "MCALLB" in codes_of(entries)


def test_schedule_delivery_is_appointment():
    entries, _, _ = analyze_lines([
        {"section": "special", "text": "SCHEDULE DELIVERY"},
    ])
    assert "MCFA" in codes_of(entries)


def test_arrange_delivery_is_appointment():
    entries, _, _ = analyze_lines([
        {"section": "special", "text": "PLEASE ARRANGE DELIVERY"},
    ])
    assert "MCFA" in codes_of(entries)