# Design records

Why the code is the way it is. Copy [0000-template.md](0000-template.md) to `NNNN-short-title.md` before a
new feature, a new dependency, or a public-interface change, and add a line below. Status moves Proposed →
Approved (by a human) → Implemented; supersede an implemented record with a new one, never rewrite it.

**Index:** read this first, then open only the records relevant to your task. CI checks that every record is listed.

| # | Title | Status | Decision in one line |
|---|---|---|---|
| [0001](0001-config-on-interpose.md) | Configuration on interpose, config in /etc/qbt-rules, state in /var/lib/qbt-rules | Approved | interpose settings keeping every variable name; new paths only; starts with no configuration |
| [0002](0002-fastapi.md) | The JSON API on FastAPI and uvicorn | Proposed | Byte-compatible JSON, ISO timestamps, `{error, message}` errors, Starlette sessions, one uvicorn process; the dashboard on FastAPI with relative URLs (4d) |
| [0003](0003-typer-cli.md) | The Typer CLI | Proposed | Commands first (`serve`, `execute`, `jobs`, `stats`, `validate`, `rules list`, `config`); no flags-only form, no alias, a hint naming the new command; exit codes 0/1/2 |
| [0004](0004-metrics-on-interpose.md) | Metrics on interpose's Registry | Proposed | The template's registry and build info; 0.10.x names and labels kept; one lock for the threads; the API key kept on `/metrics`; the multiprocess settings refused |
| [0005](0005-schedule-on-interpose.md) | The schedule on interpose 0.4.1 (amends 0001) | Approved | `schedule` an interpose list section (indexed variables from 0, replacing the file's list; new `QBT_RULES_SCHEDULE_FILE`); a lone `_N_CONTEXT` an error; interpose's unknown-key warnings logged; `${VAR}` expansion stays qbt-rules' own until the next major |
