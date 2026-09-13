# Hermes Hooks Integration & Optimization Guide for Finch

This reference document outlines how **Finch** (the OCAS self-improvement orchestrator) optimizes its learning signal capture, memory governance, subagent delegation tracking, and prompt cache management using the **Hermes Agent Hooks system** (Gateway Hooks, Plugin Hooks, Shell Hooks, and Outbound Webhooks).

---

## Architecture Overview & Synergy

Hermes provides four hook lifecycle integration surfaces:

| Hook Type | Registration Point | Target Runtime | Finch Optimization Surface |
|-----------|--------------------|----------------|----------------------------|
| **Plugin Hooks** | `ctx.register_hook()` in a Python plugin | CLI, Gateway, Desktop, TUI | Real-time signal capture, memory tool guard, cache-safe system prompt sections, subagent monitoring |
| **Gateway Hooks** | `HOOK.yaml` + `handler.py` in `~/.hermes/hooks/` | Gateway process only | Gateway startup checks, platform event alerts, session compression notifications |
| **Shell Hooks** | `hooks:` block in `~/.hermes/config.yaml` | CLI, Gateway, Desktop, TUI | Subprocess fail-closed tool guards, argument modifications, shell-based context injection |
| **Outbound Webhooks** | `hooks.outbound:` list in `~/.hermes/config.yaml` | CLI, Gateway, Desktop, TUI | Asynchronous fleet telemetry, decision record streaming, external dashboard integration |

---

## 1. Real-Time Signal Mining vs. Offline Batch Mining

### The Problem
Historically, Finch relied solely on scheduled cron jobs (`finch:scan` every 2 hours, `ocas-finch:daily` at 6 AM) to mine session JSONL files for user corrections, directives, and breakthroughs. This meant learning signals were lagging behind real-time interaction by hours.

### Optimization Pattern: Passive Real-Time Observers
By registering plugin observers (`post_llm_call`, `agent_loop_stopped`, `on_session_end`), Finch can capture explicit learning signals instantly as turns complete:

- **`post_llm_call`**: Scans the completed user message and assistant response for explicit correction phrases (e.g., "Don't do X", "Always do Y", "Stop using tool Z").
- **`agent_loop_stopped`**: Detects mid-turn user interruptions (`/stop`, `/new`) to identify friction points or abandoned task trajectories.
- **`on_session_end`**: Flushes buffered session telemetry and checks if any high-priority directives were recorded during the session.

```python
# Real-time correction detection hook pattern
def on_turn_complete(session_id: str, user_message: str, assistant_response: str, **kwargs):
    signals = extract_learning_signals(user_message)
    if signals:
        buffer_realtime_signal(session_id, signals)
```

---

## 2. Memory Guard & Tool Interception

### The Problem
In Hermes profiles where Finch is active, manual edits to `MEMORY.md` via the built-in `memory` tool are restricted or blocked to prevent manual memory surgery, bloat, and prompt-cap exhaustion (`agent-hooks/block-memory-tool.sh`).

### Optimization Pattern: `pre_tool_call` Interceptor & Redirection
Using a `pre_tool_call` directive/control hook, attempts to invoke the built-in `memory` tool can be blocked or redirected to `scripts/memory_guard.py`:

```python
def memory_tool_interceptor(tool_name: str, args: dict, **kwargs):
    if tool_name == "memory":
        return {
            "action": "block",
            "message": "Direct memory edits via 'memory' tool are restricted. "
                       "Finch maintains MEMORY.md deterministically via scripts/memory_guard.py."
        }
    return None
```

In Shell Hook format (`config.yaml`):
```yaml
hooks:
  pre_tool_call:
    - matcher: "^memory$"
      command: "~/.hermes/agent-hooks/block-memory-tool.sh"
      fail_closed: true
```

---

## 3. Cache-Safe System Prompt Sections

### The Problem
Injecting dynamic rules or recalled memories into the LLM system prompt on every turn via un-bounded `pre_llm_call` callbacks mutates the system prompt text, invalidating model provider prompt caches (e.g., Anthropic, OpenAI) and driving up token latency and costs.

### Optimization Pattern: `register_system_prompt_section`
Plugins can register frozen, bounded system prompt sections that persist across turns without busting the prompt cache:

```python
def register(ctx):
    def render_finch_rules(session_info: dict) -> str:
        return "Finch Memory Rules:\n- Follow explicit Always/Never rules in MEMORY.md."

    ctx.register_system_prompt_section(
        section_id="finch.memory-rules",
        content_fn=render_finch_rules,
        position="after_memory",
        max_chars=2000
    )
```

**Key Contracts**:
- Anchor point is `after_memory`.
- Content is evaluated once per session and frozen across context compressions.
- Bounded at 4,000 characters per section (8,000 chars total across all sections).

---

## 4. Subagent Delegation Tracking (`subagent_start` & `subagent_stop`)

### The Problem
When Finch or an orchestrating agent spawns child agents via `delegate_task`, subagent errors, iteration limits, or successes are buried inside nested subagent session transcripts.

### Optimization Pattern: Lifecycle Observers for Delegation
Hermes exposes `subagent_start` and `subagent_stop` observer hooks:

- **`subagent_start`**: Records child task goal, parent session ID, child role, and allocated child subagent ID.
- **`subagent_stop`**: Receives `child_status` (`completed`, `failed`, `interrupted`), `child_summary`, `duration_ms`, and redacted `tool_call_history`.

```python
def on_subagent_completed(parent_session_id: str, child_role: str, child_status: str, duration_ms: int, **kwargs):
    if child_status != "completed":
        log_subagent_failure(parent_session_id, child_role, child_status)
```

---

## 5. Gateway Compression & Session Lifecycle Integration

### The Problem
When context compression triggers (`session:compress`) or a session resets (`session:reset`, `on_session_reset`), session state rotates. If `MEMORY.md` is near its character cap (~79%+ capacity), compaction should occur immediately before the new compressed session state is persisted.

### Optimization Pattern: Automated Compaction Gate
Hook into `session:compress` (Gateway Hook) or `on_session_reset` (Plugin Hook) to execute `scripts/memory_guard.py`:

```python
async def handle_session_compress(event_type: str, context: dict):
    # Gateway hook triggered on context compression
    if is_memory_near_capacity():
        run_memory_guard_compaction()
```

---

## 6. Outbound Webhooks for Multi-Agent Telemetry

For multi-agent setups or fleet monitoring, Finch decision records and real-time learning signals can be streamed to external dashboards without blocking the agent turn loop:

```yaml
hooks:
  outbound:
    - name: finch-telemetry
      url: https://monitoring.internal/finch/events
      events: [on_session_end, subagent_stop, post_tool_call]
      matcher: "delegate_task|memory_guard"
      secret_env: FINCH_WEBHOOK_SECRET
      timeout: 5
```

- Delivered asynchronously on a background thread.
- Signed with HMAC-SHA256 (`X-Hermes-Signature-256`).
- Retried once on network failure.
