# TonGPT — Repo Cleanup & Technical-Debt Plan

A safe, staged plan to remove dead weight, consolidate docs, and establish a
professional structure. Everything destructive goes through **git** (recoverable
from history) and is captured in [`cleanup.sh`](../cleanup.sh).

> ⚠️ Before running anything: the working tree currently shows almost every file
> as "modified". That's **CRLF↔LF line-ending noise** from the Windows/OneDrive
> environment, not real edits. Normalise it first (see §6) so the cleanup diff is
> readable.

---

## 1. Recommended final folder structure

The Python import graph is large and working, so we **don't** repackage core code
into `src/` (high risk, low reward). Instead we group the already-separate
concerns and delete clutter:

```
tongpt/
├── README.md                  # architecture + dev workflow (front door)
├── main.py                    # bot entrypoint (unchanged)
├── requirements.txt  requirements-prod.txt
├── Dockerfile  docker-compose.yml  docker-compose.prod.yml  .dockerignore
├── .env.example  .gitignore
│
├── api/                       # FastAPI mini-app server
├── bot/                       # bot command registration (commands.py)
├── core/                      # config, pricing, rate-limit, security  (source of truth)
├── handlers/                  # Telegram command + callback handlers
├── services/                  # external API clients (TON, DEX, OpenAI, X)
├── utils/                     # redis, formatting, realtime helpers
├── gpt/                       # AI / LLM logic
│
├── contracts/                 # ← all smart-contract code lives here
│   ├── subscription/          #   (was tongpt-subscription/)
│   ├── wrappers/              #   (was /wrappers)
│   └── tact.config.json
│
├── miniapp/                   # ← the Preact v2 app (renamed from miniapp-v2/)
│   └── dist/                  #   build output served by FastAPI
│
├── scripts/                   # ops + the verify_*.py / check_*.py moved off root
├── tests/                     # all test_*.py consolidated here
│
└── docs/
    ├── CLEANUP_PLAN.md        # this file
    ├── CHANGELOG.md           # consolidated history (replaces 9 fix docs)
    ├── SECURITY.md            # security fixes + credential rotation
    ├── PRODUCTION_AUDIT.md    # the compliance audit (moved)
    ├── DISCLAIMER.md  PRIVACY.md  TERMS.md   # legal (kept; linked by the app)
```

Two structural moves are **optional / careful** (they change paths): folding
`tongpt-subscription/`+`wrappers/` into `contracts/`, and moving root
`verify_*.py`/`test_*.py` into `scripts/` and `tests/`. They're in a separate,
clearly-marked stage of the script. The dead-code and doc cleanup are zero-risk.

---

## 2. Delete list (categorized)

### A. Safe to delete — dead code, recoverable via git
| Path | Why |
| --- | --- |
| `original_main.py` | Not imported anywhere. Only a *comment* in `main.py:607` mentions it. |
| `bot/handlers/` | Dead stub. Its `register_handlers()` is never imported; the real handlers live in `handlers/`. (`bot/commands.py` is used — **keep it**.) |
| `.tmp-tongpt-bot-image.tar623475655` | 0-byte leftover Docker build artifact. |
| `ton_data.db` | 0 bytes, empty. |

### B. Stop tracking (keep locally, add to `.gitignore`)
| Path | Action |
| --- | --- |
| `notifications.db`, `ton_ecosystem.db`, `ton_tweets.db` | `git rm --cached` — runtime data that shouldn't be committed. App recreates them. |
| `bot.log` (978 KB) | Delete; `*.log` is already git-ignored. |

`.gitignore` is **missing `*.db`** — that's how these got committed. Fix in §4.

### C. Consolidate, then delete originals (content preserved in git history)
These 9 files all describe the **same "5 critical fixes" event** — pure redundancy:

`CHANGELOG.md` (old), `CHANGES.md`, `FIX_SUMMARY.md`, `FIXES_SUMMARY.md`,
`README_FIXES.md`, `VERIFICATION_REPORT.md`, `STATUS.txt`, `QUICK_START.md`,
`INDEX.md`  → replaced by **`docs/CHANGELOG.md`**.

`SECURITY_FIXES.md` + `CREDENTIAL_ROTATION.md` → **`docs/SECURITY.md`**.
`PRODUCTION_READINESS_AUDIT.md` → moved to **`docs/PRODUCTION_AUDIT.md`**.

### D. Keep
Legal pages `DISCLAIMER.md` / `PRIVACY.md` / `TERMS.md` (the app links them),
`README.md` (rewritten), and all code directories, Dockerfiles, requirements,
and tests.

### E. After Mini-App v2 is verified working
- Delete legacy `miniapp/` (vanilla JS).
- Rename `miniapp-v2/` → `miniapp/`.
- **Breaking:** update the static-serving path in `api/miniapp_server.py` (see §5).

### F. Local-only clutter (already untracked — optional, frees disk)
`myenv/` (a committed-by-accident virtualenv? no — untracked), `__pycache__/`,
`node_modules/`, `build/`. Safe to delete locally; all are git-ignored.

---

## 3. Environment audit result

Out of **93** keys in `.env.example`, only **2 are genuinely unused**:

- `REDIS_DB` — `utils/redis_conn.py` only reads `REDIS_HOST/PORT/PASSWORD`.
- `TONCENTER_API` — code uses a hardcoded base URL + a `DataSource` enum, not this var.

Everything else (the large `RATE_LIMIT_*`, `DEX_*`, `TON_HTTP_*`, breaker blocks)
**is** used — via `_env_int()/_env_float()/_env_bool()` wrappers in
`core/rate_limiter.py`, `services/dexscreener_service.py`,
`services/ton_data_service.py`, `services/moderation_service.py`. Do **not** strip
them. Action: remove only the 2 stale keys (done in `cleanup.sh`).

---

## 4. `.gitignore` fix

Add the missing rules (full file shipped):
```
*.db
*.db-journal
*.sqlite3        # already present
bot.log          # covered by *.log, kept explicit for clarity
.tmp-*
```

---

## 5. Breaking changes & how they're handled

1. **Mini-App serving path.** FastAPI mounts `StaticFiles(directory="miniapp")`
   (`api/miniapp_server.py:150`). The legacy app was raw static; v2 builds to
   `miniapp/dist`. After the rename you must:
   ```python
   # api/miniapp_server.py
   if os.path.isdir("miniapp/dist"):
       app.mount("/miniapp", StaticFiles(directory="miniapp/dist", html=True), name="miniapp")
   ```
   and rebuild (`cd miniapp && npm run build`). Until then, keep both folders.
2. **Tracked DB removal.** The app must recreate `notifications.db` etc. on boot.
   Verify a clean start before deleting local copies.
3. **Optional contract move.** If you fold `tongpt-subscription/` into
   `contracts/subscription/`, update `tact.config.json` / blueprint paths and any
   CI that references them.

---

## 6. Verification checklist (run after each stage)

```bash
# 0. Normalise line endings first (kills the CRLF "everything modified" noise)
git add --renormalize . && git commit -m "chore: normalize line endings"

# After dead-code + doc cleanup:
python -c "import main"            # imports still resolve
python test_import.py             # existing import smoke test
grep -rn "original_main" --include=*.py .   # only comments (or empty)
git status                         # only intended deletions

# After DB untracking:
# start the bot/api once → confirm it recreates the DBs and boots clean

# After Mini-App rename:
cd miniapp && npm install && npm run build && ls dist   # build succeeds
# hit /miniapp in the running server → app loads
```

Nothing here is irreversible: every deletion is a `git rm` recoverable with
`git checkout <prev-commit> -- <path>` or by restoring the backup branch the
script creates.
