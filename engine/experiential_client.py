"""Experiential Labs image transcription; M-Code decisions stay in the rule engine."""
from __future__ import annotations

import base64
import os

import requests

from engine.ollama_client import EXTRACTION_PROMPT, _parse_json_response, _preprocess_image

DEFAULT_MODEL = "gpt-5.6-luna"
CHAT_URL = "https://api.experientiallabs.ai/v1/chat/completions"


def api_key() -> str:
    return os.environ.get("gpt_expLab_api", "").strip() or os.environ.get("EXPLABS_API_KEY", "").strip()


def model_name() -> str:
    return os.environ.get("EXPLABS_MODEL", "").strip() or DEFAULT_MODEL


def extract_bol(api_key: str, image_bytes: bytes, model: str = DEFAULT_MODEL, timeout: float = 120.0) -> dict:
    def failure(message):
        return {"success": False, "data": None, "error": message}

    if not api_key.strip():
        return failure("Experiential Labs API key is not configured.")
    try:
        image = _preprocess_image(image_bytes)
    except (OSError, ValueError):
        return failure("The uploaded file could not be read as an image.")
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": EXTRACTION_PROMPT},
            {"type": "image_url", "image_url": {
                "url": "data:image/jpeg;base64," + base64.b64encode(image).decode("ascii"),
            }},
        ]}],
        "response_format": {"type": "json_object"},
    }
    try:
        response = requests.post(
            CHAT_URL, headers={"Authorization": f"Bearer {api_key.strip()}"},
            json=payload, timeout=timeout,
        )
        if response.status_code != 200:
            guidance = {
                401: "Check the configured API key.",
                403: "Check access to the selected model.",
                429: "Check your request limit or available credits, then retry.",
            }.get(response.status_code, "Retry or check the provider dashboard.")
            return failure(f"Experiential Labs returned HTTP {response.status_code}. {guidance}")
        message = response.json()["choices"][0]["message"]
        if message.get("refusal"):
            return failure("Experiential Labs declined to extract this image.")
        data = _parse_json_response(message["content"])
        if not data or not any(data.values()):
            return failure("Experiential Labs did not return usable extraction JSON.")
        return {"success": True, "data": data, "error": None}
    except requests.Timeout:
        return failure("Experiential Labs timed out. Please retry.")
    except requests.RequestException:
        return failure("Could not reach Experiential Labs. Please retry.")
    except (KeyError, IndexError, TypeError, ValueError, AttributeError):
        return failure("Experiential Labs did not return usable extraction JSON.")
