#!/usr/bin/env bash
#
# TonGPT repo cleanup — SAFE, STAGED, REVERSIBLE.
# Refreshed 2026-06-30 to match the CURRENT tree (most of the original
# dead files were already removed; this targets what actually remains).
#
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

run()  { echo "  \$ $*"; if [ "$DRY" -eq 0 ]; then eval "$@"; fi; }
ask()  { [ "$YES" -eq 1 ] && return 0; read -r -p "→ $1 [y/N] " r; [ "$r" = "y" ] || [ "$r" = "Y" ]; }
stage(){ echo; echo "════════ $1 ════════"; }

# ── Guard rails ────────────────────────────────────────────────────────────
git rev-parse --is-inside-work-tree >/dev/null 2>&1 || { echo "Not a git repo. Abort."; exit 1; }

stage "0. Backup branch + commit current work + CRLF normalization"
echo "  The working tree currently shows ~160 files 'modified' — that is CRLF↔LF"
echo "  line-ending noise from Windows/OneDrive, mixed with a few real edits."
echo "  Commit or stash BEFORE cleaning so the cleanup diff is readable."
BACKUP="backup/pre-cleanup-$(date +%Y%m%d-%H%M%S)"
run "git branch '$BACKUP'"
echo "  Backup branch: $BACKUP (restore anything with: git checkout $BACKUP -- <path>)"
if ask "Normalize CRLF->LF now (recommended; clears the 'everything modified' noise)?"; then
  run "git add --renormalize ."
  run "git commit -m 'chore: normalize line endings' || true"
fi

# ── Stage 1: dead code / junk artifacts ────────────────────────────────────
stage "1. Remove tracked junk (recoverable via git)"
if ask "git rm tracked junk: _perm_test (empty) and services/ton_ecosystem.db (runtime DB)?"; then
  run "git rm -q --ignore-unmatch _perm_test"
  run "git rm -q --cached --ignore-unmatch services/ton_ecosystem.db"   # keep on disk, stop tracking
fi

# ── Stage 2: untracked local clutter (not in git; just delete on disk) ──────
stage "2. Delete untracked runtime/junk files on disk"
if ask "Delete bot.log, notifications.db, and the temp .tar?"; then
  run "rm -f bot.log notifications.db"
  run "rm -f .tmp-tongpt-bot-image.tar623475655"
fi

# ── Stage 3: consolidate status / verification docs ────────────────────────
stage "3. Move status/verification docs under docs/ (keep content, one home)"
echo "  REMEDIATION_REGISTER.md (issue/fix register) and PRE_LAUNCH_SMOKE_TEST.md"
echo "  are substantive living docs — MOVE them into docs/, don't delete."
if ask "Move REMEDIATION_REGISTER.md + PRE_LAUNCH_SMOKE_TEST.md into docs/?"; then
  run "mkdir -p docs"
  run "git mv REMEDIATION_REGISTER.md docs/REMEDIATION_REGISTER.md 2>/dev/null || git add docs/"
  # PRE_LAUNCH_SMOKE_TEST.md may be untracked; mv on disk then add.
  run "mv -f PRE_LAUNCH_SMOKE_TEST.md docs/PRE_LAUNCH_SMOKE_TEST.md 2>/dev/null || true"
  run "git add docs/PRE_LAUNCH_SMOKE_TEST.md 2>/dev/null || true"
fi

# ── Stage 4: retain the canonical Mini-App directory ───────────────────────
stage "4. Mini-App build location"
echo "  Keep miniapp-v2/ in place; Docker and FastAPI serve miniapp-v2/dist."
echo "  Build with: cd miniapp-v2 && npm ci && npm run build"

# ── Stage 5 (OPTIONAL): tidy root scripts ──────────────────────────────────
stage "5. [OPTIONAL] Move root verify_*.py / test_*.py off the root"
if ask "Move root verify_*.py/check_*.py -> scripts/ and test_*.py -> tests/?"; then
  run "mkdir -p scripts tests"
  run "git mv verify_*.py scripts/ 2>/dev/null || true"
  run "git mv check_connect.py quick_test_twitter.py loader.py scripts/ 2>/dev/null || true"
  run "git mv test_*.py tests/ 2>/dev/null || true"
  echo "  ⚠️  These are run by path (e.g. 'python test_import.py'). Update any docs/CI"
  echo "      that reference the old root paths (README §verification mentions test_import.py)."
fi

echo
echo "Done. Review with:  git status   and   git diff --cached --stat"
echo "Commit when happy:  git commit -m 'chore: repo cleanup & tech-debt reduction'"
echo "Undo everything:    git reset --hard '$BACKUP'"
