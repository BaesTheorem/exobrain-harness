---
description: Contribute to a GitHub repo end to end, as the repo owner -- bounties, security reports, or reputation PRs.
argument-hint: [issue/PR/repo url, or empty to take the newest winnable bounty]
---
Invoke the **github** skill (via the Skill tool) to handle the request below, then follow that skill's instructions. Read the repo's note in `~/Exobrain/Areas/Contribution & Impact/GitHub Contributions/Repos/` before touching the repo, and update it afterward. Run `/de-ai` over every outward artifact.
If no request is given, take the newest unworked winnable bounty from `watchers/bounty-hunter/candidates.jsonl` (or `watch.py --list`) and run the skill's full autonomous flow.
Note: `watchers/` is local-only and gitignored (personal watcher configs and state), so it will be absent in a fresh clone.

Request: $ARGUMENTS
