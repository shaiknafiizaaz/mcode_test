"""MM Handling-Unit Engine.

MM = PALLET / MASTER HANDLING UNIT INFORMATION.
MM is NOT NMFC. This module keeps MM logic strictly separate from
NMFC (National Motor Freight Classification) processing.

Example mappings:
    1 PALLET   -> MM 1 PLT
    2 PALLETS  -> MM 2 PLTS
    1 SKID     -> MM 1 SKD
    3 SKIDS    -> MM 3 SKDS

NEVER convert an NMFC value into an MM entry: an MM entry is only
produced when a count is followed by a recognized pallet/skid term.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional

# (regex, singular abbreviation, plural abbreviation)
_PATTERNS = [
    (re.compile(r"\b(\d{1,3})\s*(?:pallet|pallets|plt|plts|pal)\b", re.IGNORECASE), "PLT", "PLTS"),
    (re.compile(r"\b(\d{1,3})\s*(?:skid|skids|skd|skds)\b", re.IGNORECASE), "SKD", "SKDS"),
]

# Written-out numbers that sometimes appear on BOLs ("TWO SKIDS").
_WORD_NUMBERS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}
_WORD_PATTERNS = [
    (re.compile(r"\b(one|two|three|four|five|six|seven|eight|nine|ten)\s*(?:pallet|pallets|plt|plts)\b", re.IGNORECASE), "PLT", "PLTS"),
    (re.compile(r"\b(one|two|three|four|five|six|seven|eight|nine|ten)\s*(?:skid|skids|skd|skds)\b", re.IGNORECASE), "SKD", "SKDS"),
]

_BARE_UNIT = re.compile(r"\b(?:pallet|pallets|plt|plts|skid|skids|skd|skds)\b", re.IGNORECASE)

RULE_SOURCE = "engine/handling_units.py (MM = pallet / master handling unit information; MM is NOT NMFC)"


def _abbrev(count: int, singular: str, plural: str) -> str:
    return singular if count == 1 else plural


def analyze_handling_units(line: str) -> Optional[Dict[str, object]]:
    """Analyze a single line for handling-unit information.

    Returns an MM entry dict or None. An entry is only produced when a
    count + pallet/skid term is present; a bare "NMFC 123456" line can
    never produce an MM entry because it has no pallet/skid term.
    """
    if not line:
        return None

    for pattern, singular, plural in _PATTERNS:
        m = pattern.search(line)
        if m:
            count = int(m.group(1))
            return _make_entry(count, _abbrev(count, singular, plural), line, m.group(0))
    for pattern, singular, plural in _WORD_PATTERNS:
        m = pattern.search(line)
        if m:
            count = _WORD_NUMBERS[m.group(1).lower()]
            return _make_entry(count, _abbrev(count, singular, plural), line, m.group(0))

    return None


def _make_entry(count: int, abbrev: str, source_text: str, matched_text: str) -> Dict[str, object]:
    return {
        "code": "MM",
        "meaning": "Handling Units - Pallet / Master Handling Unit Information (MM is NOT NMFC)",
        "category": "Handling Units",
        "value": f"{count} {abbrev}",
        "source_text": source_text.strip(),
        "matched_trigger": matched_text,
        "rule_source": RULE_SOURCE,
        "confidence": "Exact Rule Match",
        "status": "CONFIRMED",
    }


def has_bare_handling_unit(line: str) -> bool:
    """True when a pallet/skid term appears WITHOUT a count.

    Used to raise a VERIFY warning (count missing) rather than guessing.
    """
    return bool(_BARE_UNIT.search(line))