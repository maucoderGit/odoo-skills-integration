---
name: odoo-tickets
description: Read and work your Odoo tickets and tasks, and run arbitrary read-only Odoo queries. Use when the user asks about "my tickets", "my tasks", "helpdesk", "to-do list", "what am I assigned to", wants to start/stop time on a task, mark a ticket/task done, or search/group any Odoo model by domain. Runs the bundled odoo.py CLI against Odoo's XML-RPC API using the credentials in ~/.config/opencode/odoo.json.
---

# Odoo Tickets

Read the user's assigned Odoo tickets (`helpdesk.ticket`) and project tasks
(`project.task`), get full context, log time, mark work done, and run native
Odoo search/group queries on **any** model.

## CLI

The harness is at `/home/jpinero/.config/opencode/skills/odoo-tickets/odoo.py`.
Credentials (`url`/`db`/`username`/`api_key`) come from
`~/.config/opencode/odoo.json`. Each key can be overridden with `ODOO_URL`,
`ODOO_DB`, `ODOO_USERNAME`, `ODOO_API_KEY`. Never print or commit the key.

Output is **always compact JSON** (no `--json` flag). Run with `python3`:

```bash
# curated (scoped to the logged-in user). `list` hides closed items and caps
# output; use --all to include closed, --limit N to widen/narrow the cap.
python3 odoo.py auth
python3 odoo.py setup
python3 odoo.py selftest
python3 odoo.py list [tasks|tickets] [--all] [--limit N] [--by team|project|stage]
python3 odoo.py show task 42            # id...
python3 odoo.py show ticket HT00712     # ...or ticket number
python3 odoo.py time start task 42 "fixing the parser"
python3 odoo.py time stop task 42       # logs elapsed hours
python3 odoo.py time log ticket HT00623 3 "pruebas de la vista de cobros"  # fixed hours
python3 odoo.py done task 42
python3 odoo.py done ticket 17

# generic read-only queries (any model, NOT scoped to the user)
python3 odoo.py fields helpdesk.ticket [--search prior]
python3 odoo.py search helpdesk.ticket '[("priority","=","3")]' --fields number,name --limit 20 --order "create_date desc"
python3 odoo.py count helpdesk.ticket '[("closed","=",False)]'
python3 odoo.py stats helpdesk.ticket '[("team_id","=",14)]' --groupby stage_id,user_id
python3 odoo.py group helpdesk.ticket '[]' --groupby team_id [--fields "id:count"]
python3 odoo.py read res.partner 13,14 --fields name,email
```

- Prefer `stats`/`count`/`search --fields ... --limit N` over dumping `list`
  when the ask is a summary; `stats` is a thin `read_group` wrapper that
  returns counts per group, not records.

- **Domains** accept native Odoo syntax `[('field','op',val)]` or JSON. Pass
  `-` (or omit) to read the domain from stdin — avoids shell quoting pain.
- **Field discovery**: run `fields <model>` to see real field names, types,
  relations and `selection` values, then build the domain from what exists.
  No schema is hardcoded in the harness.
- Generic `search`/`group`/`count`/`stats`/`read` are **read-only**; they are
  not filtered to the user (add `[("user_id","=",<uid>)]` yourself if needed).
  Writes happen only through the curated `done`/`time` commands.

Model names for curated commands: `task` (= `project.task`) or `ticket`
(= `helpdesk.ticket`).

The same module is importable as a Python harness:

```python
from odoo import Odoo
o = Odoo()                    # reads config, connects
o.whoami()                    # -> {"uid", "name", "login"}
o.my_items(open_only=True, limit=50, kind="tickets")  # scoped, filtered, capped
o.get("ticket", "HT00712")    # -> full record + message thread
o.fields("helpdesk.ticket")   # -> field schema
o.search("helpdesk.ticket", [("priority", "=", "3")], fields=["number", "name"])
o.count("helpdesk.ticket", [("closed", "=", False)])
o.group("helpdesk.ticket", [], ["team_id"])
o.start_time("task", 42, "note")
o.stop_time("task", 42)       # -> {"hours", "note", "logged"}
o.log_time("ticket", "HT00623", 3, "pruebas")  # fixed hours, works for tickets too
o.done("ticket", "HT00712")   # -> {"action": "is_closed"|"closed"|"stage"}
```

## How to use

- When the user asks to see their work / tickets / to-do list, run `list`,
  then `show <model> <ref>` for the ones they care about. `show` returns the
  title, stage, priority, customer, description, and the recent message
  thread — treat that as the full context for the ticket.
- When the user starts working a task, run `time start task <ref> "<short
  note>"`. When they finish (or merge the pull request), run `time stop task
  <ref>` to log the elapsed hours as a timesheet line, then `done task <ref>`
  to close it. For a fixed amount instead of a timer, use
  `time log task <ref> <hours> "<note>"`.
- **Timesheets work on both `task` and `ticket`**, provided the record has a
  linked project (`project_id`); `time log`/`time stop` create the
  `account.analytic.line` either way. On a `helpdesk.ticket` the Timesheets tab
  also needs its team's **Allow Timesheet** flag on — that is a Helpdesk
  Manager setting the harness cannot toggle, so the hours may be logged and
  visible in the project/report but hidden on the ticket form until a manager
  enables it.
- `done` sets the closed flag, moves to the folded (done) stage automatically,
  and accepts a numeric id or a ticket number.
- For anything beyond the curated commands (other models, filters, aggregates),
  use `fields` to discover the schema and `search`/`group`/`count` with a
  domain. These are read-only.
