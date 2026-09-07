"""MM handling-unit engine tests.

MM = PALLET / MASTER HANDLING UNIT INFORMATION.
MM is NOT NMFC - NMFC values must never become MM entries.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.handling_units import analyze_handling_units  # noqa: E402


def test_one_pallet():
    e = analyze_handling_units("1 PALLET")
    assert e is not None
    assert e["code"] == "MM"
    assert e["value"] == "1 PLT"


def test_two_pallets():
    e = analyze_handling_units("2 PALLETS")
    assert e is not None
    assert e["value"] == "2 PLTS"


def test_one_skid():
    e = analyze_handling_units("1 SKID")
    assert e is not None
    assert e["value"] == "1 SKD"


def test_three_skids():
    e = analyze_handling_units("3 SKIDS")
    assert e is not None
    assert e["value"] == "3 SKDS"


def test_plt_abbreviation():
    e = analyze_handling_units("4 PLTS")
    assert e is not None
    assert e["value"] == "4 PLTS"


def test_skd_abbreviation():
    e = analyze_handling_units("2 SKDS")
    assert e is not None
    assert e["value"] == "2 SKDS"


def test_word_number():
    e = analyze_handling_units("TWO SKIDS")
    assert e is not None
    assert e["value"] == "2 SKDS"


def test_nmfc_never_mm():
    assert analyze_handling_units("NMFC 123456") is None
    assert analyze_handling_units("NMFC # 123456") is None


def test_bare_pallet_no_count():
    assert analyze_handling_units("PALLET") is None
    assert analyze_handling_units("PALLETS") is None


def test_do_not_stack_has_no_count():
    assert analyze_handling_units("DO NOT STACK") is None


def test_pallet_jack_not_mm():
    assert analyze_handling_units("MUST HAVE PALLET JACK") is None