# Session mining via direct state.db (interactive-session recovery)

When `session_search` drowns interactive sessions under cron noise (or fails outright),
mine the profile's session store directly. Confirmed working recipe, extracted 2026-07-16
during an `ocas-finch:daily` run where `session_search` returned only cron sessions and
missed all 12 interactive Telegram sessions.

## Why state.db directly

- Under the **indigo** cron profile, `session_search` reads the **DEFAULT** profile store
  (`/root/.hermes/state.db`), not the indigo one. Interactive sessions live in
  `/root/.hermes/profiles/indigo/state.db`. Query the indigo store directly.
- `state.db` is live and may be locked by the gateway. A plain `sqlite3.connect(db)` can
  **hang** (observed 60s timeout). Always open **read-only with a busy_timeout**:
  `sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=8)` + `PRAGMA busy_timeout=5000`.
- `execute_code` is blocked in the indigo cron profile — run the recipe via `terminal python3`.

## Tables

- `sessions`: id, source, user_id, display_name, started_at, ended_at, message_count, title, ...
- `messages`: id, session_id, role, content, timestamp, tool_calls, ...

`messages.content` is frequently a **JSON array of parts** (e.g. `[{"type":"text","text":"..."}]`),
not a bare string. Parse it before scanning.

## Recipe (daily/weekly 24h window)

```python
import sqlite3, time, json
db = "/root/.hermes/profiles/indigo/state.db"
conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=8)
conn.execute("PRAGMA busy_timeout=5000")
cur = conn.cursor()

cut = time.time() - 24*3600   # widen to 7d for weekly

# 1) interactive (non-cron) sessions in window
cur.execute("""SELECT id, source, display_name, started_at, message_count
               FROM sessions WHERE started_at>=? AND (source IS NULL OR source NOT LIKE 'cron%')
               ORDER BY started_at DESC""", (cut,))
sids = [r[0] for r in cur.fetchall()]

# 2) pull user-role messages from those sessions
q = ",".join("?"*len(sids))
cur.execute(f"""SELECT m.session_id, m.timestamp, m.content FROM messages m
               WHERE m.role='user' AND m.session_id IN ({q}) ORDER BY m.session_id, m.timestamp""", sids)
rows = cur.fetchall()

def text(c):
    if not c: return ""
    try:
        if c.strip().startswith("["):
            parts = json.loads(c)
            return " ".join(p.get("text", str(p)) if isinstance(p, dict) else str(p) for p in parts)
    except Exception: pass
    return c

for sid, ts, content in rows:
    t = text(content).strip()
    if not t: continue
    # 3) DROP context-compaction system headers — they are FALSE POSITIVE signal hits
    if t.startswith("[CONTEXT COMPACTION") or "REFERENCE ONLY" in t[:60]:
        continue
    # t is now a real user message — scan for corrections/directives/breakthroughs
```

## Confirming "no interactive sessions"

If step 1 returns nothing, verify cron didn't eat everything — check user-role messages
grouped by session source:

```python
cur.execute("""SELECT m.session_id, s.source, count(*) FROM messages m
               LEFT JOIN sessions s ON m.session_id=s.id
               WHERE m.role='user' AND m.timestamp>=? GROUP BY m.session_id
               ORDER BY max(m.timestamp) DESC""", (cut,))
```

If every row's `source` is `cron`, there were genuinely no interactive sessions → safe to
report "no behavioral signals." Otherwise a non-cron source exists and step 1 missed it
(re-run with wider window / looser source filter).

## MEMORY.md path trap (same root cause)

A bare `read_file('~/.hermes/MEMORY.md')` under indigo cron resolves to the **DEFAULT**
profile memory, which differs in path AND content from the indigo profile memory at
`/root/.hermes/profiles/indigo/memories/MEMORY.md`. **Always target the explicit
profile path** when reading/editing memory under indigo cron. The `finch` job compacts the
default-profile MEMORY.md; `ocas-finch:daily`/`weekly` operate on the indigo one —
guard the `--file` override or you compact the wrong memory.
