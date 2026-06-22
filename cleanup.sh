#!/usr/bin/env bash
#
# TonGPT repo cleanup — SAFE, STAGED, REVERSIBLE.
# Every destructive action goes through git and is preceded by a backup branch.
#
# Usage:
#   bash cleanup.sh            # interactive: asks before each stage
#   bash cleanup.sh --dry-run  # print what WOULD happen, change nothing
#   bash cleanup.sh --yes      # non-interactive (still creates the backup branch)
#
# Review docs/CLEANUP_PLAN.md before running.

set -euo pipefail
cd "$(dirname "$0")"

DRY=0; YES=0
for a in "$@"; do
  [ "$a" = "--dry-run" ] && DRY=1
  [ "$a" = "--yes" ] && YES=1
done

run()  { echo "  \$ $*"; [ "$DRY" -eq 0 ] && eval "$@"; }
ask()  { [ "$YES" -eq 1 ] && return 0; read -r -p "→ $1 [y/N] " r; [ "$r" = "y" ] || [ "$r" = "Y" ]; }
stage(){ echo; echo "════════ $1 ════════"; }

# ── Guard rails ────────────────────────────────────────────────────────────
git rev-parse --is-inside-work-tree >/dev/null 2>&1 || { echo "Not a git repo. Abort."; exit 1; }

stage "0. Backup branch + line-ending normalization"
BACKUP="backup/pre-cleanup-$(date +%Y%m%d-%H%M%S)"
run "git branch '$BACKUP'"
echo "  Backup branch: $BACKUP (restore anything with: git checkout $BACKUP -- <path>)"
if ask "Normalize CRLF->LF now (recommended; clears the 'everything modified' noise)?"; then
  run "git add --renormalize ."
  run "git commit -m 'chore: normalize line endings' || true"
fi

# ── Stage 1: zero-risk dead code ───────────────────────────────────────────
stage "1. Delete dead code (recoverable via git)"
if ask "Remove original_main.py, bot/handlers/, temp tar, empty ton_data.db?"; then
  run "git rm -q --ignore-unmatch original_main.py"
  run "git rm -qr --ignore-unmatch bot/handlers"
  run "git rm -q --ignore-unmatch '.tmp-tongpt-bot-image.tar623475655'"
  run "git rm -q --ignore-unmatch ton_data.db"
fi

# ── Stage 2: stop tracking runtime data ────────────────────────────────────
stage "2. Untrack committed DBs + logs (kept on disk locally)"
if ask "git rm --cached the tracked *.db and remove bot.log?"; then
  run "git rm -q --cached --ignore-unmatch notifications.db ton_ecosystem.db ton_tweets.db"
  run "rm -f bot.log"
fi

# ── Stage 3: consolidated docs ─────────────────────────────────────────────
stage "3. Remove the 9 redundant fix/status docs (content lives in docs/CHANGELOG.md)"
REDUNDANT=(CHANGES.md FIX_SUMMARY.md FIXES_SUMMARY.md README_FIXES.md \
           VERIFICATION_REPORT.md STATUS.txt QUICK_START.md INDEX.md)
# NOTE: the OLD top-level CHANGELOG.md is replaced by docs/CHANGELOG.md.
if ask "Delete redundant docs + old CHANGELOG.md, and move audit into docs/?"; then
  run "git rm -q --ignore-unmatch ${REDUNDANT[*]}"
  run "git rm -q --ignore-unmatch CHANGELOG.md"          # superseded by docs/CHANGELOG.md
  # These two were consolidated into docs/SECURITY.md:
  run "git rm -q --ignore-unmatch SECURITY_FIXES.md CREDENTIAL_ROTATION.md"
  # Preserve the substantive audit by MOVING it (don't retype):
  run "mkdir -p docs"
  run "git mv PRODUCTION_READINESS_AUDIT.md docs/PRODUCTION_AUDIT.md 2>/dev/null || true"
fi

# ── Stage 4: env hygiene ───────────────────────────────────────────────────
stage "4. Remove the 2 genuinely-unused env keys from .env.example"
if ask "Strip REDIS_DB and TONCENTER_API lines from .env.example?"; then
  run "sed -i.bak '/^REDIS_DB=/d; /^TONCENTER_API=/d' .env.example && rm -f .env.example.bak"
fi

# ── Stage 5 (CAREFUL): Mini-App promotion ──────────────────────────────────
stage "5. [CAREFUL] Promote miniapp-v2 → miniapp"
echo "  Prerequisite: build & verify v2 first:  cd miniapp-v2 && npm install && npm run build"
if ask "Delete legacy miniapp/ and rename miniapp-v2/ -> miniapp/ NOW?"; then
  run "git rm -qr --ignore-unmatch miniapp"
  run "git mv miniapp-v2 miniapp"
  echo "  ⚠️  Now update api/miniapp_server.py to serve 'miniapp/dist' (see CLEANUP_PLAN §5)."
fi

# ── Stage 6 (OPTIONAL): structural moves ───────────────────────────────────
stage "6. [OPTIONAL] Tidy structure: scripts/, tests/, contracts/"
if ask "Move root verify_*.py/check_*.py -> scripts/ and test_*.py -> tests/?"; then
  run "mkdir -p scripts tests"
  run "git mv verify_*.py scripts/ 2>/dev/null || true"
  run "git mv check_connect.py quick_test_twitter.py loader.py scripts/ 2>/dev/null || true"
  run "git mv test_*.py tests/ 2>/dev/null || true"
  echo "  ⚠️  If anything imports these by root path, update imports (see §6 verify)."
fi

echo
echo "Done. Review with:  git status   and   git diff --cached --stat"
echo "Commit when happy:  git commit -m 'chore: repo cleanup & tech-debt reduction'"
echo "Undo everything:    git reset --hard '$BACKUP'"
