# Agent Runtime V2 (Non-LLM Phase)

## Goal

Introduce a QueryEngine-style runtime core without breaking the existing supervisor flow.

## Runtime Mode

- Runtime is now `v2_only` (no v1 dual-stack path).

## New Core Components

- `backend/app/agent/runtime/engine.py`
  - `AgentRuntime.run(request, db, current_user) -> AsyncIterator[event]`
- `backend/app/agent/runtime/types.py`
  - `RuntimeRequest`, `RuntimeState`, `RuntimeEvent`
- `backend/app/agent/runtime/task_store.py`
  - unified task lifecycle: `pending -> running -> completed|failed|killed`
- `backend/app/agent/runtime/tool_registry.py`
  - explicit `ToolSpec` registration and unified `ToolResultEnvelope`
- `backend/app/agent/runtime/permission_gate.py`
  - per-tool decision: `allow|deny|ask`
- `backend/app/agent/runtime/agent_definitions.py`
  - built-in definitions + controlled local extension loading

## SSE Protocol Upgrade

`/api/v1/chat/stream` now emits compatibility fields on every event:

- `event_id`
- `sequence_num`
- `trace_id`
- `source`
- `degraded`
- `fallback_reason`

Resume support:

- Query replay: `resume_trace_id` + `last_sequence`
- Standard header replay: `Last-Event-ID: <trace_id>:<sequence_num>`

## New Admin Runtime APIs

- `GET /api/v1/admin/runtime/tasks`
- `GET /api/v1/admin/runtime/metrics`
- `GET /api/v1/admin/runtime/tool-decisions`
- `GET /api/v1/admin/runtime/tool-decisions/summary`
- `POST /api/v1/admin/runtime/replay?trace_id=...`
- `POST /api/v1/admin/security/watermark/trace`

`/runtime/tool-decisions` supports `source=redis|audit|merged` (default `merged`).
Runtime decisions are written to both Redis stream and `security_audit_events`.

`/runtime/tool-decisions/summary` supports:

- window filter: `since_hours`
- dimension filters: `decision`, `tool_name`, `reason`, `source`
- matrix outputs: `matrix_by_tool`, `matrix_by_reason`
- trend output: `trend_by_hour`

## Maintenance

Replay/task TTL maintenance script:

- `py -3 scripts/runtime_maintenance.py`
- `py -3 scripts/runtime_maintenance.py --cleanup-empty`
- `py -3 scripts/runtime_maintenance.py --cleanup-empty --write-report`

Performance baseline report script:

- `py -3 scripts/performance_baseline_report.py`

## Compatibility

- Runtime v2 is the single production chain.
