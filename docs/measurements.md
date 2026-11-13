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

After the code review, `scan` was fixed to look for invisible characters in
parameter descriptions too (`json.dumps(..., ensure_ascii=False)`). That only
changes `scan()` on live servers; `scan_sources.py` and the poisoned set call
`scan_text` on description strings, so the numbers above are unaffected. The
two dev sets were re-run after the fix and gave the same counts.

### Unseen test set (run once, at the end of session 2)

The repos were named in the session before download (in the message
that announced the dev re-run, not in a separate file); no pattern was
changed in this session, and the set was scanned exactly once, after all
other work. A second attempt, to print the matched text for each alarm,
was blocked before it ran; the matched text below was found by grepping the
source files instead.

getsentry/sentry-mcp now downloads as Sentry's "toolkit" repo (top folder
`toolkit-HEAD`), which also contains the Sentry CLI. supabase-community/supabase-mcp
downloads with top folder `mcp-HEAD`.

| repos (commit) | descriptions | flagged |
|---|---|---|
| getsentry/sentry-mcp (06b9eb7fcdc8), grafana/mcp-grafana (306d34a1b281), mongodb-js/mongodb-mcp-server (e607a7cec36a), hashicorp/terraform-mcp-server (3e38ca694399), cloudflare/mcp-server-cloudflare (a21972e21928) | 3,288 | 6 (0.18%) |

Per repo: sentry-mcp 1,597, mcp-server-cloudflare 615, mongodb-mcp-server
549, terraform-mcp-server 464, mcp-grafana 63.

All 6 alarms are false alarms:

- `other-tool` (2): mongodb-mcp-server `createCluster.ts` and
  `upgradeCluster.ts`, ordinary advice containing "before calling this tool".
- `conversation-data` (2): mongodb-mcp-server `eval-tests` type definitions:
  "System prompt" (`evalTypes.ts:34`) and "conversation history" in a prompt
  for an LLM judge (`datasetTypes.ts:90`). These are test-harness fields,
  not MCP tool descriptions.
- `sensitive-path` (2): sentry-mcp `packages/cli/src/lib/env-registry.ts`,
  help text for CLI environment variables: `.env` (line 99) and
  `~/.config` in `~/.config/sentry/` (line 165). Also not MCP tool
  descriptions.

The extractor takes every `description` string in the source, so the
denominator includes some text that is not a tool or parameter description
(as the last two bullets show). The rate is a rough figure, not exact.

## Session 1 (recorded in the README at commit e3de5c1)

Tuning set 955 descriptions (5 alarms before tuning, 0 after). Held-out set
1,652 descriptions (awslabs/mcp subset of 231 files + supabase-mcp): scanned
once after all changes, 6 alarms (0.36%). `must-call-first` was then
narrowed, which took the held-out set to 2 alarms (0.12%). From that point the
held-out set had been seen, so neither it nor this session's re-run of it
is an independent measurement. Poisoned examples: 9 of 12 flagged before
three patterns were added, 12 of 12 after.
