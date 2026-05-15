# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Architecture

Multi-agent code review system using LangGraph orchestration with three parallel LLM workers + one orchestrator. Backend is FastAPI, frontend is a single-page HTML/CSS/JS file with hash-based routing.

**Review pipeline**: `start → [security_worker ‖ performance_worker ‖ business_logic_worker] → orchestrator → END`

- `agents/graph.py` — LangGraph StateGraph builder, parallel fan-out to workers, orchestrator merge with dedup + diff generation
- `agents/workers.py` — Three worker prompts (security, performance, business logic), each calls LLM via `chat_with_lint_context`
- `agents/state.py` — `ReviewState` TypedDict shared across all graph nodes
- `utils/llm_client.py` — Unified OpenAI SDK wrapper supporting Mimo and DeepSeek providers with auto-fallback on failure
- `config.py` — pydantic-settings: reads env vars first, `.env` file second (`.env` may be absent in Docker)
- `database/models.py` — SQLAlchemy models: `ReviewTask` (1) → `ReviewReport` (N), cascade delete
- `database/crud.py` — Task CRUD: create_task, update_task_status, save_report, get_task, get_history, delete_task
- `tools/code_linter.py` — flake8 + pylint via subprocess on temp files
- `main.py` — FastAPI: `/api/review` (POST), `/api/review/{task_id}` (GET/DELETE), `/api/history` (GET); serves `static/` with `StaticFiles`; root route returns SPA
- `static/index.html` — Complete SPA (no build step): home page, review input (3 modes), progress page with 7-stage pipeline animation, results with findings/diff/fixed-code tabs, history page

## Running locally

```bash
pip install -r requirements.txt
python main.py          # FastAPI on :8000, serves SPA at /
```

## Docker deployment

```bash
docker compose up -d    # reads .env for API keys, mounts volume for SQLite
```

`.env` must contain valid `MIMO_API_KEY` / `DEEPSEEK_API_KEY` and `PRIMARY_PROVIDER`. DB path inside container is `/data/code_review.db`.

## Key design choices

- **Frontend is a single HTML file** — no framework, no build step. The SPA connects to API via relative paths (`/api/*`), so same-origin deployment works without CORS issues.
- **LLM fallback chain** — If primary provider fails after max_retries, the client automatically tries the secondary provider. No manual intervention needed.
- **Review tasks run via FastAPI BackgroundTasks** — `run_review()` invokes the LangGraph graph synchronously in the background. The frontend polls `GET /api/review/{task_id}` every 2s during review.
- **Progress page animation is time-based simulation** — The 7-stage pipeline in the SPA advances based on elapsed seconds, not real backend events (since LangGraph invocations are blocking). Stages: ①代码输入 → ②代码解析 → ③静态分析 → ④AgentTeam并行 → ⑤汇总决策 → ⑥修复方案 → ⑦报告存档.
- **Orchestrator output is strict JSON** — The orchestrator prompt enforces a specific JSON schema with `json_mode=True`. Findings include `severity`, `line`, `category`, `code_snippet`, `description`, `suggestion`, `found_by`.
