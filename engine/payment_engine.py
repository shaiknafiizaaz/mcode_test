"""Payment engine.

Only EXPLICITLY printed payment terms become CONFIRMED:
    PREPAID, COLLECT, THIRD PARTY, FREE ASTRAY.

If no explicit term is found the result is NOT DETECTED and the UI must
show "VERIFY WITH TRAINER". The UI clearly distinguishes an explicitly
printed term from an inferred one - inferred payment is never presented
as certain (currently inference is never performed).
"""
from __future__ import annotations

import json
from typing import Dict, List, Optional

from .rules_loader import load_rules, normalize

RULE_SOURCE = "data/payment_rules.json"


def _load_terms() -> List[Dict[str, object]]:
    return load_rules("payment")["explicit_terms"]


def analyze_payment(lines: List[Dict[str, str]]) -> Dict[str, object]:
    """Analyze parsed lines for an explicitly printed payment term.

    lines: list of {"section": ..., "text": ...}
    """
    terms = _load_terms()
    for entry in lines:
        text = normalize(entry.get("text", ""))
        if not text:
            continue
        for term in terms:
            for alias in term["aliases"]:
                # Whole-phrase boundary match to avoid matching "PREPAID"
                # inside words like "PREPAIDMENT".
                if _contains_alias(text, alias):
                    return {
                        "term": term["term"],
                        "meaning": term["note"],
                        "status": "CONFIRMED",
                        "explicit": True,
                        "source_text": entry["text"].strip(),
                        "rule_source": RULE_SOURCE,
                        "confidence": "Exact Rule Match",
                        "note": f"Explicitly printed payment term: {term['term']}. {term['note']}",
                    }
    return {
        "term": None,
        "meaning": None,
        "status": "NOT DETECTED",
        "explicit": False,
        "source_text": None,
        "rule_source": RULE_SOURCE,
        "confidence": None,
        "note": "Payment term not explicitly printed on this BOL. "
                "Do not guess - VERIFY WITH TRAINER before entering a payment code.",
    }


def _contains_alias(text: str, alias: str) -> bool:
    # "freight prepaid" / "prepaid" etc. Use word boundaries when the
    # alias has no punctuation inside it.
    alias = alias.strip().lower()
    if not alias:
        return False
    words = alias.replace("-", " ").split()
    # Exact-ish match: alias appears as a token sequence in text.
    start = 0
    while True:
        idx = text.find(alias, start)
        if idx == -1:
            return False
        before_ok = idx == 0 or not text[idx - 1].isalnum()
        after = idx + len(alias)
        after_ok = after >= len(text) or not text[after].isalnum()
        if before_ok and after_ok:
            return True
        start = idx + 1