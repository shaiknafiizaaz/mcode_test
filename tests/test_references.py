"""Reference / labeled-value extraction tests."""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import mcode_engine  # noqa: E402


def analyze(text, section="any"):
    result = mcode_engine.analyze_lines([{"section": section, "text": text}])
    return result["entries"], result["warnings"]


def find(entries, code):
    for e in entries:
        if e["code"] == code:
            return e
    return None


def test_po_with_hash():
    entries, _ = analyze("PO #: 458921", section="consignee")
    e = find(entries, "MPO")
    assert e is not None
    assert e["value"] == "458921"
    assert e["status"] == "CONFIRMED"


def test_po_number_word():
    entries, _ = analyze("PO NUMBER 458921", section="consignee")
    assert find(entries, "MPO") is not None


def test_purchase_order():
    entries, _ = analyze("PURCHASE ORDER #: 112233", section="consignee")
    e = find(entries, "MPO")
    assert e is not None
    assert e["value"] == "112233"


def test_customer_purchase_order():
    entries, _ = analyze("CUSTOMER PURCHASE ORDER #: 4455", section="consignee")
    assert find(entries, "MPO") is not None


def test_bol_number():
    entries, _ = analyze("BOL #: 99887766")
    e = find(entries, "MBO")
    assert e is not None
    assert e["value"] == "99887766"


def test_master_bol_wins_over_bol():
    entries, _ = analyze("MASTER BOL #: 1001")
    assert find(entries, "MMCK") is not None
    assert find(entries, "MBO") is None


def test_invoice():
    entries, _ = analyze("INVOICE #: 55512")
    e = find(entries, "MNV")
    assert e is not None
    assert e["value"] == "55512"


def test_reference_number():
    entries, _ = analyze("REFERENCE #: 44771")
    assert find(entries, "MRF") is not None


def test_store_number():
    entries, _ = analyze("STORE #: 1221", section="consignee")
    e = find(entries, "MSTO")
    assert e is not None
    assert e["value"] == "1221"


def test_customer_number():
    entries, _ = analyze("CUSTOMER #: 771", section="consignee")
    assert find(entries, "MCN") is not None


def test_cust_code():
    entries, _ = analyze("CUST CODE #: 22A", section="consignee")
    assert find(entries, "MCUST") is not None


def test_pro_number_maps_to_web_pro():
    entries, _ = analyze("PRO #: 889900")
    e = find(entries, "MWR")
    assert e is not None
    assert e["value"] == "889900"


def test_order_context_shipper():
    entries, _ = analyze("ORDER #: 123", section="shipper")
    assert find(entries, "MSORD") is not None


def test_order_context_consignee():
    entries, _ = analyze("ORDER #: 456", section="consignee")
    assert find(entries, "MCORD") is not None


def test_order_no_context():
    entries, _ = analyze("ORDER #: 789", section="any")
    assert find(entries, "MORD") is not None


def test_delivery_date():
    entries, _ = analyze("DELIVERY DATE: 09/15", section="dates")
    e = find(entries, "MDELD")
    assert e is not None
    assert e["value"] == "09/15"


def test_due_date():
    entries, _ = analyze("DUE DATE: 09/15", section="dates")
    assert find(entries, "MDUE") is not None


def test_delivery_by():
    entries, _ = analyze("DELIVERY BY: 09/16", section="dates")
    assert find(entries, "MDELBY") is not None


def test_shipper_ref():
    entries, _ = analyze("SHIPPER REF #: 77521", section="shipper")
    assert find(entries, "MSHRE") is not None


def test_pickup_number():
    entries, _ = analyze("PICKUP #: 88420", section="shipper")
    assert find(entries, "MPUN") is not None


def test_shipment_number():
    entries, _ = analyze("SHIPMENT #: 998877", section="shipper")
    assert find(entries, "MSHIP") is not None


def test_serial_number():
    entries, _ = analyze("SERIAL #: SN-88")
    assert find(entries, "MSF") is not None


def test_vendor_number():
    entries, _ = analyze("VENDOR #: 7712")
    assert find(entries, "MVEND") is not None


def test_phone_label_without_hash_is_generic_phone():
    # Requirement 39 accepts generic PHONE without a hash.
    entries, _ = analyze("PHONE: 555-1234", section="special")
    assert find(entries, "MPHONE")["value"] == "555-1234"


def test_phone_with_hash_is_mpbone():
    entries, _ = analyze("PHONE #: 555-1234", section="special")
    assert find(entries, "MPHONE") is not None