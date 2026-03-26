---
name: process-supernote
description: OCR Supernote handwritten notes by extracting PNG pages and reading them with vision. Extracts text, tasks, and events from handwritten content. Use when the user says "process supernote", "read my handwriting", "check supernote", or when triggered by a scheduled task.
---

# Process Supernote

## Steps

### 1. Find new or modified Supernote files
- List `.note` files in `/Users/alexhedtke/My Drive/Supernote/Note/` (including subdirectories)
- Read `/Users/alexhedtke/Documents/Exobrain harness/processing-log.json`
- Compare file modification times against the log to find new or updated files
- Key files to always check: `Bujo 2026.note`, `Zettelkasten.note`, and any `YYYYMMDD_*.note` files

### 2. Extract pages from each .note file
Run the parser:
```bash
python3 "/Users/alexhedtke/Documents/Exobrain harness/supernote-parser.py" "<note_file>" "/tmp/supernote_pages/<note_name>"
```
This outputs individual PNG page images and a JSON summary.

### 3. OCR each page
Read each extracted PNG file using the Read tool (multimodal vision). For each page:
- Transcribe all handwritten text as accurately as possible
- Preserve structure (headers, bullet points, numbered lists)
- Note any diagrams or drawings briefly

### 4. Process extracted text
Analyze the OCR'd text for:
- **Tasks** → Route to Things 3 (same as transcript processing)
- **Events** → Route to calendar or Things 3 review task
- **Notes/ideas** → Add to daily note

### 5. Write to daily note
Append to today's daily note under a `## Supernote` section:
```markdown
## Supernote
### [Note name]
[OCR'd text, preserving structure]

**Tasks extracted**: [list of tasks created in Things 3]
**Connections**: [[relevant existing notes]]
```

### 6. Update processing log
```json
{
  "id": "Note/filename.note",
  "processedAt": "ISO-8601 timestamp",
  "source": "supernote",
  "modifiedAt": "file modification timestamp",
  "pages": N,
  "itemsCreated": { "tasks": N, "notes": N, "events": N }
}
```

### 7. Clean up temp files
Remove the extracted PNGs from `/tmp/supernote_pages/` after processing.

### 8. Notify
```bash
osascript -e 'display notification "OCR: X pages from [note name]" with title "Exobrain" sound name "Purr"'
```
