"""BOL text parser.

Splits pasted BOL text (or structured manual-entry fields) into
section-aware lines of the form {"section": str, "text": str}.

Full lines are preserved (labels stay intact so the reference engine can
extract values). Sections provide context for direction-sensitive codes:
    LIFT GATE PICKUP -> LIFTP     LIFT GATE DELIVERY -> MLIFT
    RESIDENTIAL PICKUP -> RPU     RESIDENTIAL DELIVERY -> RC
    ORDER # in shipper section -> MSORD (Our Order #)
    ORDER # in consignee section -> MCORD (Your Order #)
"""
from __future__ import annotations

import re
from typing import Dict, List

# Structural headers switch the current section.
# (label, section, follow) - follow=True accepts content after the label
# ("NMFC: 123456", "CLASS 70", "SHIP FROM: ABC"); follow=False requires
# a bare header or "LABEL:" so that e.g. "SHIPPER LOAD AND COUNT" is
# NOT treated as a shipper section header.
_STRUCTURAL = [
    ("ship from", "shipper", True),
    ("shipper", "shipper", False),
    ("ship to", "consignee", True),
    ("consignee", "consignee", False),
    ("bill to", "billto", True),
    ("freight terms", "freight", True),
    ("payment", "freight", False),
    ("special instructions", "special", True),
    ("handling units", "handling", True),
    ("pieces", "pieces", True),
    ("weight", "weight", True),
    ("description", "description", True),
    ("nmfc", "description", True),
    ("class", "description", True),
    ("references", "references", False),
    ("reference", "references", False),
    ("contact", "contact", False),
    ("pickup instructions", "pickup", True),
    ("delivery instructions", "delivery", True),
    ("delivery date", "dates", True),
    ("dates", "dates", False),
    ("appointment", "special", False),
    ("call before", "special", False),
    ("notify", "special", False),
]

# Labeled value lines stay in the current section (context preserved).
_ANY_TYPE = [
    "pro", "po", "purchase order", "cust po", "shipment", "store", "suite",
    "customer", "cust", "bol", "bill of lading", "master bol", "invoice",
    "order", "our order", "your order", "ref", "job", "load",
    "booking", "quote", "quotation", "account", "serial", "vendor",
    "release", "pickup", "delivery", "sid", "cid", "duns", "wwe",
    "manifest", "confirmation", "document", "ticket", "code", "gl",
    "general ledger", "packing list", "packing slip", "pick ticket",
    "aff dispatch", "due date", "arrival", "scheduled delivery",
    "delivery by", "date requested", "delivery between", "phone", "tel",
    "telephone", "email", "dimensions", "receiving hours", "delivery hours",
    "dock hours", "attn", "attention",
]


def _starts_with_label(low: str, label: str, follow: bool) -> bool:
    if low == label:
        return True
    if low.startswith(label + ":"):
        return True
    if follow:
        return low.startswith(label + " ") or low.startswith(label + "#") or low.startswith(label + "-")
    return False


def parse_text(raw_text: str) -> Dict[str, object]:
    """Parse pasted BOL text into section-aware lines."""
    lines: List[Dict[str, str]] = []
    section = "any"
    for raw_line in raw_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        low = line.lower()

        # Structural headers first (order matters: "delivery instructions"
        # must win over "delivery date", "delivery", etc.).
        header_section = None
        for label, sec, follow in _STRUCTURAL:
            if _starts_with_label(low, label, follow):
                header_section = sec
                break
        if header_section:
            section = header_section
            lines.append({"section": section, "text": line})
            continue

        # Any-type labeled value lines keep the current section context.
        matched_any = False
        for label in _ANY_TYPE:
            if _starts_with_label(low, label, True):
                matched_any = True
                break
        if matched_any:
            lines.append({"section": section, "text": line})
            continue

        lines.append({"section": section, "text": line})

    return {
        "lines": lines,
        "raw_text": raw_text,
    }


def lines_from_fields(fields: Dict[str, str]) -> List[Dict[str, str]]:
    """Build engine-ready lines from structured manual-entry fields."""
    lines: List[Dict[str, str]] = []
    g = fields.get

    def add(section: str, text: str) -> None:
        text = (text or "").strip()
        if text:
            lines.append({"section": section, "text": text})

    def add_multi(section: str, text: str) -> None:
        for ln in (text or "").splitlines():
            add(section, ln)

    add("shipper", g("shipper"))
    add("consignee", g("consignee"))
    if g("attn"):
        add("consignee", f"ATTN: {g('attn')}")
    add("billto", g("bill_to"))
    add("freight", g("freight_terms"))
    if g("pro_number"):
        add("any", f"PRO #: {g('pro_number')}")
    add_multi("handling", g("handling_units"))
    add("pieces", g("pieces"))
    add("weight", g("weight"))
    add_multi("description", g("description"))
    if g("nmfc"):
        add("description", f"NMFC: {g('nmfc')}")
    if g("class"):
        add("description", f"CLASS: {g('class')}")
    add_multi("references", g("references"))
    add_multi("special", g("special_instructions"))
    add_multi("contact", g("contact_information"))
    add_multi("pickup", g("pickup_instructions"))
    add_multi("delivery", g("delivery_instructions"))
    return lines