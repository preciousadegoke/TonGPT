# TonGPT — Repo Cleanup & Technical-Debt Plan (living doc)

_Last refreshed: 2026-06-30._

A safe, staged plan to remove dead weight, consolidate docs, and keep a
professional structure. Everything destructive goes through **git** (recoverable
from history) and is captured in [`cleanup.sh`](../cleanup.sh).

> ⚠️ **Read first.** The working tree currently shows ~160 files as "modified".
> That is almost entirely **CRLF↔LF line-ending noise** from the Windows/OneDrive
> environment — plus a handful of real in-flight edits (`api/miniapp_server.py`,
> the C# controllers, `REMEDIATION_REGISTER.md`). **Commit or stash your real work
> first**, then normalize line endings (§6) so the cleanup diff is readable.

This repo has already been through one cleanup pass. Several files named in older
plans (`original_main.py`, `bot/handlers/`, `ton_data.db`, `CHANGES.md`,
`FIX_SUMMARY.md`, `SECURITY_FIXES.md`, …) **are already gone**. The sections below
describe only what *still* remains as of the date above.

---

## 1. Recommended final folder structure

The Python import graph is large and working, so we **don't** repackage core code
into `src/` (high risk, low reward). We group the already-separate concerns and
delete clutter:

```
tongpt/
├── README.md                  # architecture + dev workflow (front door)
├── main.py                    # bot + mini-app entrypoint (unchanged)
├── requirements.txt  requirements-prod.txt
├── Dockerfile  docker-compose.yml  docker-compose.prod.yml  .dockerignore
├── .env.example  .gitignore
│
├── api/                       # FastAPI mini-app server
├── bot/                       # bot command registration (commands.py) — KEEP
├── core/                      # config, pricing, rate-limit, security (source of truth)
├── handlers/                  # Telegram command + callback handlers (the REAL ones)
├── services/                  # external API clients (TON, DEX, OpenAI, X)
├── utils/                     # redis, formatting, realtime helpers
├── gpt/                       # AI / LLM logic
│
├── contracts/                 # Tact smart-contract code
│   ├── (subscription/)        #   optional: fold tongpt-subscription/ here
│   └── (wrappers/)            #   optional: fold wrappers/ here
│
├── miniapp-v2/                # canonical Preact/Vite source directory
│   └── dist/                  #   build output served by FastAPI
│
├── scripts/                   # ops + the verify_*.py / check_*.py moved off root
├── tests/                     # all test_*.py consolidated here
│
└── docs/
    ├── CLEANUP_PLAN.md          # this file (living)
    ├── CHANGELOG.md             # consolidated history
    ├── SECURITY.md              # security fixes + credential rotation
    ├── PRODUCTION_AUDIT.md      # compliance audit
    ├── REMEDIATION_REGISTER.md  # moved off root (issue/fix register)
    ├── PRE_LAUNCH_SMOKE_TEST.md # moved off root (launch checklist)
    └── DISCLAIMER.md PRIVACY.md TERMS.md  # legal — only if not linked from root
```

The folds (`tongpt-subscription/` + `wrappers/` → `contracts/`) and the root
`verify_*.py`/`test_*.py` → `scripts/`/`tests/` moves change paths, so they live in
clearly-marked **optional** stages. The dead-code, doc, and Mini-App cleanups are
low risk.

---

## 2. What still needs cleaning (current state)

### A. Tracked junk — `git rm` (recoverable)
| Path | Status | Action |
| --- | --- | --- |
| `_perm_test` | tracked, 0 bytes | `git rm` — a leftover permission probe. |
| `services/ton_ecosystem.db` | **tracked**, 44 KB | `git rm --cached` — runtime DB; app recreates it. Keep on disk. |

### B. Untracked local clutter — delete on disk (not in git)
| Path | Action |
| --- | --- |
| `bot.log` | `rm` — already covered by `*.log`. |
| `notifications.db` | `rm` — already covered by `*.db`; app recreates it. |
| `.tmp-tongpt-bot-image.tar623475655` | `rm` — 0-byte Docker leftover. |

> `.gitignore` already ignores `*.db`, `*.log`, `*.tar`, `.tmp-*`, `build/`,
> `node_modules/`, `myenv/`. `services/ton_ecosystem.db` and `_perm_test` are
> tracked only because they were committed *before* those rules existed — hence
> `git rm --cached`.

### C. Status / verification docs — consolidate to `docs/`
The task's "many status/fix/verification markdown files" have mostly been merged
already. The two that remain on the root are **substantive and worth keeping** —
move, don't delete:

- `REMEDIATION_REGISTER.md` (62 KB issue/fix register) → `docs/REMEDIATION_REGISTER.md`
- `PRE_LAUNCH_SMOKE_TEST.md` (launch checklist) → `docs/PRE_LAUNCH_SMOKE_TEST.md`

Living docs going forward: **`docs/CHANGELOG.md`** (history) and
**`docs/REMEDIATION_REGISTER.md`** (open/closed issues). Point new status notes at
those two instead of creating new root files.

### D. Keep — do not touch
`README.md`, legal pages (`DISCLAIMER.md` / `PRIVACY.md` / `TERMS.md`),
`bot/commands.py`, all code dirs, Dockerfiles, requirements, `tests/`.

### E. Local-only, already git-ignored (optional, frees disk)
`myenv/`, `__pycache__/`, `node_modules/`, `build/`, `miniapp-v2/node_modules/`.
Safe to delete locally at any time.

---

## 3. Mini-App build and serving

Keep the source directory named `miniapp-v2/`. FastAPI and Docker/Nginx both
serve `miniapp-v2/dist`; no folder promotion or rename is needed.

```bash
cd miniapp-v2 && npm ci && npm run build
cd ..
docker compose up -d --no-deps tongpt-web-ui
```

Confirm `dist/index.html` and its referenced assets exist before starting the
web container. The public `/miniapp/` URL is retained for compatibility.

---

## 4. Environment audit (unchanged)

`.env.example` was audited previously: of its keys, only `REDIS_DB` and
`TONCENTER_API` were genuinely unused and have already been removed. The large
`RATE_LIMIT_*`, `DEX_*`, `TON_HTTP_*`, and breaker blocks **are** read via the
`_env_int()/_env_float()/_env_bool()` wrappers — do **not** strip them.

---

## 5. Breaking changes & how they're handled

1. **Mini-App serving path** — always `miniapp-v2/dist` (§3). Build before
   starting the web container; the uncompiled source directory is not a web root.
2. **Tracked DB removal** — after `git rm --cached`, boot the bot/api once and
   confirm it recreates `notifications.db` / `services/ton_ecosystem.db` cleanly
   before relying on it.
3. **Root script moves (optional)** — `verify_*.py` / `test_*.py` are run by path
   (e.g. `python test_import.py`). If you move them to `scripts/`/`tests/`, update
   the README verification snippet and any CI that calls the old paths.
4. **Contract fold (optional)** — folding `tongpt-subscription/` + `wrappers/`
   into `contracts/` requires updating `tact.config.json` / blueprint paths.

---

## 6. Verification checklist (run after each stage)

```bash
# 0. Normalize line endings first (kills the CRLF "everything modified" noise)
git add --renormalize . && git commit -m "chore: normalize line endings"

# After tracked-junk + doc cleanup:
python -c "import main"                       # imports still resolve
python tests/test_import.py 2>/dev/null || python test_import.py   # import smoke test
git status                                    # only intended changes show

# After DB untracking:
#   start the bot/api once -> confirm it recreates the DBs and boots clean
git ls-files | grep -E '\.(db|log)$' || echo "no DB/log tracked ✓"

# After Mini-App build:
cd miniapp-v2 && npm ci && npm run build && ls dist   # build succeeds
#   hit /miniapp on the running server -> app loads

# Final sanity:
git ls-files | grep -E '^(_perm_test|.*\.db|.*\.log)$' || echo "clean ✓"
```

Nothing here is irreversible: every deletion is a `git rm` recoverable with
`git checkout <prev-commit> -- <path>`, or restore the whole `backup/pre-cleanup-*`
branch the script creates.
