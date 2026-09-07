"""Description engine.

Represents the Tenet/EBS training priority for a freight line:

    FLUSH
      -> NMFC / ITEM
      -> CLASS
      -> R LINE
      -> RDG

The engine NEVER invents FLUSH matches, NMFC values, classes, R-lines
or RDG entries. If the source information is insufficient the result is:

    DESCRIPTION:  VERIFY / INSUFFICIENT INFORMATION
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional

from .rules_loader import load_rules, normalize

RULE_SOURCE = "data/description_rules.json"

_NMFC_RE = re.compile(r"\bnmfc\s*(?:#|no\.?|number)?\s*:?\s*(\d{3,7})\b", re.IGNORECASE)
_CLASS_RE = re.compile(r"\bclass\s*(?:#|no\.?|number)?\s*:?\s*([0-9]{2,3}(?:\.[0-9])?)\b", re.IGNORECASE)
_FLUSH_RE = re.compile(r"\bflush\b", re.IGNORECASE)
_R_LINE_RE = re.compile(r"\br[- ]?line\b", re.IGNORECASE)
_RDG_RE = re.compile(r"\brdg\b", re.IGNORECASE)


def analyze_description(lines: List[Dict[str, str]]) -> Dict[str, object]:
    """Analyze parsed description-section lines.

    lines: list of {"section": ..., "text": ...} (description section).
    """
    desc_text = " ".join(normalize(entry.get("text", "")) for entry in lines).strip()

    result: Dict[str, object] = {
        "flush": False,
        "nmfc": None,
        "class": None,
        "r_line": None,
        "rdg": None,
        "status": "NOT DETECTED",
        "note": "",
        "rule_source": RULE_SOURCE,
        "source_text": None,
    }
    if not desc_text:
        result["note"] = "No description text on this BOL. Description processing: VERIFY / INSUFFICIENT INFORMATION."
        return result

    result["source_text"] = desc_text

    if _FLUSH_RE.search(desc_text):
        result["flush"] = True
    nmfc_m = _NMFC_RE.search(desc_text)
    if nmfc_m:
        result["nmfc"] = nmfc_m.group(1)
    class_m = _CLASS_RE.search(desc_text)
    if class_m:
        result["class"] = class_m.group(1)
    if _R_LINE_RE.search(desc_text):
        result["r_line"] = True
    if _RDG_RE.search(desc_text):
        result["rdg"] = True

    # Status determination - never invent values.
    if result["nmfc"] and result["class"]:
        result["status"] = "CONFIRMED"
        result["note"] = (
            f"NMFC {result['nmfc']} with class {result['class']} found. "
            "FLUSH / R-LINE / RDG handling must be confirmed with trainer before entry."
        )
    elif result["nmfc"] or result["class"]:
        result["status"] = "VERIFY"
        result["note"] = (
            "Description contains partial NMFC/class information. "
            "VERIFY / INSUFFICIENT INFORMATION - do not guess the missing value."
        )
    else:
        result["status"] = "NOT DETECTED"
        result["note"] = "DESCRIPTION: VERIFY / INSUFFICIENT INFORMATION - no NMFC or class value present to process deterministically."

    if result["flush"]:
        result["note"] += " FLUSH keyword present - confirm FLUSH designation with trainer."

    return result