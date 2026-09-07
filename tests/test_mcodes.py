"""Core M-Code rule engine tests (deterministic, no guessing)."""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import mcode_engine  # noqa: E402


def analyze(text, section="any"):
    result = mcode_engine.analyze_lines([{"section": section, "text": text}])
    return result["entries"], result["warnings"]


def codes_of(entries):
    return [e["code"] for e in entries]


def find(entries, code):
    for e in entries:
        if e["code"] == code:
            return e
    return None


# ---------------------------------------------------------------- confirmed

def test_do_not_stack():
    entries, _ = analyze("DO NOT STACK")
    assert "MDOUBL" in codes_of(entries)


def test_stackable_no():
    entries, _ = analyze("STACKABLE - NO")
    assert "MDOUBL" in codes_of(entries)


def test_lift_gate_delivery():
    entries, _ = analyze("LIFT GATE DELIVERY")
    e = find(entries, "MLIFT")
    assert e is not None
    assert e["status"] == "CONFIRMED"


def test_lift_gate_pickup():
    entries, _ = analyze("LIFT GATE PICKUP")
    assert "LIFTP" in codes_of(entries)
    assert "MLIFT" not in codes_of(entries)


def test_residential_delivery():
    entries, _ = analyze("RESIDENTIAL DELIVERY")
    assert "RC" in codes_of(entries)


def test_residential_pickup():
    entries, _ = analyze("RESIDENTIAL PICKUP")
    assert "RPU" in codes_of(entries)


def test_inside_pickup():
    entries, _ = analyze("INSIDE PICKUP")
    assert "IPU" in codes_of(entries)


def test_inside_delivery():
    entries, _ = analyze("INSIDE DELIVERY")
    assert "ID" in codes_of(entries)


def test_po_number():
    entries, _ = analyze("PO # 12345", section="consignee")
    e = find(entries, "MPO")
    assert e is not None
    assert e["value"] == "12345"


def test_attn_person():
    entries, _ = analyze("ATTN JOHN SMITH", section="consignee")
    e = find(entries, "MA")
    assert e is not None
    assert e["value"] == "JOHN SMITH"
    assert e["status"] == "CONFIRMED"


def test_urgent():
    entries, _ = analyze("URGENT")
    assert "MR" in codes_of(entries)


def test_protect_from_freezing():
    entries, _ = analyze("PROTECT FROM FREEZING")
    assert "MPFF" in codes_of(entries)


def test_do_not_remove_from_pallet():
    entries, _ = analyze("DO NOT REMOVE FROM PALLET")
    assert "MDONOT" in codes_of(entries)


def test_shipper_load_and_count():
    entries, _ = analyze("SHIPPER LOAD AND COUNT")
    assert "MSLC" in codes_of(entries)


def test_tail_gate_delivery():
    entries, _ = analyze("TAIL GATE DELIVERY")
    assert "MTAIL" in codes_of(entries)


def test_pallet_jack():
    entries, _ = analyze("MUST HAVE PALLET JACK", section="delivery")
    assert "MPL" in codes_of(entries)


def test_do_not_top_load():
    entries, _ = analyze("DO NOT TOP LOAD")
    assert "MDONT" in codes_of(entries)


# ---------------------------------------------------------------- negatives

def test_nmfc_never_becomes_mm():
    entries, _ = analyze("NMFC 123456", section="description")
    assert "MM" not in codes_of(entries)
    # The NMFC number must not leak into any code value either.
    for e in entries:
        assert "123456" not in str(e.get("value", ""))


def test_parts_department_never_becomes_ma():
    entries, _ = analyze("PARTS DEPARTMENT", section="consignee")
    assert "MA" not in codes_of(entries)


def test_attn_department_never_becomes_ma():
    entries, warnings = analyze("ATTN: PARTS DEPARTMENT", section="consignee")
    assert "MA" not in codes_of(entries)
    assert any("department" in w.lower() for w in warnings)


def test_receiving_shipping_departments_not_ma():
    for dept in ("RECEIVING", "SHIPPING DEPARTMENT", "WAREHOUSE"):
        entries, _ = analyze(f"ATTN: {dept}", section="consignee")
        assert "MA" not in codes_of(entries), dept


def test_pallet_jack_is_not_handling_unit():
    # "PALLET JACK" must not produce an MM entry (no count + pallet term).
    entries, _ = analyze("MUST HAVE PALLET JACK TO DELIVERY")
    assert "MM" not in codes_of(entries)


def test_po_box_not_po():
    entries, _ = analyze("P.O. BOX 4410", section="consignee")
    assert "MPO" not in codes_of(entries)


def test_ambiguous_call_warns_without_guessing():
    entries, warnings = analyze("CALL 555-1234", section="special")
    assert any("ambig" in w.lower() for w in warnings)
    # No appointment/call-before code may be invented from bare "call".
    assert not any(c in codes_of(entries) for c in ("MCA", "MCFA", "MCALLB", "MBEFOR", "M24"))


def test_customer_service_not_customer_number():
    entries, _ = analyze("CUSTOMER SERVICE", section="consignee")
    assert "MCN" not in codes_of(entries)


def test_no_mcode_invented_for_unknown_text():
    entries, _ = analyze("QWERTY UNKNOWN FREIGHT LINE", section="any")
    assert entries == [] or all(e["status"] != "CONFIRMED" for e in entries)