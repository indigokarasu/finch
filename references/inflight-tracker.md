# In-flight tracker (finch:track)

Finch already reads sessions, journals and logs to mine corrections and directives, so it also keeps
the record of what is in flight: projects, in-flight tasks and todos. Finch only observes and records.
It never acts on an item, and it never reads email, calendar or Drive.

## Sources (read only)

1. Session transcripts (`session_search`).
2. Skill journals under `journals/` in the commons root (not archive folders).
3. Gateway, cron and kanban logs.

## Output (the only files it writes)

- `data/ocas-finch/tracker.json`: `projects` (id, name, summary, owner, last_activity, evidence),
  `inflight` (id, title, project, owner, state: in_progress | blocked | waiting_on_<owner> | stalled | done,
  started, last_seen, next_step, evidence) and `todos` (id, text, owner, project, added, status: open |
  done | dropped, evidence). Written atomically.
- `data/ocas-finch/tracker.md`: the same, readable on a phone: Waiting on you, In progress,
  Blocked or stalled, Todos, Projects grouped by Mentor's status.
- `journals/ocas-finch/track-<time>.json`: what the run changed and why.

Finch does not judge project status. Mentor tags it in `data/ocas-mentor/project-status.json`
(see the Mentor skill's `references/project-status.md`) and routes next steps to the owning skill.
Items close only with evidence (a journal or log line such as `project: <id>`); an in-flight item with
no activity for 7 days becomes `stalled`.

## Tool limits

The `finch:track` job runs with file access and session search only, and no MCP servers.
Nothing in this flow sends messages, edits jobs or configs, or changes calendars.
