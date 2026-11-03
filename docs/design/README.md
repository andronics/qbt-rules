# Design records

Why the code is the way it is. Copy [0000-template.md](0000-template.md) to `NNNN-short-title.md` before a
new feature, a new dependency, or a public-interface change, and add a line below. Status moves Proposed →
Approved (by a human) → Implemented; supersede an implemented record with a new one, never rewrite it.

**Index:** read this first, then open only the records relevant to your task. CI checks that every record is listed.

| # | Title | Status | Decision in one line |
|---|---|---|---|
| [0001](0001-config-on-interpose.md) | Configuration on interpose, config in /etc/qbt-rules, state in /var/lib/qbt-rules | Approved | interpose settings keeping every variable name; new paths only; starts with no configuration |
| [0002](0002-fastapi.md) | The JSON API on FastAPI and uvicorn | Proposed | Byte-compatible JSON, ISO timestamps, `{error, message}` errors, Starlette sessions, one uvicorn process; the dashboard on FastAPI with relative URLs (4d) |
