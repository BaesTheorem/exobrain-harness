# Exobrain Command Queue

Drop command files here from any Claude Code session (phone, cloud, etc.).
The next capable session will pick them up and process them.

## How to use

1. Create a JSON file in this folder named `YYYY-MM-DD-HHMMSS-brief-label.json`
2. Use the schema below
3. The next session with full tool access will process pending commands

## Command file schema

```json
{
  "created_at": "2026-04-07T10:00:00Z",
  "from": "cloud",
  "command": "I decided to abandon X project. Update Things 3 and Obsidian accordingly.",
  "priority": "normal",
  "status": "pending"
}
```

### Fields

| Field | Required | Values |
|-------|----------|--------|
| `created_at` | yes | ISO 8601 timestamp |
| `from` | yes | `"cloud"`, `"phone"`, `"desktop"`, etc. |
| `command` | yes | Free-text instruction for Claude to execute |
| `priority` | no | `"low"`, `"normal"` (default), `"urgent"` |
| `status` | yes | `"pending"` initially; updated to `"completed"` or `"failed"` after processing |
| `processed_at` | no | Set by the processing session |
| `result` | no | Summary of actions taken |

### Priority

- **urgent**: Process immediately, notify via Discord
- **normal**: Process in next session startup sweep
- **low**: Process when convenient
