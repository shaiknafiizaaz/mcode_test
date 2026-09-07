"""Deterministic M-Code rule engine.

THE APPLICATION MUST NEVER INVENT AN M-CODE. Every code emitted by this
engine comes from data/mcode_rules.json (the authoritative database) or
from the explicitly coded contextual rules below (appointment vs
call-before, service direction, person-name guard), each of which maps
back to a code that exists in the database.

Pipeline (per parsed line):
    line text
      -> handling units (MM)          engine/handling_units.py
      -> labeled references/values    engine/reference_engine.py
      -> contextual service codes     this module (direction aware)
      -> appointment / call-before    this module (time + phone aware)
      -> plain trigger phrases        data/mcode_rules.json
      -> MA person-name guard         this module
    then document-level pass: phone resolution, conflicts, MBR check.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional

from .handling_units import analyze_handling_units, has_bare_handling_unit
from .reference_engine import analyze_line as analyze_reference_line
from .rules_loader import get_code_map, load_mcodes, load_rules, role_code, normalize

RULE_SOURCE = "data/mcode_rules.json"

# ---------------------------------------------------------------------------
# Phones
# ---------------------------------------------------------------------------
PHONE_RE = re.compile(
    r"(?:(?:\+?\d{1,3}[\s.-]?)?(?:\(\d{3}\)[\s.-]?|\d{3}[\s.-])\d{3}[\s.-]\d{4}"
    r"|\d{3}[\s.-]\d{4})"
)

# ---------------------------------------------------------------------------
# Service codes: direction-aware (explicit direction -> CONFIRMED;
# direction inferred from section -> VERIFY; ambiguous -> warning only).
# ---------------------------------------------------------------------------
_SERVICE_CODES = {c['code']: {side: side in c['service']['directions'] or None for side in ('pickup', 'delivery')} for c in load_mcodes() if 'service' in c}
_SERVICE_TRIGGER = {c['code']: re.compile(c['service']['pattern'], re.I) for c in load_mcodes() if 'service' in c}

_PICKUP_WORD = re.compile(r"\bpick\s*ups?\b|\bpickups?\b", re.IGNORECASE)
_DELIVERY_WORD = re.compile(r"\bdeliver(?:y|ies|ed)?\b", re.IGNORECASE)

_PICKUP_SECTIONS = {"shipper", "pickup"}
_DELIVERY_SECTIONS = {"consignee", "delivery"}

# ---------------------------------------------------------------------------
# Appointment vs Call-Before
# ---------------------------------------------------------------------------
_PATTERN_DATA = load_rules('mcodes')['patterns']
_APPOINTMENT_PATTERNS = [re.compile(p, re.I) for p in _PATTERN_DATA['appointment']]
_NO_APPOINTMENT_PATTERNS = [re.compile(p, re.I) for p in _PATTERN_DATA['no_appointment']]
_CALL_BEFORE_PATTERNS = [re.compile(p, re.I) for p in _PATTERN_DATA['callbefore']]

_TIME_HOURS_RE = re.compile(
    r"\b(\d+|one|two|twenty\s*[- ]?four|forty\s*[- ]?eight|seventy\s*[- ]?two)\s*"
    r"(?:hrs?|hours?)\s*before\b", re.IGNORECASE
)

_HOURS_VALUE = {
    "24": 24, "twenty four": 24, "twenty-four": 24,
    "48": 48, "forty eight": 48, "forty-eight": 48,
    "72": 72, "seventy two": 72, "seventy-two": 72,
    "1": 1, "one": 1, "2": 2, "two": 2,
}

# Appointment time-specific codes.
_APPT_TIME_CODE = {c['hours']: c['code'] for c in load_mcodes() if c.get('family') == 'appointment' and 'hours' in c}
_CALLB_TIME_CODE = {c['hours']: c['code'] for c in load_mcodes() if c.get('family') == 'callbefore' and 'hours' in c}
_CALLB_TIME_REQUIRES_PHONE = {c['hours'] for c in load_mcodes() if c.get('family') == 'callbefore' and c.get('phone_value')}
_APPOINTMENT_FAMILY = {c['code'] for c in load_mcodes() if c.get('family') == 'appointment'}

# ---------------------------------------------------------------------------
# MA guard: generic departments must not become MA.
# ---------------------------------------------------------------------------
_DEPARTMENT_WORDS = {
    "parts", "receiving", "shipping", "warehouse", "dock", "accounting",
    "billing", "purchasing", "procurement", "customer service", "maintenance",
    "general office", "mail room", "mailroom", "human resources", "office",
    "stores", "stockroom", "loading dock", "front desk", "reception",
}
_ATTN_RE = re.compile(_PATTERN_DATA['attention'], re.I)


def _looks_like_department(value: str) -> bool:
    v = normalize(value)
    if not v:
        return False
    # "PARTS DEPARTMENT", "SHIPPING DEPT" etc.
    for word in _DEPARTMENT_WORDS:
        if v == word or v.startswith(word) or v.endswith(word) or f" {word} " in f" {v} ":
            return True
    return False


# ---------------------------------------------------------------------------
# Plain trigger codes (substring match against data/mcode_rules.json).
# Codes with dedicated contextual logic are excluded here.
# ---------------------------------------------------------------------------
_EXCLUDED_FROM_PLAIN = {c['code'] for c in load_mcodes() if not c['plain_enabled']}

_TRIGGER_CACHE: Optional[Dict[str, List[str]]] = None


def _plain_triggers() -> Dict[str, List[str]]:
    global _TRIGGER_CACHE
    if _TRIGGER_CACHE is None:
        cache: Dict[str, List[str]] = {}
        for c in load_mcodes():
            code = c["code"].upper()
            if code in _EXCLUDED_FROM_PLAIN:
                continue
            triggers = [normalize(t).replace("-", " ") for t in c.get("triggers", []) if t]
            # longest triggers first so "do not top load" wins over "top load"
            triggers.sort(key=len, reverse=True)
            cache[code] = triggers
        _TRIGGER_CACHE = cache
    return _TRIGGER_CACHE


def _find_plain_matches(text):
    """Exact phrase candidates; preserve ties instead of depending on JSON order."""
    norm = normalize(text.replace('-', ' '))
    matches = []
    for code, triggers in _plain_triggers().items():
        if any(re.search(p, text, re.I) for p in get_code_map()[code].get('exclude_patterns', [])):
            continue
        for trigger in triggers:
            if re.search(r'(?<!\w)' + re.escape(trigger) + r'(?!\w)', norm):
                matches.append((code, trigger, get_code_map()[code]['priority']))
                break
    if not matches:
        return []
    rank = min((p, -len(t)) for c, t, p in matches)
    return [(c, t, p) for c, t, p in matches if (p, -len(t)) == rank]


def _associated_phones(lines, index):
    line = lines[index]
    direct = _phones_in_text(line['text'])
    if direct:
        return list(dict.fromkeys(direct))
    section = line.get('section', 'any')
    pickup = bool(_PICKUP_WORD.search(line['text'])) or section in _PICKUP_SECTIONS
    compatible = _PICKUP_SECTIONS if pickup else _DELIVERY_SECTIONS
    opposite = _DELIVERY_SECTIONS if pickup else _PICKUP_SECTIONS
    def permitted(other):
        text = other['text'].lower()
        # Reference identifiers that resemble phone numbers are not contacts.
        if not (re.search(r'\bphone\b|\btel\b|\btelephone\b|\bcontact\b|\bcall\b', text) or PHONE_RE.fullmatch(text.strip())):
            return False
        if other.get('section') in opposite:
            return False
        if not pickup and re.search(r'\bshipper\s+phone', text):
            return False
        if pickup and re.search(r'\bcustomer\s+phone', text):
            return False
        return other.get('section', 'any') in compatible | {section, 'any', 'contact', 'special'}
    # An immediately following phone-only line belongs to this instruction.
    if index + 1 < len(lines):
        other = lines[index + 1]
        phones = _phones_in_text(other['text'])
        if phones and permitted(other) and not re.search(r'\bcall\b|appointment', other['text'], re.I):
            return list(dict.fromkeys(phones))
    return list(dict.fromkeys(ph for other in lines if permitted(other)
                             for ph in _phones_in_text(other['text'])))


# ---------------------------------------------------------------------------
# Document / line analysis
# ---------------------------------------------------------------------------

def _phones_in_text(text: str) -> List[str]:
    return [m.group(0) for m in PHONE_RE.finditer(text)]


def analyze_lines(lines: List[Dict[str, str]]) -> Dict[str, object]:
    """Run the full deterministic engine over parsed lines.

    lines: list of {"section": str, "text": str}
    """
    code_map = get_code_map()
    entries: List[Dict[str, object]] = []
    warnings: List[str] = []

    # Retain raw phones for traceability; instruction association is contextual.
    doc_phones: List[str] = []
    for ln in lines:
        for ph in _phones_in_text(ln.get("text", "")):
            doc_phones.append(ph)

    for line_index, ln in enumerate(lines):
        section = ln.get("section", "any")
        text = ln.get("text", "")
        if not text.strip():
            continue
        line_norm = normalize(text)

        # 1) Handling units (MM). Runs on every line - MM is NOT NMFC.
        hu = analyze_handling_units(text)
        if hu:
            hu["section"] = section
            entries.append(hu)
        elif has_bare_handling_unit(text) and section not in ("description",):
            warnings.append(
                f"Handling-unit term found without a count: '{text.strip()}'. "
                "VERIFY the number of pallets/skids before entering MM."
            )

        # 2) Labeled references/values.
        ref_matched = False
        references = analyze_reference_line(text, section)
        for ref in references:
            ref_matched = True
            code = ref["code"]
            entry = _make_db_entry(code, code_map)
            entry.update(ref)
            entries.append(entry)

        # 3) Plain trigger phrases from the authoritative database.
        # Lines that already matched a labeled reference skip plain-trigger
        # matching so that e.g. "PACKING LIST #: 3301" does not also fire
        # the MPACK "packing list" trigger.
        plain = _find_plain_matches(line_norm) if not ref_matched else []
        plain_matched = False
        for code, trigger, priority in plain:
            plain_matched = True
            entry = _make_db_entry(code, code_map)
            entry.update({
                "value": text.strip(),
                "source_text": text.strip(),
                "matched_trigger": trigger,
                "rule_source": RULE_SOURCE,
                "confidence": "Exact Rule Match",
                "status": "CONFLICT" if len(plain) > 1 else "CONFIRMED",
                "priority": priority,
                "section": section,
            })
            entries.append(entry)

        # 4) Appointment / call-before family.
        phones = _associated_phones(lines, line_index)
        appt = _analyze_appointment_callbefore(text, section, bool(phones), phones, plain_matched)
        if references and not re.search(r'\bcall\b|\bappointment\b', text, re.I):
            appt = {}  # A structured date label is not an appointment request.
        if appt:
            if appt.get("warning"):
                warnings.append(appt["warning"])
            for entry in appt.get('entries', [appt['entry']] if appt.get('entry') else []):
                entry['section'] = section
                entry['priority'] = code_map[entry['code']]['priority']
                if code_map[entry['code']].get('phone_value'):
                    entry['value'] = ''
                    if len(phones) == 1:
                        entry['phone'] = entry['value'] = phones[0]
                    elif len(phones) > 1:
                        entry['status'] = 'CONFLICT'
                        entry['phone_candidates'] = phones
                        warnings.append('Multiple equally applicable phone numbers; CONFLICT. Select the intended contact.')
                entries.append(entry)

        # 5) Service codes (direction aware).
        service = _analyze_service_codes(text, section)
        if service:
            warnings.extend(service.get("warnings", []))
            for entry in service.get("entries", []):
                entries.append(entry)

        # 6) MA person-name guard.
        ma = _analyze_attn(text, section)
        if ma:
            if ma.get("warning"):
                warnings.append(ma["warning"])
            if ma.get("entry"):
                entries.append(ma["entry"])

    # Resolve phone-dependent appointment/call-before entries.
    used_phones = {e['phone'] for e in entries if e.get('phone')}
    resolved = [e for e in entries if not (e['code'] == role_code('generic_phone') and e.get('value') in used_phones)]

    # Conflicts.
    conflicts = _detect_conflicts(entries)

    # De-duplicate: same code + same value + same source line.
    deduped = _dedupe(resolved)

    return {
        "entries": deduped,
        "warnings": _dedupe_strings(warnings),
        "conflicts": conflicts,
        "doc_phones": doc_phones,
    }


def _make_db_entry(code: str, code_map: Dict[str, Dict[str, object]]) -> Dict[str, object]:
    entry = code_map[code]
    return {
        "code": code,
        "meaning": entry.get("meaning", code),
        "category": entry.get("category", ""),
        "priority": entry["priority"],
    }


# ---------------------------------------------------------------------------
# Appointment vs call-before
# ---------------------------------------------------------------------------

def _analyze_appointment_callbefore(
    text: str,
    section: str,
    section_has_phone: bool,
    doc_phones: List[str],
    line_has_plain_match: bool = False,
) -> Dict[str, object]:
    """Classify a line containing call/appointment/schedule wording."""
    norm = normalize(text)

    # No appointment necessary -> MNDA (conflict checked later).
    if any(p.search(norm) for p in _NO_APPOINTMENT_PATTERNS):
        return {"entry": _appt_entry(role_code('no_appointment'), text, "no appointment necessary", "CONFIRMED")}

    # Is this line about appointments at all?
    is_appointment = any(p.search(norm) for p in _APPOINTMENT_PATTERNS)
    is_call_before = any(p.search(norm) for p in _CALL_BEFORE_PATTERNS)
    has_call_word = bool(re.search(r"\bcall\b", norm)) or is_call_before or is_appointment

    if not (has_call_word or is_appointment or is_call_before):
        return {}

    # Time-specific handling takes precedence.
    time_matches = list(_TIME_HOURS_RE.finditer(norm))
    distinct_hours = {_HOURS_VALUE.get(m.group(1).lower()) for m in time_matches}
    if len(distinct_hours) > 1:
        timed_codes = _APPT_TIME_CODE if is_appointment else _CALLB_TIME_CODE
        candidates = [_appt_entry(timed_codes[h], text, m.group(0), 'CONFLICT')
                      for m in time_matches
                      if (h := _HOURS_VALUE.get(m.group(1).lower())) in timed_codes]
        return {'entries': candidates, 'warning': 'CONFLICT: multiple incompatible call timing instructions on the same line.'}
    time_m = _TIME_HOURS_RE.search(norm)
    hours = _HOURS_VALUE.get(time_m.group(1).lower()) if time_m else None
    if time_m and hours is None:
        # e.g. "5 hours before" - no code defined; do not invent.
        return {"warning": f"Time-specific call instruction found with unsupported hours ('{time_m.group(0)}'). No M-Code exists for this; VERIFY WITH TRAINER."}

    if hours is not None:
        if is_appointment and hours in _APPT_TIME_CODE:
            code = _APPT_TIME_CODE[hours]
            return {"entry": _appt_entry(code, text, f"call for appointment {hours} hours before delivery", "CONFIRMED")}
        if hours in _CALLB_TIME_CODE:
            code = _CALLB_TIME_CODE[hours]
            if hours in _CALLB_TIME_REQUIRES_PHONE:
                if section_has_phone or doc_phones:
                    return {"entry": _appt_entry(code, text, f"call {hours} hours before delivery", "CONFIRMED", phone_required=True)}
                return {
                    "entry": _appt_entry(code, text, f"call {hours} hours before delivery", "VERIFY", phone_required=True),
                    "warning": f"{code} requires a phone number; none detected. VERIFY against the original BOL.",
                }
            return {"entry": _appt_entry(code, text, f"call {hours} hours before delivery", "CONFIRMED")}
        # appointment hours not supported (e.g. 24 call-before under appointment wording -> MADV handled above; 72 call-before has no code)
        if not is_appointment and hours == 72:
            return {"warning": "72-hour call-before has no defined M-Code in the authoritative database. VERIFY WITH TRAINER."}
        return {"warning": f"Unsupported call timing '{time_m.group(0)}'. No M-Code exists; VERIFY WITH TRAINER."}

    # Generic (no time): appointment vs call-before vs ambiguous.
    if is_appointment:
        code = role_code('appointment_phone') if (section_has_phone or doc_phones) else role_code('appointment_no_phone')
        return {"entry": _appt_entry(code, text, "call for appointment", "CONFIRMED", phone_required=True)}

    if is_call_before:
        if re.search(r"notify|notification", norm):
            # Notify instructions -> MNOTI (no phone requirement).
            return {"entry": _appt_entry(role_code('notify'), text, "notify prior to delivery", "CONFIRMED")}
        code = role_code('callbefore_phone') if (section_has_phone or doc_phones) else role_code('callbefore_no_phone')
        return {"entry": _appt_entry(code, text, "call before delivery", "CONFIRMED", phone_required=True)}

    # Bare "call ..." with no appointment/before/time wording and nothing
    # else on the line already explained it (e.g. "CALL WITH ANY QUESTIONS"
    # is explained by MEGLA). Ambiguous - never guess.
    if has_call_word and not line_has_plain_match and not ref_matched_hint(norm):
        return {
            "warning": (
                f"Call instruction is ambiguous: '{text.strip()}'. "
                "It could be an appointment (schedule/arrange) or a call-before "
                "(notify prior). VERIFY WITH TRAINER - no code emitted."
            )
        }

    return {}


def ref_matched_hint(norm: str) -> bool:
    """True when the line is already explained by a labeled reference."""
    return bool(re.search(r"phone|tel|#|no\.", norm))


def _appt_entry(code: str, source_text: str, trigger: str, status: str, phone_required: bool = False) -> Dict[str, object]:
    code_map = get_code_map()
    entry = _make_db_entry(code, code_map)
    entry.update({
        "value": source_text.strip(),
        "source_text": source_text.strip(),
        "matched_trigger": trigger,
        "rule_source": RULE_SOURCE,
        "confidence": "Exact Rule Match" if status == "CONFIRMED" else "Pattern Match - Verify",
        "status": status,
    })
    if phone_required and code_map[code].get('phone_value') and status == "CONFIRMED":
        entry["note"] = "Phone number present; phone-dependent code resolved."
    return entry


# ---------------------------------------------------------------------------
# Service codes
# ---------------------------------------------------------------------------

def _analyze_service_codes(text: str, section: str) -> Dict[str, object]:
    entries: List[Dict[str, object]] = []
    warnings: List[str] = []
    for code, pattern in _SERVICE_TRIGGER.items():
        m = pattern.search(text)
        if not m:
            continue
        info = _SERVICE_CODES[code]
        pickup = bool(_PICKUP_WORD.search(text))
        delivery = bool(_DELIVERY_WORD.search(text))
        if pickup and delivery:
            # e.g. "LIFT GATE PICKUP AND DELIVERY" -> both codes
            entries.append(_service_entry(code, text, m.group(0), section, "CONFIRMED"))
            continue
        if pickup:
            meaning = info.get("pickup")
            if meaning is None:
                pass
                continue
            entries.append(_service_entry(code, text, m.group(0), section, "CONFIRMED"))
            continue
        if delivery:
            meaning = info.get("delivery")
            if meaning is None:
                pass
                continue
            entries.append(_service_entry(code, text, m.group(0), section, "CONFIRMED"))
            continue
        # No explicit direction on the line - fall back to section context.
        if section in _PICKUP_SECTIONS and info.get("pickup"):
            entries.append(_service_entry(code, text, m.group(0), section, "VERIFY"))
            warnings.append(f"'{text.strip()}' - direction inferred from section ({section}). VERIFY before entering {code}.")
        elif section in _DELIVERY_SECTIONS and info.get("delivery"):
            entries.append(_service_entry(code, text, m.group(0), section, "VERIFY"))
            warnings.append(f"'{text.strip()}' - direction inferred from section ({section}). VERIFY before entering {code}.")
        else:
            warnings.append(
                f"'{text.strip()}' matches {code} but pickup vs delivery direction is ambiguous. "
                "VERIFY WITH TRAINER - no code emitted."
            )
    if not entries and not warnings:
        return {}
    return {"entries": entries, "warnings": warnings}


def _service_entry(code: str, source_text: str, trigger: str, section: str, status: str) -> Dict[str, object]:
    code_map = get_code_map()
    entry = _make_db_entry(code, code_map)
    entry.update({
        "value": source_text.strip(),
        "source_text": source_text.strip(),
        "matched_trigger": trigger,
        "rule_source": RULE_SOURCE,
        "confidence": "Exact Rule Match" if status == "CONFIRMED" else "Context Match - Verify",
        "status": status,
        "section": section,
    })
    return entry


# ---------------------------------------------------------------------------
# MA person-name guard
# ---------------------------------------------------------------------------

def _analyze_attn(text: str, section: str) -> Dict[str, object]:
    """ATTN/CONTACT lines -> MA, but only for actual person names.

    Generic departments (PARTS, RECEIVING, SHIPPING, ...) must NOT become
    MA; they produce a VERIFY warning instead. A phone number in the
    ATTN value is a contact phone, not a person name.
    """
    m = _ATTN_RE.search(text)
    if not m:
        return {}
    person = m.group(1).strip()
    if not person:
        return {}
    if _phones_in_text(person):
        return {
            "warning": (
                f"CONTACT value '{person}' is a phone number, not a person name. "
                "Do NOT enter MA - use a phone code instead."
            )
        }
    if _looks_like_department(person):
        return {
            "warning": (
                f"ATTN value '{person}' looks like a generic department, not a person. "
                "Do NOT enter MA for a department. VERIFY whether a contact person is intended."
            )
        }
    entry = _make_db_entry(role_code('attention'), get_code_map())
    entry.update({
        "value": person,
        "source_text": text.strip(),
        "matched_trigger": "attn",
        "rule_source": RULE_SOURCE,
        "confidence": "Exact Rule Match",
        "status": "CONFIRMED",
        "section": section,
    })
    return {"entry": entry}


# ---------------------------------------------------------------------------
# Conflicts + dedupe
# ---------------------------------------------------------------------------

def _detect_conflicts(entries: List[Dict[str, object]]) -> List[Dict[str, object]]:
    conflicts: List[Dict[str, object]] = []
    codes = [e.get("code") for e in entries]
    appt_sources = [
        e.get("source_text") for e in entries if e.get("code") in _APPOINTMENT_FAMILY
    ]
    mnda_sources = [e.get("source_text") for e in entries if e.get("code") == role_code('no_appointment')]
    if appt_sources and mnda_sources:
        conflicts.append({
            "type": "appointment",
            "message": (
                "CONFLICT DETECTED: an appointment instruction and a "
                "'no appointment necessary' instruction are both present."
            ),
            "phrases": appt_sources + mnda_sources,
        })
    if appt_sources and mnda_sources:
        for entry in entries:
            if entry['code'] in _APPOINTMENT_FAMILY | {role_code('no_appointment')}:
                entry['status'] = 'CONFLICT'
    already_reported = _APPOINTMENT_FAMILY | {role_code('no_appointment')} if appt_sources and mnda_sources else set()
    tied = [e for e in entries if e.get('status') == 'CONFLICT' and e['code'] not in already_reported]
    if tied:
        conflicts.append({'type': 'rule_priority', 'message': 'CONFLICT: equally strong incompatible candidates.', 'phrases': [e['source_text'] for e in tied]})
    return conflicts


def _dedupe(entries: List[Dict[str, object]]) -> List[Dict[str, object]]:
    seen = set()
    out = []
    for e in entries:
        key = (e.get("code"), normalize(str(e.get("value", ""))), normalize(str(e.get("source_text", ""))))
        if key in seen:
            continue
        seen.add(key)
        out.append(e)
    return out


def _dedupe_strings(items: List[str]) -> List[str]:
    out = []
    seen = set()
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out
