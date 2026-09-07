# R+L Carriers BOL / Tenet-EBS Job Assistant

A **100% local** Windows application that helps you learn and apply R+L
Carriers M-Codes while processing Bills of Lading (BOL) in Tenet/EBS.

**Accuracy > Automation > Appearance.** The application **never invents an
M-Code**. Every suggestion shows *why* it was generated (source text,
matched trigger, rule source, confidence). When something cannot be
determined safely it returns **VERIFY** instead of guessing.

## How to start

Double-click **`start.bat`**. It checks Python, installs dependencies if
needed, checks Ollama, starts the FastAPI server and opens:

    http://127.0.0.1:8000

No cloud accounts. No API keys. No telemetry. Local processing only.

## Internet / phone access

For access from a phone, deploy the included `Dockerfile` to an HTTPS host
such as Render, Railway, Fly.io, or a private VPS. Set the service start
command to the Docker default and expose port 8000. The browser camera can
upload images through the existing image-upload screen once the site is served
over HTTPS. Set `TENET_DB_PATH` to a mounted persistent disk in production so
history and practice progress survive restarts.

The deterministic M-Code engine, search, manual entry, paste analysis and
reference extraction run in the container without Ollama. Image OCR remains an
optional enhancement: install or host a compatible Ollama vision model and set
the Ollama URL in Settings. Do not expose an unauthenticated Ollama endpoint
directly to the public internet.

## Architecture

```
BOL IMAGE/TEXT
      |
      v
INFORMATION EXTRACTION      (parser + optional local Ollama vision OCR)
      |
      v
STRUCTURED DATA
      |
      v
DETERMINISTIC RULE ENGINE   (engine/*.py)
      |
      v
AUTHORITATIVE M-CODE DATABASE  (data/mcode_rules.json)
      |
      v
VALIDATION                  (statuses, conflicts, traceability)
      |
      v
SUGGESTED TENET/EBS ENTRIES
```

The vision model is used for **extraction only** - it is never asked to
decide an M-Code, and the core M-Code system works fully offline even
when Ollama is not running.

## Project structure

```
rl-tenet-assistant/
|-- app.py                  FastAPI app (routes + JSON API)
|-- requirements.txt
|-- README.md
|-- start.bat               double-click launcher
|-- config.json             host/port
|-- data/
|   |-- mcode_rules.json        AUTHORITATIVE M-Code database (102 codes)
|   |-- payment_rules.json      payment terms
|   |-- description_rules.json  FLUSH -> NMFC/ITEM -> CLASS -> R LINE -> RDG
|   `-- training_examples.json  canonical wording examples
|-- engine/
|   |-- bol_parser.py       section-aware BOL text parsing
|   |-- mcode_engine.py     deterministic M-Code rule engine
|   |-- handling_units.py   MM pallet/handling-unit engine (MM is NOT NMFC)
|   |-- payment_engine.py   explicit payment terms only
|   |-- description_engine.py  description processing priority
|   |-- reference_engine.py labeled reference/value extraction
|   |-- validation.py       statuses, conflicts, suggested entries
|   `-- ollama_client.py    local Ollama vision extraction
|-- database/
|   `-- db.py               SQLite: history, code stats, mock sessions
|-- templates/              HTML pages (Jinja2)
|-- static/css, static/js   styles + vanilla JS
`-- tests/                  pytest suite
```

## Status semantics

| Status        | Color  | Meaning                                            |
|---------------|--------|----------------------------------------------------|
| CONFIRMED     | green  | deterministic rule matched with all required data  |
| VERIFY        | orange | matched, but something must be double-checked      |
| NOT DETECTED  | gray   | nothing found for that category                    |
| CONFLICT      | red    | contradictory instructions both present            |

## Key rules encoded

- `MM` = pallet / master handling-unit information (`1 PALLET` -> `MM 1 PLT`,
  `2 SKIDS` -> `MM 2 SKDS`). **MM is NOT NMFC** - NMFC values are never
  converted into MM entries.
- Appointment vs call-before: `CALL FOR APPOINTMENT` + phone -> `MCA`,
  without phone -> `MCFA`; `CALL BEFORE DELIVERY` + phone -> `MCALLB`,
  without phone -> `MBEFOR`; time-specific rules (24/48/72 hrs) take
  precedence (`M24`, `M48H`, `M1HO`, `M2B4`, `MADV`, `M48`, `M72A`).
- `MA` = actual ATTN/contact **person**. Generic departments (PARTS,
  RECEIVING, SHIPPING, ...) never become MA - they raise a VERIFY warning.
- Payment terms are only CONFIRMED when explicitly printed; otherwise
  VERIFY WITH TRAINER.

## Tests

```
python -m pytest tests/ -v
```

## Privacy

LOCAL MODE by default: no analytics, no telemetry, no external APIs, no
cloud storage. Uploaded BOL images are processed in memory and are not
saved unless you enable "save images" in Settings.
## Rule integrity and completion audit

Run `python audit.py` to validate the authoritative dataset, run every automated
test, probe the local Ollama installation, and regenerate `audit_report.json`.
The command returns a failure status if tests, validation or offline checks fail.
The report includes individual test outcomes and the rule-file hash so its
results can be tied to the tested dataset. Rerun it after changing any rules.

`data/mcode_rules.json` contains the code meanings, triggers, extraction patterns,
service directions, timing families, phone requirements, contextual roles and
display ranks. Application modules interpret this file; the UI and mock questions
consume it through the API. Restart the server after editing rules. Invalid
rules stop startup with a descriptive validation error.

Priorities are explicit: exact context, timing, side, exact phrase, structured
label, partial/fuzzy, then verification. Equal incompatible candidates remain
CONFLICT and are excluded from the copy panel. Intentional shared triggers have
contextual precedence documentation in the JSON. Mock questions use full
meanings so an ambiguous short trigger is never presented without its context.

Offline tests remove API keys/tokens from their process environment and deny
application socket connections, including Ollama. They exercise both analyzer
inputs, the acceptance BOL, search, master data, history, practice, wrong answers
and weak-code learning using temporary SQLite databases. A separate child process
checks real server startup under the same network restriction. Windows asyncio's
internal socketpair is permitted; host networking and running Ollama processes
are not changed. Ollama availability in the audit is a separate live local probe.

For isolated deployments or testing, `TENET_DB_PATH` selects a different SQLite
file. The default remains `database/app.db`.
