# QA Test Generator

A QA agent that takes a functional specification document (Word/PDF/text), splits it into business blocks, generates structured functional tests (JSON) per block via LLM sub-agents, iterates with an independent judge, and exposes everything in a FastAPI + HTMX web interface with human-in-the-loop and local git versioning.

## Architecture

```
test-generation-interface/
├── main.py                    # FastAPI app, routes, SSE
├── config.py                  # pydantic-settings configuration
├── agents/
│   ├── orchestrator.py        # Main pipeline coordinator
│   ├── extractor.py           # Business rule extraction
│   ├── generator.py           # Test JSON generation
│   ├── judge.py               # Coverage validation
│   └── planner.py             # Complex instruction decomposition
├── services/
│   ├── llm.py                 # ICA/OpenAI async client
│   ├── doc_parser.py          # Word/PDF/text parsing
│   ├── git_service.py         # Async git with asyncio.Lock
│   └── state_manager.py       # JSON state persistence
├── prompts/                   # System prompts for each agent role
├── templates/                 # Jinja2 + HTMX templates
├── static/style.css           # Minimal utility CSS
└── schemas/test_schema.json   # JSON Schema for test validation
```

## Setup

```bash
# Copy environment config
cp .env.example .env
# Edit .env: set ICA_API_KEY

# Install with uv
uv sync

# Run
uv run uvicorn main:app --reload
```

Open `http://localhost:8000`.

## Configuration (.env)

| Variable | Default | Description |
|---|---|---|
| `ICA_BASE_URL` | `https://api.nextgen-beta.ica.ibm.com/ica/v1` | ICA API endpoint |
| `ICA_API_KEY` | — | Bearer token (required) |
| `MODEL_GENERATOR` | `gemma-4-26b-a4b-it` | LLM for extraction + generation |
| `MODEL_JUDGE` | `ibm/granite-4-h-small` | LLM for coverage evaluation |
| `MAX_JUDGE_PASSES` | `3` | Max judge/generator iterations per bloc |
| `MAX_CONTEXT_TOKENS` | `128000` | Minimum required context window |
| `PROJECTS_DIR` | `./projects` | Where projects are stored |

## Pipeline

```
Upload doc
    → Parse (Word/PDF/text)
    → Split into blocs
    → [HUMAN CHECKPOINT] validate split
    → For each bloc (parallel):
        EXTRACTOR → business rules (JSON)
        GENERATOR → functional tests (JSON)
        JUDGE loop (max 3 passes):
            JUDGE evaluates coverage
            if gaps → GENERATOR regenerates targeting gaps
            if ok → done
        if max passes reached → needs_human
    → Human can edit tests, chat, rollback
    → Export ZIP
```

## Agent Roles

All agents use **fresh context** (no conversation history). Context is reconstructed from `state.json` on each call.

| Agent | Model | Role |
|---|---|---|
| EXTRACTOR | generator | Extract explicit + implicit business rules from a text chunk |
| GENERATOR | generator | Generate functional tests covering all rules |
| JUDGE | judge | Find gaps and missing coverage (never validates if in doubt) |
| PLANNER | generator | Decompose complex human chat instructions into steps |

## API Routes

| Method | Path | Description |
|---|---|---|
| `GET` | `/` | Home page, upload form, recent projects |
| `POST` | `/upload` | Upload doc, create project |
| `GET` | `/projects/{id}` | Project UI (tabbed) |
| `GET` | `/projects/{id}/stream` | SSE event stream |
| `POST` | `/projects/{id}/validate-split` | Human validates bloc split |
| `POST` | `/projects/{id}/run` | Start pipeline |
| `POST` | `/projects/{id}/blocs/{bloc_id}/rerun` | Rerun one bloc |
| `GET` | `/projects/{id}/tests` | All tests JSON |
| `PUT` | `/projects/{id}/tests/{test_id}` | Update one test |
| `POST` | `/projects/{id}/chat` | Chat with QA agent |
| `GET` | `/projects/{id}/history` | Git log |
| `POST` | `/projects/{id}/rollback` | Rollback to commit hash |
| `GET` | `/projects/{id}/export` | Download ZIP |

## Git Commit Convention

```
init:           project initialization
feat(doc):      document uploaded and parsed
feat(blocs):    block split validated by human
feat(bloc-X):   business rules extracted
feat(bloc-X):   tests generated v1
feat(bloc-X):   judge iteration pass N
fix(bloc-X):    human modification via chat
feat(bloc-X):   human validation
export:         final JSON export
```

## Test JSON Schema

```json
{
  "id": "TEST-001",
  "bloc_id": "bloc-1",
  "business_rule": "Un utilisateur non authentifié...",
  "name": "Accès refusé sans authentification",
  "description": "Vérifie que...",
  "steps": [
    { "order": 1, "description": "...", "expected_result": "..." }
  ],
  "status": "draft",
  "created_at": "2025-01-01T00:00:00Z",
  "updated_at": "2025-01-01T00:00:00Z"
}
```

## Error Handling

| Situation | Behavior |
|---|---|
| Model context < 128k | Startup error, explicit message |
| Malformed JSON from LLM | Retry 3x with correction prompt |
| Judge loop exhausted | `needs_human` status on bloc |
| LLM timeout | Retry 2x, then `error` status |
| Git rollback | Full state reload |
| Chat out of scope | Agent refuses and explains |
