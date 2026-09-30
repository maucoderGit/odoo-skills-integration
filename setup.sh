#!/usr/bin/env sh
# First-run setup for the odoo-tickets opencode skill.
set -e
cd "$(dirname "$0")"
command -v python3 >/dev/null || { echo "python3 not found"; exit 1; }
echo "==> Configure your Odoo connection"
python3 odoo.py setup
echo "==> Verify"
python3 odoo.py auth
echo "==> Done. Restart opencode and ask it about your tickets."
