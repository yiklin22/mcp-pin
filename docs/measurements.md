# Measurements

Every number in the README comes from this file.

## How false alarms are measured

Running third-party servers is not needed: `scripts/scan_sources.py` reads
their `.ts`, `.py` and `.go` source files as text, pulls out every tool and
parameter description with regexes, and counts how many `mcppin.scan_text`
flags. Each repo was downloaded as a GitHub tarball of its default branch;
only `.ts`, `.py` and `.go` files were extracted.

```bash
python scripts/scan_sources.py <folder with one sub-folder per repo>
```

## 2026-11-13, session 2 (scan patterns as of commit e3de5c1, unchanged since)

| set | repos (commit) | descriptions | flagged |
|---|---|---|---|
| tuning (seen) | modelcontextprotocol/servers (e1dc4b18dbb9), github/github-mcp-server (6fbcd00b2034), microsoft/playwright-mcp (78eca85361ef) | 1,022 | 0 |
| former held-out (seen) | awslabs/mcp (5abaf6ad4d70), supabase-community/supabase-mcp (9092ab905550) | 4,147 | 2 (0.05%) |

Per repo: servers 259, github-mcp-server 762, playwright-mcp 1 (its tool
code has moved out of that repo), awslabs/mcp 4,043, supabase-mcp 104.
Session 1 used a 231-file subset of awslabs/mcp; this run used every
`.ts`/`.py`/`.go` file in it, so the counts differ.

The 2 alarms, both legitimate instructions to the model:

- `must-call-first` matched "Always include key" in
  awslabs `billing_cost_management_mcp_server/tools/recommendation_details_tools.py`
- `other-tool` matched "Before using this tool" in
  awslabs `billing_cost_management_mcp_server/tools/storage_lens_tools.py`
  ("Before using this tool, provide a 1-3 sentence explanation...")

Poisoned examples: `tests/poisoned.jsonl`, 12 of 12 flagged.

## Session 1 (recorded in the README at commit e3de5c1)

Tuning set 955 descriptions (5 alarms before tuning, 0 after). Held-out set
1,652 descriptions (awslabs/mcp subset of 231 files + supabase-mcp): scanned
once after all changes, 6 alarms (0.36%). `must-call-first` was then
narrowed, which took the held-out set to 2 alarms (0.12%). From that point the
held-out set had been seen, so neither it nor this session's re-run of it
is an independent measurement. Poisoned examples: 9 of 12 flagged before
three patterns were added, 12 of 12 after.
