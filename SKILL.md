---
name: odoo-tickets
description: Read and work your Odoo tickets and tasks, write to them safely, and run arbitrary Odoo queries. Use when the user asks about "my tickets", "my tasks", "helpdesk", "to-do list", "what am I assigned to", wants to start/stop time on a task, mark a ticket/task done, change a field (priority, stage, assignee, deadline), or search/group any Odoo model by domain. Runs the bundled odoo.py CLI against Odoo's XML-RPC API using the credentials in ~/.config/opencode/odoo.json.
---

# Odoo Tickets

Read the user's assigned Odoo tickets (`helpdesk.ticket`) and project tasks
(`project.task`), get full context, log time, mark work done, set fields, and
run native Odoo search/group queries on **any** model.

## Setup

If a command fails with `Missing Odoo config`, the user hasn't connected yet.
Collect the four values with the question tool (do **not** use
`input()`/`getpass` — opencode's shell is non-interactive):

1. Odoo server URL (e.g. `http://localhost:8071` or `https://myco.odoo.com`)
2. Database name
3. Login email
4. API key (Odoo → Preferences → Account Security → API Keys)

Write `~/.config/opencode/odoo.json`, then `chmod 600` it and verify with
`python3 odoo.py auth`. The key is never echoed or logged.

```json
{"url": "<url>", "db": "<db>", "username": "<login>", "api_key": "<key>"}
```

## CLI

The harness is `odoo.py`, in the **same directory as this `SKILL.md`**. Run the
commands below from that directory. Credentials (`url`/`db`/`username`/
`api_key`) come from `~/.config/opencode/odoo.json`. Each key can be overridden
with `ODOO_URL`, `ODOO_DB`, `ODOO_USERNAME`, `ODOO_API_KEY`. Never print or
commit the key.

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
python3 odoo.py write task 42 '{"priority":"3"}'         # generic field write

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
  Writes happen only through `time`, `done`, and `write` (see below).

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
o.write("task", 42, {"priority": "3", "user_ids": ["Alice"]})  # typed, validated
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

## Writing to Odoo

Exactly three ways to write, in order of preference:

1. **Time** — `time start|stop|log` (creates an `account.analytic.line`).
2. **Close** — `done task|ticket <ref>` (sets the closed flag, or the folded
   stage when the model has no writable closed field).
3. **Any other field** — `write <model> <ref> '{"<field>": <value>, ...}'`.
   One record, typed and validated against the model's schema.

Rules — follow these so writes stay deliberate and well-formed:

- **Discover, never guess.** Run `fields <model> --search <term>` first to get
  the real field name, type, `selection` keys and relation. Field names differ
  between versions and custom models.
- **Confirm before writing.** For anything the user did not explicitly ask for,
  state the change (record → field → value) and get a yes before running it.
- **The schema is enforced.** Unknown fields and `readonly` fields are rejected
  instead of silently ignored. Never write system fields (`id`, `create_date`,
  `write_date`, `__last_update`, message/audit fields).
- **Values are coerced by type**:
  - boolean → `true`/`false`
  - integer / float → number
  - selection → one of the field's listed **keys** (priority `"3"`, not `"Very High"`)
  - many2one → an id or a name; names are resolved with `name_search` and error
    on no match or ambiguity
  - one2many / many2many → a list of ids or names; `false`/`[]` clears
  - dates → `date` is `YYYY-MM-DD`, `datetime` is `YYYY-MM-DD HH:MM:SS` (UTC)
- **Timesheet notes describe the actual work**, from context — short and
  specific, no ticket-number prefix. The placeholder is `work`, so always pass
  a real note: `revisión de la vista de cobros`, `fix parser`, not `work`.
