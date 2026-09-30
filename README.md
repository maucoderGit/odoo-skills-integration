# odoo-tickets — an opencode skill

Read and work your Odoo **helpdesk tickets** (`helpdesk.ticket`) and
**project tasks** (`project.task`) from opencode: list what you're assigned
to, read full context, log time, close items, set fields, and run
search/count/group queries on **any** Odoo model.

Pure Python 3, no dependencies (stdlib `xmlrpc.client`).

## Install

**Option A — global skill (zero config).** opencode auto-loads
`~/.config/opencode/skills/*`:

```bash
git clone <REPO_URL> ~/.config/opencode/skills/odoo-tickets
```

**Option B — clone anywhere, point opencode at it.** Add the repo root to
`~/.config/opencode/opencode.json` (or `opencode.jsonc`); opencode scans it
recursively for `SKILL.md`:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "skills": { "paths": ["/absolute/path/to/odoo-tickets"] }
}
```

Restart opencode after changing config or adding the skill.

## Connect your Odoo

In opencode, just ask **"connect odoo"**. The skill asks for your server URL,
database, login email and an API key (Odoo → Preferences → Account Security →
API Keys), writes `~/.config/opencode/odoo.json` (chmod 600), and verifies the
connection. The key is never logged or committed.

## Use

Just talk to opencode:

- "what are my tickets?" / "what am I assigned to?"
- "show ticket HT00712" / "show task 42"
- "start time on task 42" … "stop and log it"
- "log 3 hours on ticket HT00623"
- "mark task 42 done"
- "set task 42 to high priority"
- "how many open tickets per team?"

## Writing to Odoo

Three write paths, preferred in this order: `time` (timesheets), `done`
(close), then `write` for any other field. The `write` command is typed and
validated against the model's schema — unknown and `readonly` fields are
rejected instead of silently ignored.

```bash
python3 odoo.py write task 42 '{"priority":"3"}'
python3 odoo.py write task 42 '{"user_ids":["Alice"]}'        # name -> id
python3 odoo.py write helpdesk.ticket HT00712 '{"stage_id":"In Progress"}'
```

Conventions the skill follows (and you should too):

- Discover field names first with `fields <model> --search <term>` — never guess.
- Confirm the change before writing unless the user asked for it explicitly.
- selection fields take the key (`"3"`), not the label (`"Very High"`).
- dates: `YYYY-MM-DD` (date), `YYYY-MM-DD HH:MM:SS` UTC (datetime).
- timesheet notes describe the actual work, short and specific, with no
  ticket-number prefix (e.g. `fix parser`, not `work`).

## The CLI

`odoo.py` is also usable directly (always compact JSON):

```bash
python3 odoo.py auth
python3 odoo.py list [tasks|tickets] [--all] [--limit N] [--by team|project|stage]
python3 odoo.py show task 42
python3 odoo.py time log ticket HT00623 3 "note"
python3 odoo.py done task 42
python3 odoo.py write task 42 '{"priority":"3"}'
python3 odoo.py search helpdesk.ticket '[("priority","=","3")]' --fields number,name
python3 odoo.py stats helpdesk.ticket '[]' --groupby stage_id,user_id
```

Run it from this directory, or set `ODOO_URL` / `ODOO_DB` / `ODOO_USERNAME` /
`ODOO_API_KEY` instead of the JSON file.
