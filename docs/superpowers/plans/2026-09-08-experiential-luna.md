# Experiential Labs Luna integration

Goal: use the user's selected `gpt-5.6-luna` model for BOL image extraction with the existing `gpt_expLab_api` production variable.

Design: a small provider client uses the existing extraction prompt and image preprocessing, calls the fixed Experiential Labs Chat Completions endpoint, and returns the existing success/data/error structure. Prefer this provider when configured, then Gemini when configured, then local Ollama. Do not silently switch providers after a failed request. Keep deterministic M-Code analysis authoritative. An environment key indicates configuration, not verified connectivity.

Alternatives considered: replacing Gemini would remove a working option; adding a provider picker introduces unnecessary configuration for this request. Automatic selection from configured credentials fits the existing app.

Implementation steps:
- [x] Add `engine/experiential_client.py`: read `gpt_expLab_api` (also support `EXPLABS_API_KEY`), default model `gpt-5.6-luna`, Bearer authentication, JPEG image content, JSON response parsing, sanitized failures.
- [x] Update `app.py` hosted extraction branch and status metadata, preserving PDF/local flows.
- [x] Update provider indicators and cloud-processing descriptions in existing templates and README.
- [x] Test request format, errors, credential precedence, provider selection and deterministic pipeline with mocked HTTP and isolated SQLite. Run full pytest suite, compile and Vercel import checks.

Verification: 178 tests passed; Python compilation and Vercel entrypoint import passed. Initial routing test used only raw_text, which is not a structured engine input; corrected the fixture to include the extraction schema's references field. Hosted responses now normalize lists through the existing field mapper and return fields/confidence for the review form.

Live verification requires the deployment credentials/environment; the local workspace currently has neither provider key. Do not report mocked checks as a live model call or a Vercel build.
