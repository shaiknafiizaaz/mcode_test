"""Loads the authoritative rule files from data/.

data/mcode_rules.json is the SINGLE source of truth for M-Codes.
The rule engines reference codes by their database entry so that
meanings/categories/triggers are never duplicated in code.
"""
from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from typing import Any, Dict, List, Optional

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")

RULE_FILES = {
    "mcodes": "mcode_rules.json",
    "payment": "payment_rules.json",
    "description": "description_rules.json",
    "training": "training_examples.json",
}


def data_path(name: str) -> str:
    return os.path.join(DATA_DIR, RULE_FILES[name])


@lru_cache(maxsize=8)
def load_rules(name: str) -> Dict[str, Any]:
    with open(data_path(name), "r", encoding="utf-8") as fh:
        data = json.load(fh)
    if name == 'mcodes':
        from .rule_integrity import validate_database
        report = validate_database(data)
        if report['errors']:
            raise ValueError('Invalid authoritative M-Code database: ' + '; '.join(report['errors']))
    return data


def role_code(role: str) -> str:
    return next(c['code'] for c in load_mcodes() if c.get('role') == role)


def load_mcodes() -> List[Dict[str, Any]]:
    """Returns the authoritative list of M-Code rule entries."""
    return load_rules("mcodes")["codes"]


def get_code_map() -> Dict[str, Dict[str, Any]]:
    """code (uppercase) -> rule entry."""
    return {c["code"].upper(): c for c in load_mcodes()}


def normalize(text: str) -> str:
    """Lowercase, collapse whitespace. Used for trigger matching."""
    if not text:
        return ""
    return re.sub(r"\s+", " ", text.lower()).strip()


def code_category(category_key: str) -> str:
    """Map category keys used by the mock test to display categories."""
    mapping = {
        "Shipper / Pickup": "Shipper",
        "Consignee / Delivery": "Consignee",
        "Delivery Dates": "Delivery Dates",
        "Other Reference Numbers": "References",
        "Special Instructions": "Special Instructions",
        "Appointment Codes": "Appointment",
        "Call Before / Prior To Delivery": "Call Before",
    }
    return mapping.get(category_key, category_key)
