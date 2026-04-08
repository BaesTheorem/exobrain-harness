---
name: process-supernote
description: OCR Supernote handwritten notes by extracting PNG pages and reading them with vision. Extracts text, tasks, and events from handwritten content. Use when the user mentions Supernote, handwritten notes, handwriting, "read what I wrote", "I wrote something down", "check my notebook", "any new handwritten notes", or when triggered by a scheduled task.
---

# Process Supernote

## Steps

### 1. Find new or modified Supernote files
- List `.note` files in `/Users/alexhedtke/My Drive/Supernote/Note/` (including subdirectories)
- Read `/Users/alexhedtke/Documents/Exobrain harness/processing-log.json`
- Compare file modification times against the log to find new or updated files

### 2. Extract pages from each .note file
Run the parser:
```bash
python3 "/Users/alexhedtke/Documents/Exobrain harness/transcript-processing/supernote-parser.py" "<note_file>" "/tmp/supernote_pages/<note_name>"
```
This outputs individual PNG page images, a JSON summary, and **per-page SHA-256 hashes** in `page_hashes`.

### 3. Diff pages using hashes (skip already-processed pages)
Compare the `page_hashes` from the parser output against the `pageHashes` stored in the processing log for this file:
- **New file** (no log entry): all pages are new — OCR all of them
- **Updated file** (log entry exists): only OCR pages whose hash differs from or doesn't exist in the stored `pageHashes`
- **Pages with identical hashes to a known blank page should be skipped** — blank Supernote pages produce identical hashes (e.g., two blank pages will share the same hash). If multiple pages at the end of a note share the same hash, they are likely blank — skip them unless their content hash differs from previously seen blank pages.
- Track which page numbers are new/changed for use in steps 5 and 6

### 4. OCR new/changed pages only
Read each **new or changed** PNG file using the Read tool (multimodal vision). For each page:
- Transcribe all handwritten text as accurately as possible
- Preserve structure (headers, bullet points, numbered lists)
- Note any diagrams or drawings briefly
- Skip pages that matched a previously stored hash (already processed)

### 5. Process extracted text
Analyze the OCR'd text for:
- **Tasks** → Route to Things 3
- **Events** → Route to calendar or Things 3 review task
- **Notes/ideas** → Add to daily note

### 6. Copy PNGs into vault
Copy the extracted PNG pages into the vault's attachments folder:
```
/Users/alexhedtke/Library/Mobile Documents/iCloud~md~obsidian/Documents/Exobrain/attachments/supernote/
```
Name them `<note_name>_page_<N>.png` (e.g., `20260322_170801_page_0.png`). Only copy new/changed pages.

### 7. Write to daily note
Determine the **creation date** from the `.note` filename (format `YYYYMMDD_HHMMSS`) and append to that date's daily note, not today's. For files without a date-based name, use the file's filesystem creation date.

Append under a `### Supernote` section. **Only include new/changed pages** — do not repeat previously processed content.

Embed the PNG pages directly so they're visible in Obsidian:

```markdown
### Supernote
#### [Note name] (pages X, Y, Z — new/updated)
![[supernote/20260322_170801_page_0.png]]
![[supernote/20260322_170801_page_1.png]]

> [OCR'd text from new/changed pages only, preserving structure]

**Tasks extracted**: [list of tasks created in Things 3]
**Connections**: [[relevant existing notes]]
```
- Embed paths use the shortest-path Obsidian convention (just `supernote/filename.png` since it's in `attachments/supernote/`)
- If ALL pages are new (first time processing), omit the "(pages X, Y, Z — new/updated)" suffix
- If no pages changed (all hashes match), skip this file entirely — do not write to daily note

### 8. Update processing log
Store `pageHashes` so future runs can diff against them:
```json
{
  "id": "Note/filename.note",
  "processedAt": "ISO-8601 timestamp",
  "source": "supernote",
  "modifiedAt": "file modification timestamp",
  "pages": N,
  "pageHashes": { "0": "sha256...", "1": "sha256...", "2": "sha256..." },
  "itemsCreated": { "tasks": N, "notes": N, "events": N }
}
```
- On re-processing, **replace** the previous log entry for this file (same `id`) with the updated entry containing the full merged `pageHashes` map
- The `pageHashes` map should always reflect the complete current state of all pages

### 9. Clean up temp files
Remove the extracted PNGs from `/tmp/supernote_pages/` after processing (vault copies are kept in `attachments/supernote/`).

### 10. Notify
```bash
osascript -e 'display notification "OCR: X new pages from [note name] (Y unchanged skipped)" with title "Exobrain" sound name "Purr"'
```
