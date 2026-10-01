#!/usr/bin/env sh
# First-run setup for the odoo-tickets opencode skill.
# 1. Registers this repo in opencode's config (skills.paths) so opencode
#    loads the skill by default, wherever the repo is cloned.
# 2. Prompts for the Odoo connection and verifies it.
set -e
cd "$(dirname "$0")"
REPO="$(pwd -P)"
command -v python3 >/dev/null || { echo "python3 not found"; exit 1; }

echo "==> Register skill with opencode"
python3 - "$REPO" <<'PY'
import json, os, sys
repo = sys.argv[1]
cfgdir = os.path.expanduser("~/.config/opencode")
cfgpath = os.path.join(cfgdir, "opencode.jsonc")
if not os.path.exists(cfgpath):
    cfgpath = os.path.join(cfgdir, "opencode.json")
cfg = {}
if os.path.exists(cfgpath):
    try:
        cfg = json.loads(open(cfgpath).read())
    except ValueError as e:
        print("Warning: could not parse %s (%s); skipping skill registration." % (cfgpath, e))
        sys.exit(0)
cfg.setdefault("skills", {}).setdefault("paths", [])
if repo not in cfg["skills"]["paths"]:
    cfg["skills"]["paths"].append(repo)
    os.makedirs(cfgdir, exist_ok=True)
    open(cfgpath, "w").write(json.dumps(cfg, indent=2) + "\n")
    print("Registered skill path: %s" % repo)
else:
    print("Skill path already registered: %s" % repo)
PY

echo "==> Configure your Odoo connection"
python3 odoo.py setup
echo "==> Verify"
python3 odoo.py auth
echo "==> Done. Restart opencode and ask it about your tickets."
