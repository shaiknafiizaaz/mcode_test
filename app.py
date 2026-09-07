"""R+L Carriers BOL / Tenet-EBS Job Assistant - FastAPI application.

LOCAL-FIRST: no external APIs, no telemetry, no cloud storage. The core
M-Code system works fully offline; Ollama (if available) is used ONLY
for image extraction and is never the authority for M-Codes.

Run with:  python -m uvicorn app:app --host 127.0.0.1 --port 8000
or double-click start.bat
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from starlette.requests import Request

import database.db as db
from engine import bol_parser, mcode_engine, ollama_client
from engine.rules_loader import code_category, load_mcodes, load_rules
from engine.validation import build_result

load_mcodes()  # Fail startup before serving any request if authoritative rules are invalid.
db.init_db()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
DEFAULT_CONFIG = {"host": "127.0.0.1", "port": 8000}


def load_config() -> Dict[str, Any]:
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
            cfg = json.load(fh)
        merged = dict(DEFAULT_CONFIG)
        merged.update(cfg)
        return merged
    except (OSError, json.JSONDecodeError):
        return dict(DEFAULT_CONFIG)


CONFIG = load_config()

app = FastAPI(title="R+L BOL / Tenet Assistant", version="1.0.0")
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

ALLOWED_IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}
ALLOWED_UPLOAD_EXT = ALLOWED_IMAGE_EXT | {".pdf"}


# ---------------------------------------------------------------------------
# Request models (validated API input)
# ---------------------------------------------------------------------------

class AnalyzeRequest(BaseModel):
    text: str = Field(default="", max_length=200000)
    fields: Dict[str, Any] = Field(default_factory=dict)
    source_type: str = Field(default="paste", pattern="^(paste|manual|image)$")


class RecordAnswerRequest(BaseModel):
    code: str = Field(min_length=1, max_length=10)
    correct: bool


class MockSessionRequest(BaseModel):
    mode: str = Field(min_length=1, max_length=30)
    category: str = Field(min_length=1, max_length=30)
    total: int = Field(ge=1, le=500)
    correct: int = Field(ge=0, le=500)


class SettingsRequest(BaseModel):
    settings: Dict[str, Any]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def run_pipeline(lines: List[Dict[str, str]], source_type: str, preview: str) -> Dict[str, Any]:
    engine_result = mcode_engine.analyze_lines(lines)
    return build_result(lines, engine_result, source_type=source_type, input_preview=preview)


def _search_mcodes(query: str, limit: int = 25) -> List[Dict[str, Any]]:
    q = query.strip().lower()
    if not q:
        return []
    q_up = q.upper()
    results: List[tuple] = []
    for code in load_mcodes():
        c = code["code"].upper()
        meaning = code.get("meaning", "").lower()
        triggers = [t.lower() for t in code.get("triggers", [])]
        score = None
        if q_up == c:
            score = 0
        elif c.startswith(q_up):
            score = 1
        elif q_up in c:
            score = 2
        elif any(t == q for t in triggers):
            score = 3
        elif any(q in t for t in triggers):
            score = 4
        elif q in meaning:
            score = 5
        elif q_up in c or any(q in t for t in triggers):
            score = 6
        if score is not None:
            results.append((score, c, code))
    results.sort(key=lambda x: (x[0], x[1]))
    out = []
    for _, c, code in results[:limit]:
        out.append({
            "code": c,
            "meaning": code.get("meaning", ""),
            "category": code.get("category", ""),
            "triggers": code.get("triggers", []),
            "example": code.get("example", ""),
        })
    return out


def _build_mock_questions(mode: str, category: str, count: int) -> List[Dict[str, Any]]:
    import random
    codes = load_mcodes()
    if category and category != "All Categories":
        codes = [c for c in codes if code_category(c["category"]) == category]
    if mode == "wrong":
        weak = db.get_weak_codes()
        weak_codes = {w["code"] for w in weak}
        pool = [c for c in codes if c["code"].upper() in weak_codes]
        if not pool:
            pool = codes
    else:
        pool = codes

    random.shuffle(pool)
    n = count if 0 < count <= len(pool) else len(pool)
    questions = []
    for code in pool[:n]:
        # Short triggers can intentionally overlap. The authoritative meaning
        # supplies the complete timing/phone/side context for an unambiguous quiz.
        wording = code["meaning"].upper()
        prompt_kind = "meaning"
        questions.append({
            "code": code["code"].upper(),
            "meaning": code.get("meaning", ""),
            "category": code.get("category", ""),
            "prompt": wording,
            "prompt_kind": prompt_kind,
            "example": code.get("example", ""),
        })
    return questions


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def page_index(request: Request):
    return templates.TemplateResponse(request=request, name="index.html", context={"page": "index"})


@app.get("/assistant", response_class=HTMLResponse)
def page_assistant(request: Request):
    return templates.TemplateResponse(request=request, name="assistant.html", context={"page": "assistant"})


@app.get("/manual", response_class=HTMLResponse)
def page_manual(request: Request):
    return templates.TemplateResponse(request=request, name="manual.html", context={"page": "manual"})


@app.get("/search", response_class=HTMLResponse)
def page_search(request: Request):
    return templates.TemplateResponse(request=request, name="search.html", context={"page": "search"})


@app.get("/mock-test", response_class=HTMLResponse)
def page_mock_test(request: Request):
    return templates.TemplateResponse(request=request, name="mock_test.html", context={"page": "mock-test"})


@app.get("/master", response_class=HTMLResponse)
def page_master(request: Request):
    return templates.TemplateResponse(request=request, name="master.html", context={"page": "master"})


@app.get("/history", response_class=HTMLResponse)
def page_history(request: Request):
    return templates.TemplateResponse(request=request, name="history.html", context={"page": "history"})


@app.get("/settings", response_class=HTMLResponse)
def page_settings(request: Request):
    return templates.TemplateResponse(request=request, name="settings.html", context={"page": "settings"})


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

@app.get("/api/health")
def api_health():
    return {"status": "ok", "local_mode": True, "version": "1.0.0"}


@app.get("/api/mcodes")
def api_mcodes():
    codes = []
    for c in load_mcodes():
        codes.append({
            "code": c["code"].upper(),
            "meaning": c.get("meaning", ""),
            "category": c.get("category", ""),
            "test_category": code_category(c.get("category", "")),
            "triggers": c.get("triggers", []),
            "example": c.get("example", ""),
        })
    return {"count": len(codes), "codes": codes, "categories": list(load_rules("mcodes")["categories"].values())}


@app.get("/api/search")
def api_search(q: str = Query(default="", max_length=100)):
    return {"query": q, "results": _search_mcodes(q)}


@app.post("/api/analyze")
def api_analyze(req: AnalyzeRequest):
    """Run the deterministic engine over pasted text or structured fields."""
    if req.fields:
        # Manual entry or corrected image-extraction fields.
        lines = bol_parser.lines_from_fields(req.fields)
        preview = " | ".join(str(v)[:40] for v in req.fields.values() if str(v).strip())[:500]
    elif req.source_type == "manual":
        raise HTTPException(status_code=400, detail="Manual analysis requires fields.")
    else:
        text = req.text.strip()
        if not text:
            raise HTTPException(status_code=400, detail="No BOL text provided.")
        parsed = bol_parser.parse_text(text)
        lines = parsed["lines"]
        preview = text[:500]

    result = run_pipeline(lines, req.source_type, preview)
    save_history(req.source_type, preview, result)
    return JSONResponse(result)


def save_history(source_type: str, preview: str, result: Dict[str, Any]) -> None:
    suggested = [{"code": s["code"], "value": s["value"]} for s in result.get("suggested_entries", [])]
    db.add_history(
        input_type=source_type,
        input_preview=preview,
        detected_fields=result.get("detected_categories", []),
        suggested_codes=suggested,
        warnings=result.get("warnings", []),
    )


@app.post("/api/analyze/image")
async def api_analyze_image(file: UploadFile = File(...)):
    """Upload a BOL image (or PDF) and extract + analyze locally.

    Extraction is done by the local Ollama vision model if available;
    the deterministic rule engine decides all M-Codes.
    """
    filename = file.filename or "upload"
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ALLOWED_UPLOAD_EXT:
        raise HTTPException(status_code=400, detail=f"Unsupported file type '{ext}'. Use PNG, JPG, JPEG, WEBP or PDF.")

    raw = await file.read()
    if len(raw) > 15 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large (max 15 MB).")

    # PDFs: extract embedded text (scans must be converted to images).
    if ext == ".pdf":
        pdf_result = ollama_client.extract_text_from_pdf(raw)
        if not pdf_result["success"]:
            raise HTTPException(status_code=422, detail=pdf_result["error"])
        parsed = bol_parser.parse_text(pdf_result["data"])
        result = run_pipeline(parsed["lines"], "image", f"PDF: {filename} (text extraction)")
        result["extracted"] = {"raw_text": pdf_result["data"]}
        result["ollama"] = None
        result["vision_model"] = None
        save_history("image", f"PDF: {filename}", result)
        return JSONResponse(result)

    # Image path. Prefer hosted Gemini on Vercel; fall back to local Ollama.
    gemini_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if gemini_key:
        extraction = ollama_client.extract_bol_with_gemini(
            gemini_key, raw, os.environ.get("GEMINI_MODEL", ollama_client.DEFAULT_GEMINI_MODEL)
        )
        if not extraction["success"]:
            raise HTTPException(status_code=502, detail=extraction["error"])
        extracted = extraction["data"]
        fields = dict(extracted)
        if isinstance(fields.get("contacts"), list) and not fields.get("contact_information"):
            fields["contact_information"] = "\n".join(str(v) for v in fields["contacts"])
        if isinstance(fields.get("raw_text"), list) and not fields.get("raw_text_text"):
            fields["raw_text_text"] = "\n".join(str(v) for v in fields["raw_text"])
        lines = bol_parser.lines_from_fields(fields)
        result = run_pipeline(lines, "image", f"Gemini extraction: {filename}")
        result["extracted"] = extracted
        result["ollama"] = None
        result["vision_model"] = os.environ.get("GEMINI_MODEL", ollama_client.DEFAULT_GEMINI_MODEL)
        result["vision_provider"] = "gemini"
        save_history("image", f"Gemini extraction: {filename}", result)
        return JSONResponse(result)

    # Local image path.
    status = ollama_client.ollama_status(db.get_setting("ollama_url", ollama_client.DEFAULT_OLLAMA_URL))
    if not status["available"]:
        raise HTTPException(
            status_code=503,
            detail=(
                "Ollama is not running, so local image extraction is unavailable. "
                "Start Ollama (ollama serve) or use the Paste Text / Manual Entry tabs - "
                "the core M-Code system works fully offline. "
                f"({status.get('error')})"
            ),
        )
    model = ollama_client.pick_vision_model(status["models"], db.get_setting("vision_model", ""))
    if not model:
        raise HTTPException(
            status_code=503,
            detail=(
                "No vision model installed. Install one with:  ollama pull qwen2.5vl "
                "then retry. Installed models: " + ", ".join(status["models"] or ["(none)"])
            ),
        )

    extraction = ollama_client.extract_bol_from_image(
        db.get_setting("ollama_url", ollama_client.DEFAULT_OLLAMA_URL), model, raw
    )
    if not extraction["success"]:
        raise HTTPException(status_code=502, detail=extraction["error"])

    data = extraction["data"]
    fields = _extraction_to_fields(data)
    lines = bol_parser.lines_from_fields(fields)
    result = run_pipeline(lines, "image", f"Image: {filename}")
    result["extracted"] = data
    result["fields"] = fields
    result["ollama"] = {"available": True, "model": model}
    result["vision_model"] = model
    result["confidence"] = _confidence_summary(data)
    save_history("image", f"Image: {filename}", result)
    return JSONResponse(result)


def _extraction_to_fields(data: Dict[str, Any]) -> Dict[str, str]:
    """Map vision-model JSON to the manual-entry field shape."""
    def first(x: Any) -> str:
        if isinstance(x, list):
            return "\n".join(str(i) for i in x if str(i).strip())
        return str(x or "").strip()

    def join_list(x: Any) -> str:
        if isinstance(x, list):
            return "\n".join(str(i).strip() for i in x if str(i).strip())
        return str(x or "").strip()

    return {
        "shipper": first(data.get("shipper")),
        "consignee": first(data.get("consignee")),
        "attn": first(data.get("attn")),
        "bill_to": first(data.get("bill_to")),
        "freight_terms": first(data.get("freight_terms")),
        "pro_number": first(data.get("pro_number")),
        "handling_units": first(data.get("handling_units")),
        "pieces": first(data.get("pieces")),
        "weight": first(data.get("weight")),
        "description": first(data.get("description")),
        "nmfc": first(data.get("nmfc")),
        "class": first(data.get("class")),
        "references": join_list(data.get("references")),
        "special_instructions": join_list(data.get("special_instructions")),
        "contact_information": join_list(data.get("contacts")),
        "delivery_instructions": join_list(data.get("dates")),
    }


def _confidence_summary(data: Dict[str, Any]) -> Dict[str, str]:
    """Heuristic confidence per extracted section (HIGH/MEDIUM/LOW)."""
    summary = {}
    for key in ("shipper", "consignee", "attn", "handling_units", "freight_terms", "description", "nmfc", "class"):
        val = data.get(key)
        if isinstance(val, list):
            val = " ".join(str(v) for v in val)
        val = str(val or "").strip()
        if not val:
            summary[key] = "LOW"
        elif len(val) >= 4:
            summary[key] = "HIGH"
        else:
            summary[key] = "MEDIUM"
    for key in ("references", "special_instructions", "raw_text"):
        val = data.get(key)
        n = len(val) if isinstance(val, list) else (1 if str(val or "").strip() else 0)
        summary[key] = "HIGH" if n >= 2 else ("MEDIUM" if n == 1 else "LOW")
    return summary


@app.get("/api/ollama/status")
def api_ollama_status():
    status = ollama_client.ollama_status(db.get_setting("ollama_url", ollama_client.DEFAULT_OLLAMA_URL))
    model = None
    if status["available"]:
        model = ollama_client.pick_vision_model(status["models"], db.get_setting("vision_model", ""))
    return {
        "available": status["available"],
        "models": status["models"],
        "vision_model": model,
        "error": status["error"],
        "gemini_configured": bool(os.environ.get("GEMINI_API_KEY", "").strip()),
        "gemini_model": os.environ.get("GEMINI_MODEL", ollama_client.DEFAULT_GEMINI_MODEL),
    }


# ---------------------------------------------------------------------------
# Mock test
# ---------------------------------------------------------------------------

@app.get("/api/mock/questions")
def api_mock_questions(
    mode: str = Query(default="practice", max_length=30),
    category: str = Query(default="All Categories", max_length=30),
    count: int = Query(default=10, ge=1, le=500),
):
    return {"questions": _build_mock_questions(mode, category, count)}


@app.post("/api/mock/record")
def api_mock_record(req: RecordAnswerRequest):
    if req.code.upper() not in {c['code'] for c in load_mcodes()}:
        raise HTTPException(status_code=422, detail="Unknown authoritative M-Code")
    db.record_answer(req.code.upper(), req.correct)
    return {"ok": True}


@app.post("/api/mock/session")
def api_mock_session(req: MockSessionRequest):
    if req.correct > req.total:
        raise HTTPException(status_code=422, detail="Correct answers cannot exceed total")
    return db.add_mock_session(req.mode, req.category, req.total, req.correct)


@app.get("/api/mock/weak")
def api_mock_weak():
    return {"weak_codes": db.get_weak_codes()}


# ---------------------------------------------------------------------------
# Stats / history
# ---------------------------------------------------------------------------

@app.get("/api/stats")
def api_stats():
    return db.get_learning_stats()


@app.get("/api/history")
def api_history(search: str = Query(default="", max_length=100)):
    return {"history": db.list_history(search)}


@app.delete("/api/history/{history_id}")
def api_history_delete(history_id: int):
    if not db.delete_history(history_id):
        raise HTTPException(status_code=404, detail="History entry not found.")
    return {"ok": True}


@app.post("/api/history/clear")
def api_history_clear():
    db.clear_history()
    return {"ok": True}


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

@app.get("/api/settings")
def api_get_settings():
    return {
        "settings": db.get_all_settings(),
        "config": CONFIG,
        "ollama": api_ollama_status(),
    }


@app.post("/api/settings")
def api_set_settings(req: SettingsRequest):
    allowed_keys = {"ollama_url", "vision_model", "save_images"}
    for key, value in req.settings.items():
        if key in allowed_keys:
            db.set_setting(key, value)
    return {"ok": True, "settings": db.get_all_settings()}


@app.get("/api/local-mode")
def api_local_mode():
    return {"local_mode": True, "message": "LOCAL MODE - all processing happens on this computer. No cloud upload."}


if __name__ == "__main__":
    import uvicorn
    db.init_db()
    uvicorn.run(app, host=CONFIG.get("host", "127.0.0.1"), port=int(CONFIG.get("port", 8000)))
