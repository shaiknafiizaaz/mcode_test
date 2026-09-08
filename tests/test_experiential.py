"""Hosted OCR contract, failures and routing without sending documents externally."""
import io
from unittest.mock import Mock

import pytest
import requests
from PIL import Image
from fastapi.testclient import TestClient

from engine import experiential_client as provider


@pytest.fixture
def image_bytes():
    buf = io.BytesIO()
    Image.new("RGB", (12, 12), "white").save(buf, format="PNG")
    return buf.getvalue()


def test_request_and_response(monkeypatch, image_bytes):
    post = Mock(return_value=Mock(status_code=200, json=lambda: {
        "choices": [{"message": {"content": '{"raw_text": ["PO # 12345"]}'}}],
    }))
    monkeypatch.setattr(provider.requests, "post", post)
    result = provider.extract_bol("test-secret", image_bytes)
    assert result == {"success": True, "data": {"raw_text": ["PO # 12345"]}, "error": None}
    args, kwargs = post.call_args
    assert args == ("https://api.experientiallabs.ai/v1/chat/completions",)
    assert kwargs["headers"] == {"Authorization": "Bearer test-secret"}
    assert kwargs["json"]["model"] == "gpt-5.6-luna"
    assert kwargs["json"]["response_format"] == {"type": "json_object"}
    assert kwargs["json"]["messages"][0]["content"][1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert "test-secret" not in str(kwargs["json"])


@pytest.mark.parametrize("status", [401, 403, 429, 500])
def test_http_errors_do_not_expose_response_body(monkeypatch, image_bytes, status):
    monkeypatch.setattr(provider.requests, "post", Mock(return_value=Mock(status_code=status, text="test-secret")))
    result = provider.extract_bol("test-secret", image_bytes)
    assert not result["success"]
    assert str(status) in result["error"]
    assert "test-secret" not in result["error"]


@pytest.mark.parametrize("body", [{}, {"choices": []}, {"choices": [{"message": {"content": None}}]},
    {"choices": [{"message": {"content": "not JSON"}}]},
    {"choices": [{"message": {"content": "{}"}}]},
    {"choices": [{"message": {"refusal": "no", "content": None}}]}])
def test_malformed_or_refused_response(monkeypatch, image_bytes, body):
    monkeypatch.setattr(provider.requests, "post", Mock(return_value=Mock(status_code=200, json=lambda: body)))
    assert not provider.extract_bol("test-secret", image_bytes)["success"]


@pytest.mark.parametrize("error", [requests.Timeout("test-secret"), requests.ConnectionError("test-secret")])
def test_network_errors_are_sanitized(monkeypatch, image_bytes, error):
    monkeypatch.setattr(provider.requests, "post", Mock(side_effect=error))
    result = provider.extract_bol("test-secret", image_bytes)
    assert not result["success"]
    assert "test-secret" not in result["error"]


def test_bad_image_and_missing_key_do_not_call_provider(monkeypatch, image_bytes):
    post = Mock()
    monkeypatch.setattr(provider.requests, "post", post)
    assert not provider.extract_bol("", image_bytes)["success"]
    assert not provider.extract_bol("secret", b"not an image")["success"]
    post.assert_not_called()


@pytest.fixture
def client(monkeypatch, tmp_path):
    import app as application
    import database.db as db
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "provider.db"))
    db.init_db()
    for name in ("gpt_expLab_api", "EXPLABS_API_KEY", "EXPLABS_MODEL", "GEMINI_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(application.ollama_client, "ollama_status", lambda *a: {"available": False, "models": [], "error": "offline"})
    with TestClient(application.app) as test_client:
        yield test_client


@pytest.mark.parametrize("key_name", ["gpt_expLab_api", "EXPLABS_API_KEY"])
def test_luna_routing_and_deterministic_analysis(client, monkeypatch, image_bytes, key_name):
    import app as application
    monkeypatch.setenv(key_name, "secret")
    monkeypatch.setenv("GEMINI_API_KEY", "other-secret")
    extraction = Mock(return_value={"success": True, "data": {"references": ["PO # 12345"], "raw_text": ["PO # 12345"]}, "error": None})
    monkeypatch.setattr(provider, "extract_bol", extraction)
    gemini = Mock(side_effect=AssertionError("Must select Luna"))
    monkeypatch.setattr(application.ollama_client, "extract_bol_with_gemini", gemini)
    response = client.post("/api/analyze/image", files={"file": ("bol.png", image_bytes, "image/png")})
    assert response.status_code == 200
    result = response.json()
    assert result["vision_provider"] == "experiential"
    assert result["vision_model"] == "gpt-5.6-luna"
    assert result["fields"]["references"] == "PO # 12345"
    assert any(e["code"] == "MPO" and e["value"] == "12345" for e in result["entries"])
    extraction.assert_called_once_with("secret", image_bytes, "gpt-5.6-luna")
    gemini.assert_not_called()
    status = client.get("/api/ollama/status").json()
    assert status["experiential_configured"]
    assert "secret" not in str(status)


def test_provider_failure_falls_through_to_local_when_available(client, monkeypatch, image_bytes):
    monkeypatch.setenv("gpt_expLab_api", "secret")
    monkeypatch.setattr(provider, "extract_bol", lambda *a: {"success": False, "data": None, "error": "Experiential Labs returned HTTP 401."})
    response = client.post("/api/analyze/image", files={"file": ("bol.png", image_bytes, "image/png")})
    assert response.status_code == 503
    assert "401" in response.json()["detail"]


def test_credential_and_model_defaults(client, monkeypatch):
    assert not client.get("/api/ollama/status").json()["experiential_configured"]
    monkeypatch.setenv("EXPLABS_API_KEY", "alias")
    monkeypatch.setenv("gpt_expLab_api", " preferred ")
    assert provider.api_key() == "preferred"
    monkeypatch.setenv("gpt_expLab_api", " ")
    assert provider.api_key() == "alias"
    monkeypatch.setenv("EXPLABS_MODEL", " ")
    assert provider.model_name() == "gpt-5.6-luna"
