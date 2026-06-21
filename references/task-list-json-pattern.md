# task-list.json Read/Write Pattern for finch:work

## File Format (as of 2026-06-20)

The file on disk is **clean JSON** without embedded `LINE_NUM|` prefixes. The `read_file` tool adds `LINE_NUM|` prefixes as a display/transport artifact — this does NOT mean the file on disk has them. `json.dump()` via `terminal()` writes clean JSON correctly.

## Safe Read Pattern (via terminal)

```python
import json, re

with open('/root/.hermes/commons/data/ocas-finch/task-list.json', 'r') as f:
    raw = f.read()

# Only needed if read via read_file tool (which adds prefixes):
# clean = re.sub(r'^\d+\|', '', raw, flags=re.MULTILINE)
# data = json.loads(clean)

# If read via terminal('cat path') or open(), raw is already clean:
data = json.loads(raw)
```

## Safe Write Pattern (via terminal)

```python
import json

with open('/root/.hermes/commons/data/ocas-finch/task-list.json', 'w') as f:
    json.dump(data, f, indent=2)
```

## Full Pattern in terminal() Call

```bash
python3 << 'PYEOF'
import json, re

path = '/root/.hermes/commons/data/ocas-finch/task-list.json'

with open(path, 'r') as f:
    raw = f.read()

# Strip read_file display prefixes if present, then parse
clean = re.sub(r'^\d+\|', '', raw, flags=re.MULTILINE)
data = json.loads(clean)

for task in data['tasks']:
    if task['id'] == 'target-task-id':
        task['status'] = 'done'
        task['note'] = 'Completed by finch:work'

with open(path, 'w') as f:
    json.dump(data, f, indent=2)

print("OK")
PYEOF
```

## Status Values

- `pending` — not yet started
- `in_progress` — currently being worked
- `done` — completed successfully
- `cancelled` — no longer needed
- `blocked` — cannot proceed (missing permissions, external dependency)
- `needs_review` — requires human judgment

## Severity Values

- `low` — informational, no time pressure
- `medium` — actionable, moderate time sensitivity
- `high` — urgent, time-critical
