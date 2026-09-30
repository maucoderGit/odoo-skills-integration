#!/usr/bin/env python3
import argparse
import ast
import getpass
import json
import os
import re
import sys
import time
import xmlrpc.client

CONFIG_PATH = os.path.expanduser("~/.config/opencode/odoo.json")
TIMER_PATH = os.path.expanduser("~/.local/share/opencode/odoo-timer.json")

MODELS = {"task": "project.task", "ticket": "helpdesk.ticket"}

TASK_FIELDS = ["name", "description", "project_id", "stage_id", "priority",
               "user_ids", "partner_id", "create_date", "write_date", "state"]
TICKET_FIELDS = ["name", "number", "description", "partner_id", "user_id", "stage_id",
                 "priority", "team_id", "create_date", "write_date", "closed"]


def load_config():
    cfg = {}
    if os.path.exists(CONFIG_PATH):
        cfg = json.load(open(CONFIG_PATH))
    for key, var in (("url", "ODOO_URL"), ("db", "ODOO_DB"),
                     ("username", "ODOO_USERNAME"), ("api_key", "ODOO_API_KEY")):
        if os.environ.get(var):
            cfg[key] = os.environ[var]
    missing = [k for k in ("url", "db", "username", "api_key") if not cfg.get(k)]
    if missing:
        raise RuntimeError("Missing Odoo config: %s. Fill %s or set env vars."
                           % (", ".join(missing), CONFIG_PATH))
    return cfg


def strip_tags(s):
    return re.sub(r"<[^>]+>", "", s or "").strip()


def m2o(v):
    return {"id": v[0], "name": v[1]} if v else None


def label(v):
    return m2o(v)["name"] if v else ""


def pick_fields(schema, base):
    return [f for f in base if f in schema]


def stars(schema, value):
    sel = (schema.get("priority") or {}).get("selection") or []
    n = max(len(sel) - 1, 0)
    v = min(int(value or 0), n)
    return "\u2605" * v + "\u2606" * (n - v)


def parse_domain(s):
    if s is None or s.strip() in ("", "-"):
        s = sys.stdin.read()
    try:
        return json.loads(s)
    except (ValueError, TypeError):
        return ast.literal_eval(s)


def group_items(data, by):
    out = {}
    for kind in ("tasks", "tickets"):
        buckets = {}
        for x in data.get(kind, []):
            v = x.get(by)
            key = v.get("name") if isinstance(v, dict) else v
            buckets.setdefault(key or "(none)", []).append(x)
        out[kind] = buckets
    return out


def emit(obj):
    print(json.dumps(obj, ensure_ascii=False, separators=(",", ":")))


def select_items(items, open_only=True, limit=None):
    if open_only:
        items = [x for x in items if not x.get("closed")]
    return items[:limit] if limit else items


def check_field(name, schema):
    if name not in schema:
        raise ValueError("Unknown field %r (run `fields <model>`)" % name)
    if schema[name].get("readonly"):
        raise ValueError("Field %r is readonly" % name)


def coerce_value(field, value, resolve):
    t = field.get("type")
    if value is None or value is False:
        if t in ("one2many", "many2many"):
            return [(6, 0, [])]
        return False if t == "many2one" else value
    if t == "boolean":
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "y", "t")
        return bool(value)
    if t == "integer":
        return int(value)
    if t in ("float", "monetary"):
        return float(value)
    if t == "selection":
        for key, _label in field.get("selection") or []:
            if value == key or str(value) == str(key):
                return key
        raise ValueError("Invalid selection %r; valid: %s"
                         % (value, [k for k, _ in field.get("selection") or []]))
    if t == "many2one":
        if isinstance(value, int) or (isinstance(value, str) and value.isdigit()):
            return int(value)
        return resolve(value)
    if t in ("one2many", "many2many"):
        vals = value if isinstance(value, (list, tuple)) else [value]
        return [(6, 0, [v if isinstance(v, int) else resolve(v) for v in vals])]
    return value


class Odoo:
    def __init__(self, cfg=None):
        self.cfg = cfg or load_config()
        url = self.cfg["url"].rstrip("/")
        self.url = url
        self._schema_cache = {}
        self._fold_cache = {}
        self._common = xmlrpc.client.ServerProxy("%s/xmlrpc/2/common" % url, allow_none=True)
        try:
            self.uid = self._common.authenticate(self.cfg["db"], self.cfg["username"],
                                                 self.cfg["api_key"], {})
        except Exception as e:
            raise RuntimeError("Auth failed (unreachable/bad url?): %s" % e)
        if not self.uid:
            raise RuntimeError("Auth failed: check url/db/username/api_key.")
        self._models = xmlrpc.client.ServerProxy("%s/xmlrpc/2/object" % url, allow_none=True)

    def _call(self, model, method, args, kwargs=None):
        return self._models.execute_kw(self.cfg["db"], self.uid, self.cfg["api_key"],
                                       model, method, args, kwargs or {})

    def schema(self, model):
        if model not in self._schema_cache:
            self._schema_cache[model] = self._call(
                model, "fields_get", [],
                {"attributes": ["type", "string", "selection", "readonly", "relation"]})
        return self._schema_cache[model]

    def _fields(self, model, base):
        return pick_fields(self.schema(model), base)

    def _folded_stage_ids(self, model):
        if model not in self._fold_cache:
            rel = (self.schema(model).get("stage_id") or {}).get("relation")
            self._fold_cache[model] = set(
                self._call(rel, "search", [[["fold", "=", True]]])) if rel else set()
        return self._fold_cache[model]

    def _closed(self, model, r):
        s = self.schema(model)
        for f in ("closed", "is_closed"):
            if f in s:
                return bool(r.get(f))
        if "state" in s:
            # Odoo convention: terminal states are prefixed "1_" (1_done, 1_canceled)
            return str(r.get("state") or "").startswith("1")
        # ponytail: last resort = stage folded; non-folded terminal stages read as open
        return bool(r.get("stage_id")) and r["stage_id"][0] in self._folded_stage_ids(model)

    def _resolve(self, model, ref):
        if str(ref).isdigit():
            return int(ref)
        ids = self._call(model, "search", [[["number", "=", str(ref).upper()]]], {"limit": 1})
        if not ids:
            raise ValueError("No %s with number %s" % (model, ref))
        return ids[0]

    def whoami(self):
        r = self._call("res.users", "read", [self.uid], {"fields": ["name", "login"]})
        u = r[0] if r else {}
        return {"uid": self.uid, "name": u.get("name"), "login": u.get("login")}

    def fields(self, model, search=None):
        out = []
        for name, a in sorted(self.schema(model).items()):
            if search and search.lower() not in (name + " " + (a.get("string") or "")).lower():
                continue
            item = {"name": name, "type": a.get("type"), "string": a.get("string")}
            if a.get("relation"):
                item["relation"] = a["relation"]
            if a.get("selection"):
                item["selection"] = a["selection"]
            out.append(item)
        return out

    def my_items(self, open_only=True, limit=50, kind=None):
        out = {"tasks": [], "tickets": [], "errors": []}
        try:
            tasks = self._call("project.task", "search_read",
                               [[["user_ids", "in", [self.uid]]]],
                               {"fields": self._fields("project.task", TASK_FIELDS),
                                "order": "write_date desc", "limit": 200})
        except Exception as e:
            tasks = []
            out["errors"].append("project.task: %s" % e)
        try:
            tickets = self._call("helpdesk.ticket", "search_read",
                                 [[["user_id", "=", self.uid]]],
                                 {"fields": self._fields("helpdesk.ticket", TICKET_FIELDS),
                                  "order": "write_date desc", "limit": 200})
        except Exception as e:
            tickets = []
            out["errors"].append("helpdesk.ticket: %s" % e)
        for t in tasks:
            out["tasks"].append({
                "id": t["id"], "title": t.get("name"), "stage": label(t.get("stage_id")),
                "priority": t.get("priority"),
                "stars": stars(self.schema("project.task"), t.get("priority")),
                "closed": self._closed("project.task", t),
                "project": m2o(t.get("project_id")), "create_date": t.get("create_date"),
                "write_date": t.get("write_date"),
            })
        for t in tickets:
            out["tickets"].append({
                "id": t["id"], "number": t.get("number"), "title": t.get("name"),
                "stage": label(t.get("stage_id")),
                "priority": t.get("priority"),
                "stars": stars(self.schema("helpdesk.ticket"), t.get("priority")),
                "closed": self._closed("helpdesk.ticket", t),
                "team": m2o(t.get("team_id")), "customer": m2o(t.get("partner_id")),
                "create_date": t.get("create_date"), "write_date": t.get("write_date"),
            })
        for k in ("tasks", "tickets"):
            out[k].sort(key=lambda x: (-int(x.get("priority") or 0),
                                       x.get("create_date") or ""))
            out[k] = select_items(out[k], open_only=open_only, limit=limit)
        if kind in ("tasks", "tickets"):
            for other in ("tasks", "tickets"):
                if other != kind:
                    out.pop(other, None)
        return out

    def get(self, model, ref):
        model = MODELS.get(model, model)
        id_ = self._resolve(model, ref)
        if model == "project.task":
            base = TASK_FIELDS
        elif model == "helpdesk.ticket":
            base = TICKET_FIELDS
        else:
            base = ["name", "display_name", "create_date", "write_date"]
        recs = self._call(model, "read", [id_], {"fields": self._fields(model, base)})
        if not recs:
            raise ValueError("Not found: %s %s" % (model, id_))
        r = recs[0]
        item = {
            "model": model, "id": r["id"], "title": r.get("name"),
            "stage": label(r.get("stage_id")), "priority": r.get("priority"),
            "closed": self._closed(model, r), "customer": m2o(r.get("partner_id")),
            "create_date": r.get("create_date"), "write_date": r.get("write_date"),
            "description": strip_tags(r.get("description")),
        }
        if model == "project.task":
            item["project"] = m2o(r.get("project_id"))
            item["assigned_user_ids"] = r.get("user_ids")
        elif model == "helpdesk.ticket":
            item["number"] = r.get("number")
            item["team"] = m2o(r.get("team_id"))
            item["assigned_user_id"] = r.get("user_id")
        try:
            msgs = self._call("mail.message", "search_read",
                              [[["model", "=", model], ["res_id", "=", id_]]],
                              {"fields": ["date", "author_id", "body"],
                               "order": "date desc", "limit": 50})
        except Exception:
            msgs = []
        clean = [m for m in msgs if strip_tags(m.get("body"))][:10]
        item["messages"] = [{"date": m.get("date"), "author": label(m.get("author_id")),
                             "body": strip_tags(m.get("body"))}
                            for m in reversed(clean)]
        return item

    def search(self, model, domain, fields=None, limit=None, order=None):
        base = fields or self._default_fields(model)
        kw = {"fields": self._fields(model, base)}
        if limit:
            kw["limit"] = limit
        if order:
            kw["order"] = order
        return self._call(model, "search_read", [domain], kw)

    def count(self, model, domain):
        return {"model": model, "count": self._call(model, "search_count", [domain])}

    def group(self, model, domain, groupby, fields=None):
        return self._call(model, "read_group",
                          [domain, fields or [], groupby], {"lazy": False})

    def read(self, model, ids, fields=None):
        base = fields or self._default_fields(model)
        return self._call(model, "read", [ids], {"fields": self._fields(model, base)})

    def _default_fields(self, model):
        if model == "project.task":
            return self._fields(model, TASK_FIELDS)
        if model == "helpdesk.ticket":
            return self._fields(model, TICKET_FIELDS)
        return self._fields(model, ["name", "display_name", "create_date", "write_date"])

    def start_time(self, model, ref, note=""):
        model = MODELS.get(model, model)
        id_ = self._resolve(model, ref)
        recs = self._call(model, "read", [id_], {"fields": ["id"]})
        if not recs:
            raise ValueError("Not found: %s %s" % (model, id_))
        key = "%s/%s" % (model, id_)
        t = self._load_timer()
        t[key] = {"start": time.time(), "note": note}
        self._save_timer(t)
        return {"key": key, "note": note, "started": time.time()}

    def stop_time(self, model, ref, note=None):
        model = MODELS.get(model, model)
        id_ = self._resolve(model, ref)
        key = "%s/%s" % (model, id_)
        t = self._load_timer()
        if key not in t:
            raise ValueError("No running timer for %s. Start one first." % key)
        start = t.pop(key)
        self._save_timer(t)
        hours = max(round((time.time() - start["start"]) / 3600.0, 2), 0.01)
        note = note or start["note"] or "work"
        return self.log_time(model, ref, hours, note)

    def log_time(self, model, ref, hours, note=""):
        model = MODELS.get(model, model)
        id_ = self._resolve(model, ref)
        ref_field = {"project.task": "task_id", "helpdesk.ticket": "ticket_id"}.get(model)
        if not ref_field:
            raise ValueError("Timesheets aren't supported for %s." % model)
        recs = self._call(model, "read", [id_], {"fields": ["project_id"]})
        project = recs[0].get("project_id") if recs else None
        if not project:
            raise ValueError("No project linked to %s %s; can't log a timesheet." % (model, ref))
        proj = self._call("project.project", "read", [project[0]],
                          {"fields": ["analytic_account_id", "timesheet_encode_uom_id"]})[0]
        vals = {"name": note or "work", "unit_amount": float(hours),
                "date": time.strftime("%Y-%m-%d"),
                "project_id": project[0], ref_field: id_}
        if proj.get("analytic_account_id"):
            vals["account_id"] = proj["analytic_account_id"][0]
        if proj.get("timesheet_encode_uom_id"):
            vals["product_uom_id"] = proj["timesheet_encode_uom_id"][0]
        emp = self._employee_id()
        if emp:
            vals["employee_id"] = emp
        line = self._call("account.analytic.line", "create", [vals])
        return {"key": "%s/%s" % (model, id_), "line_id": line, "hours": float(hours),
                "note": vals["name"], "project": project[1], "logged": True}

    def write(self, model, ref, values):
        model = MODELS.get(model, model)
        id_ = self._resolve(model, ref)
        schema = self.schema(model)
        out = {}
        for k, v in values.items():
            check_field(k, schema)
            rel = schema[k].get("relation")
            out[k] = coerce_value(schema[k], v,
                                  lambda name, rel=rel: self._resolve_name(rel, name))
        self._call(model, "write", [[id_], out])
        return {"model": model, "id": id_, "written": out}

    def _resolve_name(self, rel, name):
        if not rel:
            raise ValueError("Can't resolve %r: field has no relation" % name)
        hits = self._call(rel, "name_search", [name], {"limit": 2})
        if not hits:
            raise ValueError("No %s named %r" % (rel, name))
        if len(hits) > 1:
            raise ValueError("Ambiguous %s %r matches %s"
                             % (rel, name, [h[1] for h in hits]))
        return hits[0][0]

    def done(self, model, ref):
        model = MODELS.get(model, model)
        id_ = self._resolve(model, ref)
        s = self.schema(model)
        for f in ("is_closed", "closed"):
            if f in s and not s[f].get("readonly"):
                self._call(model, "write", [[id_], {f: True}])
                return {"model": model, "id": id_, "action": f}
        rel = (s.get("stage_id") or {}).get("relation")
        if not rel:
            raise ValueError("No stage field on %s." % model)
        stages = self._call(rel, "search_read", [[["fold", "=", True]]],
                            {"fields": ["name"], "order": "sequence", "limit": 1})
        if not stages:
            raise ValueError("No folded (done) stage found for %s." % model)
        self._call(model, "write", [[id_], {"stage_id": stages[0]["id"]}])
        self._fold_cache.pop(model, None)
        return {"model": model, "id": id_, "action": "stage", "stage": stages[0]["name"]}

    def _employee_id(self):
        try:
            emp = self._call("hr.employee", "search", [[["user_id", "=", self.uid]]],
                             {"limit": 1})
            return emp[0] if emp else False
        except Exception:
            # ponytail: no employee record -> timesheet logs without employee_id
            return False

    @staticmethod
    def _load_timer():
        if os.path.exists(TIMER_PATH):
            return json.load(open(TIMER_PATH))
        return {}

    @staticmethod
    def _save_timer(t):
        os.makedirs(os.path.dirname(TIMER_PATH), exist_ok=True)
        json.dump(t, open(TIMER_PATH, "w"))


def setup():
    existing = {}
    if os.path.exists(CONFIG_PATH):
        try:
            existing = json.load(open(CONFIG_PATH))
        except Exception:
            pass
    print("Odoo connection setup (writes %s)" % CONFIG_PATH)
    url = (input("URL: ").strip() or existing.get("url") or "").rstrip("/")
    dbname = input("Database: ").strip() or existing.get("db") or ""
    username = input("Login email: ").strip() or existing.get("username") or ""
    key = getpass.getpass("API key (blank to keep existing): ").strip()
    out = {"url": url, "db": dbname, "username": username,
           "api_key": key or existing.get("api_key", "")}
    json.dump(out, open(CONFIG_PATH, "w"), indent=2)
    os.chmod(CONFIG_PATH, 0o600)
    print("Saved. Run `auth` to verify.")


def selftest():
    assert m2o([1, "A"]) == {"id": 1, "name": "A"}
    assert m2o(False) is None
    assert label([1, "A"]) == "A"
    assert label(False) == ""
    task = {"priority": {"selection": [["0", "Low"], ["1", "High"]]}}
    ticket = {"priority": {"selection": [["0", "Low"], ["1", "Medium"],
                                         ["2", "High"], ["3", "Very High"]]}}
    assert stars(task, "1") == "\u2605"
    assert stars(task, "0") == "\u2606"
    assert stars(ticket, "3") == "\u2605\u2605\u2605"
    assert stars(ticket, "0") == "\u2606\u2606\u2606"
    assert stars(ticket, None) == "\u2606\u2606\u2606"
    assert pick_fields({"a": {}, "b": {}}, ["a", "c", "b"]) == ["a", "b"]
    assert parse_domain('[("priority", "=", "3")]') == [("priority", "=", "3")]
    assert parse_domain('[["priority", "=", "3"]]') == [["priority", "=", "3"]]
    data = {"tasks": [], "tickets": [{"team": {"name": "X"}, "id": 1},
                                     {"team": None, "id": 2}]}
    assert list(group_items(data, "team")["tickets"]) == ["X", "(none)"]
    items = [{"id": 1, "closed": False}, {"id": 2, "closed": True},
             {"id": 3, "closed": False}]
    assert [x["id"] for x in select_items(items)] == [1, 3]
    assert [x["id"] for x in select_items(items, open_only=False, limit=2)] == [1, 2]
    assert select_items(items, open_only=False, limit=None) == items
    t = Odoo.__new__(Odoo)
    t._schema_cache = {"m": {"state": {}}, "t": {"closed": {}}}
    assert t._closed("m", {"state": "1_done"}) is True
    assert t._closed("m", {"state": "01_in_progress"}) is False
    assert t._closed("t", {"closed": True}) is True
    sch = {"name": {"type": "char"},
           "priority": {"type": "selection", "selection": [["0", "Low"], ["1", "High"]]},
           "user_id": {"type": "many2one", "relation": "res.users"},
           "tag_ids": {"type": "many2many", "relation": "x.tag"},
           "active": {"type": "boolean"}}
    r = lambda n: {"Alice": 7}[n]
    check_field("name", sch)
    try:
        check_field("nope", sch)
        assert False
    except ValueError:
        pass
    try:
        check_field("x", {"x": {"readonly": True}})
        assert False
    except ValueError:
        pass
    assert coerce_value(sch["name"], "hi", r) == "hi"
    assert coerce_value(sch["priority"], "1", r) == "1"
    assert coerce_value(sch["active"], "true", r) is True
    assert coerce_value(sch["user_id"], "Alice", r) == 7
    assert coerce_value(sch["user_id"], 3, r) == 3
    assert coerce_value(sch["user_id"], False, r) is False
    assert coerce_value(sch["tag_ids"], ["Alice", 4], r) == [(6, 0, [7, 4])]
    assert coerce_value(sch["tag_ids"], False, r) == [(6, 0, [])]
    for bad in ("9", "High"):
        try:
            coerce_value(sch["priority"], bad, r)
            assert False
        except ValueError:
            pass
    print("selftest ok")


def main():
    p = argparse.ArgumentParser(prog="odoo", description="Odoo tickets/tasks/query harness")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("auth")
    sub.add_parser("setup")
    sub.add_parser("selftest")

    lp = sub.add_parser("list")
    lp.add_argument("kind", nargs="?", choices=["tasks", "tickets"])
    lp.add_argument("--all", action="store_true", help="include closed items")
    lp.add_argument("--limit", type=int, default=50, help="max items per kind")
    lp.add_argument("--by", choices=["team", "project", "stage"], help="group results")

    s = sub.add_parser("show")
    s.add_argument("model", choices=list(MODELS))
    s.add_argument("ref", help="numeric id or ticket number (HT00712)")

    fp = sub.add_parser("fields")
    fp.add_argument("model")
    fp.add_argument("--search", help="substring filter on name/label")

    sp = sub.add_parser("search")
    sp.add_argument("model")
    sp.add_argument("domain", help="Odoo domain: JSON or [('field','op',val)]; '-' reads stdin")
    sp.add_argument("--fields", help="comma-separated field names")
    sp.add_argument("--limit", type=int)
    sp.add_argument("--order", help="e.g. 'create_date desc'")

    cp = sub.add_parser("count")
    cp.add_argument("model")
    cp.add_argument("domain")

    st = sub.add_parser("stats")
    st.add_argument("model")
    st.add_argument("domain", nargs="?", default="[]")
    st.add_argument("--groupby", required=True, help="comma-separated groupby fields")
    st.add_argument("--fields", help="aggregates, e.g. 'id:count'")

    gp = sub.add_parser("group")
    gp.add_argument("model")
    gp.add_argument("domain")
    gp.add_argument("--groupby", required=True, help="comma-separated groupby fields")
    gp.add_argument("--fields", help="comma-separated aggregates, e.g. 'id:count'")

    rp = sub.add_parser("read")
    rp.add_argument("model")
    rp.add_argument("ids", help="comma-separated ids")
    rp.add_argument("--fields")

    ts = sub.add_parser("time")
    ts_sub = ts.add_subparsers(dest="time_cmd", required=True)
    tstart = ts_sub.add_parser("start")
    tstart.add_argument("model", choices=list(MODELS))
    tstart.add_argument("ref")
    tstart.add_argument("note", nargs="*")
    tstop = ts_sub.add_parser("stop")
    tstop.add_argument("model", choices=list(MODELS))
    tstop.add_argument("ref")
    tstop.add_argument("note", nargs="*")
    tlog = ts_sub.add_parser("log")
    tlog.add_argument("model", choices=list(MODELS))
    tlog.add_argument("ref")
    tlog.add_argument("hours", type=float)
    tlog.add_argument("note", nargs="*")

    d = sub.add_parser("done")
    d.add_argument("model", choices=list(MODELS))
    d.add_argument("ref")

    wp = sub.add_parser("write")
    wp.add_argument("model")
    wp.add_argument("ref")
    wp.add_argument("values", help="{field: value} JSON/Python dict; '-' reads stdin")

    args = p.parse_args()

    def clist(s):
        return [x.strip() for x in s.split(",") if x.strip()] if s else None

    try:
        if args.cmd == "setup":
            setup()
            return
        if args.cmd == "selftest":
            selftest()
            return
        odoo = Odoo()
        if args.cmd == "auth":
            emit(odoo.whoami())
        elif args.cmd == "list":
            data = odoo.my_items(open_only=not args.all, limit=args.limit, kind=args.kind)
            emit(group_items(data, args.by) if args.by else data)
        elif args.cmd == "show":
            emit(odoo.get(args.model, args.ref))
        elif args.cmd == "fields":
            emit(odoo.fields(args.model, args.search))
        elif args.cmd == "search":
            emit(odoo.search(args.model, parse_domain(args.domain),
                             clist(args.fields), args.limit, args.order))
        elif args.cmd == "count":
            emit(odoo.count(args.model, parse_domain(args.domain)))
        elif args.cmd == "stats":
            gb = clist(args.groupby) or []
            emit(odoo.group(args.model, parse_domain(args.domain),
                            gb, gb + (clist(args.fields) or [])))
        elif args.cmd == "group":
            emit(odoo.group(args.model, parse_domain(args.domain),
                            clist(args.groupby), clist(args.fields) or []))
        elif args.cmd == "read":
            emit(odoo.read(args.model, [int(x) for x in args.ids.split(",")],
                           clist(args.fields)))
        elif args.cmd == "done":
            emit(odoo.done(args.model, args.ref))
        elif args.cmd == "write":
            emit(odoo.write(args.model, args.ref, parse_domain(args.values)))
        elif args.cmd == "time":
            note = " ".join(args.note)
            if args.time_cmd == "start":
                emit(odoo.start_time(args.model, args.ref, note))
            elif args.time_cmd == "stop":
                emit(odoo.stop_time(args.model, args.ref, note or None))
            else:
                emit(odoo.log_time(args.model, args.ref, args.hours, note))
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
