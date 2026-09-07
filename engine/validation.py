"""Validation and result assembly.

Every result entry carries one of:
    CONFIRMED   (green) - deterministic rule matched with required data
    VERIFY      (orange) - matched but something must be double-checked
    NOT DETECTED (gray) - nothing was found for the category
    CONFLICT    (red)   - contradictory instructions both present

Also builds the copy-friendly "Suggested Tenet/EBS Entries" panel.
"""
from __future__ import annotations

import re
from typing import Dict, List

from .description_engine import analyze_description
from .payment_engine import analyze_payment
from .rules_loader import get_code_map, role_code, normalize

STATUS_COLORS = {
    "CONFIRMED": "green",
    "VERIFY": "orange",
    "NOT DETECTED": "gray",
    "CONFLICT": "red",
}

# Suggested-entry ordering used by the Tenet/EBS copy panel.
# Explicit code-level rank so that e.g. MLIFT (a delivery service) sorts
# with services rather than with consignee contact codes (MA).
_CODE_RANK = {code: rule['display_rank'] for code, rule in get_code_map().items()}

_CODE_RANK['MM'] = 1  # Separate handling-unit engine.

_STREET_RE = re.compile(
    r"\b\d{1,5}\s+(?:[A-Za-z]+\s+)?(?:st\.?|ave\.?|rd\.?|blvd\.?|dr\.?|"
    r"ln\.?|way|court|ct\.?|road|street|boulevard|drive|lane|highway|hwy)\b"
    r"|\bpo\s*box\s*\d+\b",
    re.IGNORECASE,
)
_ZIP_RE = re.compile(r"\b\d{5}(?:-\d{4})?\b")

MBR_RULE_SOURCE = "engine/validation.py (MBR: missing consignee address information - requires trainer verification)"


def _mb_check(lines: List[Dict[str, str]]) -> List[Dict[str, object]]:
    """MBR: consignee has a street address but no ZIP/postal code."""
    consignee_lines = [ln["text"] for ln in lines if ln.get("section") == "consignee"]
    if not consignee_lines:
        return []
    block = " ".join(consignee_lines)
    has_street = bool(_STREET_RE.search(block))
    has_zip = bool(_ZIP_RE.search(block))
    if has_street and not has_zip:
        entry = {
            **{key: get_code_map()[role_code('missing_address')][key] for key in ('code', 'meaning', 'category')},
            "value": "",
            "source_text": block[:200],
            "matched_trigger": "street address without ZIP/postal code detected",
            "rule_source": MBR_RULE_SOURCE,
            "confidence": "Pattern Match - Verify",
            "status": "VERIFY",
            "section": "consignee",
            "note": "Consignee street address present but no ZIP/postal code detected. "
                    "VERIFY against the original BOL before entering MBR.",
        }
        return [entry]
    return []


def _category_of(entry: Dict[str, object]) -> str:
    return str(entry.get("category", ""))


def build_result(
    lines: List[Dict[str, str]],
    engine: Dict[str, object],
    source_type: str = "paste",
    input_preview: str = "",
) -> Dict[str, object]:
    """Assemble the complete analysis result shown in the UI."""
    entries: List[Dict[str, object]] = list(engine.get("entries", []))
    warnings: List[str] = list(engine.get("warnings", []))
    conflicts: List[Dict[str, object]] = list(engine.get("conflicts", []))

    # MBR (missing consignee address information).
    entries.extend(_mb_check(lines))

    # Payment.
    payment = analyze_payment(lines)

    # Description.
    desc_lines = [ln for ln in lines if ln.get("section") == "description"]
    description = analyze_description(desc_lines)

    # Annotate entries with display status/colors.
    for entry in entries:
        status = str(entry.get("status", "VERIFY"))
        entry["status"] = status
        entry["status_color"] = STATUS_COLORS.get(status, "orange")
        entry["category_rank"] = _CODE_RANK.get(str(entry.get("code", "")), 9)
        if source_type == "image" and "note" not in entry:
            entry["note"] = "Extracted from image - verify against the original BOL."

    # Order entries for display: rank, then detection order.
    entries.sort(key=lambda e: (e.get("category_rank", 9), 0))

    # Suggested Tenet/EBS entries (copy-friendly).
    suggested = []
    seen_suggested = set()
    for entry in entries:
        code = str(entry.get("code", ""))
        value = str(entry.get("value", "") or "").strip()
        if not value or entry.get("status") == "CONFLICT":
            continue
        key = (code, normalize(value))
        if key in seen_suggested:
            continue
        seen_suggested.add(key)
        suggested.append({
            "code": code,
            "value": value,
            "status": entry.get("status", "VERIFY"),
            "status_color": entry.get("status_color", "orange"),
        })

    # Summary of detected categories.
    detected_categories = sorted({
        _category_of(e) for e in entries if e.get("status") == "CONFIRMED" and _category_of(e)
    })

    # NOT DETECTED summary rows (payment/description shown in their panels).
    not_detected = []
    if payment["status"] == "NOT DETECTED":
        not_detected.append({
            "label": "Payment",
            "status": "NOT DETECTED",
            "note": payment["note"],
        })
    if description["status"] in ("NOT DETECTED", "VERIFY"):
        not_detected.append({
            "label": "Description / NMFC / Class",
            "status": description["status"],
            "note": description["note"],
        })

    return {
        "source_type": source_type,
        "input_preview": input_preview,
        "entries": entries,
        "warnings": warnings,
        "conflicts": conflicts,
        "payment": payment,
        "description": description,
        "suggested_entries": suggested,
        "detected_categories": detected_categories,
        "not_detected": not_detected,
        "summary": {
            "total_entries": len(entries),
            "confirmed": sum(1 for e in entries if e.get("status") == "CONFIRMED"),
            "verify": sum(1 for e in entries if e.get("status") == "VERIFY"),
            "conflicts": len(conflicts),
        },
    }