"""Local Ollama client.

The vision model (qwen2.5-VL or another local vision model) is used for
EXTRACTION ONLY. It is explicitly instructed to return raw BOL wording /
structured fields and is NEVER asked to decide M-Codes. Every extracted
value is passed through the deterministic rule engine.

Ollama being offline is handled gracefully: the core M-Code system keeps
working; only image extraction is unavailable.
"""
from __future__ import annotations

import base64
import io
import json
import re
from typing import Dict, List, Optional

import requests

DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434"
DEFAULT_GEMINI_MODEL = "gemini-3.6-flash"
VISION_PATTERNS = [
    re.compile(r"qwen.*vl", re.IGNORECASE),
    re.compile(r"llava", re.IGNORECASE),
    re.compile(r"minicpm.*v", re.IGNORECASE),
    re.compile(r"vision", re.IGNORECASE),
    re.compile(r"moondream", re.IGNORECASE),
]

EXTRACTION_PROMPT = """You are a Bill of Lading (BOL) data extraction assistant for R+L Carriers training. Read the BOL image and extract the data into STRICT JSON only, with no commentary and no markdown. Use exactly this schema:
{
  "shipper": "",
  "consignee": "",
  "attn": "",
  "bill_to": "",
  "freight_terms": "",
  "pro_number": "",
  "handling_units": "",
  "pieces": "",
  "weight": "",
  "description": "",
  "nmfc": "",
  "class": "",
  "references": [],
  "special_instructions": [],
  "contacts": [],
  "dates": [],
  "payment_terms": [],
  "raw_text": []
}
Rules:
- Transcribe exact wording from the image. Do not interpret, translate, summarize or correct.
- references: one string per labeled reference, e.g. "PO #: 458921".
- special_instructions: one string per instruction line, e.g. "DO NOT STACK".
- raw_text: every readable line of text on the document.
- If something is unreadable or absent, use an empty string or empty array. NEVER guess or fabricate values.
- You are extracting text only. You MUST NOT determine, suggest or reason about M-Codes, MM entries, NMFC values, classes or Tenet/EBS entries.
Return only the JSON object."""


def ollama_status(url: str = DEFAULT_OLLAMA_URL, timeout: float = 2.0) -> Dict[str, object]:
    """Check whether a local Ollama instance is reachable and list models."""
    try:
        resp = requests.get(url.rstrip("/") + "/api/tags", timeout=timeout)
        if resp.status_code == 200:
            models = [m.get("name", "") for m in resp.json().get("models", [])]
            return {"available": True, "models": models, "error": None}
        return {"available": False, "models": [], "error": f"Ollama returned HTTP {resp.status_code}"}
    except requests.RequestException as exc:
        return {"available": False, "models": [], "error": str(exc)}


def pick_vision_model(models: List[str], preferred: str = "") -> Optional[str]:
    """Choose a vision-capable model. Preference: configured model, then
    qwen2.5-VL style names, then any known vision model."""
    if preferred and preferred in models:
        return preferred
    # qwen2.5vl / qwen2.5-vl family first
    for m in models:
        base = m.split(":")[0].lower()
        if base in ("qwen2.5vl", "qwen2.5-vl", "qwen2vl", "qwen2-vl") or base.startswith("qwen2.5vl"):
            return m
    for m in models:
        for pat in VISION_PATTERNS:
            if pat.search(m):
                return m
    return None


def _preprocess_image(image_bytes: bytes) -> bytes:
    """Downscale large images so OCR payloads stay small (Pillow)."""
    from PIL import Image
    img = Image.open(io.BytesIO(image_bytes))
    img = img.convert("RGB")
    max_dim = 1600
    w, h = img.size
    if max(w, h) > max_dim:
        ratio = max_dim / float(max(w, h))
        img = img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def extract_bol_from_image(
    url: str,
    model: str,
    image_bytes: bytes,
    timeout: float = 300.0,
) -> Dict[str, object]:
    """Send an image to the local vision model for structured extraction.

    Returns {"success": bool, "data": {...}, "error": str|None}.
    """
    try:
        img = _preprocess_image(image_bytes)
        b64 = base64.b64encode(img).decode("ascii")
        payload = {
            "model": model,
            "prompt": EXTRACTION_PROMPT,
            "images": [b64],
            "stream": False,
            "format": "json",
            "options": {"temperature": 0},
        }
        resp = requests.post(
            url.rstrip("/") + "/api/generate",
            json=payload,
            timeout=timeout,
        )
        if resp.status_code != 200:
            return {"success": False, "data": None, "error": f"Ollama returned HTTP {resp.status_code}"}
        raw = resp.json().get("response", "")
        data = _parse_json_response(raw)
        if data is None:
            return {"success": False, "data": None, "error": "Vision model did not return valid JSON."}
        return {"success": True, "data": data, "error": None}
    except requests.RequestException as exc:
        return {"success": False, "data": None, "error": f"Ollama request failed: {exc}"}
    except Exception as exc:  # noqa: BLE001 - degrade gracefully offline
        return {"success": False, "data": None, "error": f"Image processing failed: {exc}"}


def extract_bol_with_gemini(api_key: str, image_bytes: bytes, model: str = DEFAULT_GEMINI_MODEL, timeout: float = 120.0) -> Dict[str, object]:
    """Extract BOL text through Gemini without giving it M-Code authority."""
    if not api_key:
        return {"success": False, "data": None, "error": "GEMINI_API_KEY is not configured."}
    try:
        image = _preprocess_image(image_bytes)
        payload = {
            "contents": [{"parts": [
                {"text": EXTRACTION_PROMPT},
                {"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(image).decode("ascii")}},
            ]}],
            "generationConfig": {"temperature": 0, "responseMimeType": "application/json"},
        }
        response = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            params={"key": api_key}, json=payload, timeout=timeout,
        )
        if response.status_code != 200:
            return {"success": False, "data": None, "error": f"Gemini returned HTTP {response.status_code}: {response.text[:300]}"}
        body = response.json()
        raw = body["candidates"][0]["content"]["parts"][0].get("text", "")
        data = _parse_json_response(raw)
        if data is None:
            return {"success": False, "data": None, "error": "Gemini did not return valid extraction JSON."}
        return {"success": True, "data": data, "error": None}
    except requests.RequestException as exc:
        return {"success": False, "data": None, "error": f"Gemini request failed: {exc}"}
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        return {"success": False, "data": None, "error": f"Gemini response was not usable: {exc}"}


def _parse_json_response(raw: str) -> Optional[Dict[str, object]]:
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    # Try to find the first JSON object in the response.
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        try:
            data = json.loads(m.group(0))
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass
    return None


def extract_text_from_pdf(pdf_bytes: bytes) -> Dict[str, object]:
    """Extract embedded text from a PDF (works for text-based PDFs, not scans)."""
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(pdf_bytes))
        pages = []
        for page in reader.pages:
            pages.append(page.extract_text() or "")
        text = "\n".join(pages).strip()
        if not text:
            return {
                "success": False,
                "data": None,
                "error": "PDF appears to be a scan (no embedded text). Convert it to a PNG/JPG image and upload that.",
            }
        return {"success": True, "data": text, "error": None}
    except Exception as exc:  # noqa: BLE001
        return {"success": False, "data": None, "error": f"PDF text extraction failed: {exc}"}
