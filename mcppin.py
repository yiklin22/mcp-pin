"""mcp-pin: pin an MCP server's tool definitions and scan them for hidden instructions.

  mcp-pin lock  [--file mcp-lock.json] -- <server command...>   record each tool's definition hash
  mcp-pin check [--file mcp-lock.json] -- <server command...>   fail if any tool was added, removed or changed
  mcp-pin scan                         -- <server command...>   fail if a description looks like a prompt injection

An MCP tool's description goes straight into the model's context. A server can
hide instructions there ("tool poisoning") or change a description after you
approved it ("rug pull"). `lock` + `check` catch the second in CI; `scan`
flags the common shapes of the first. The scan is a set of patterns, not a
proof: a clean scan does not mean a server is safe.
"""
import argparse
import hashlib
import json
import os
import re
import sys
import traceback
import unicodedata

import anyio
from mcp import Client, StdioServerParameters
from mcp.shared.exceptions import MCPError

PATTERNS = [
    ("hidden-tag", re.compile(r"<\s*/?\s*(important|system|instructions?|secret|admin)\b", re.I)),
    ("conceal-from-user", re.compile(r"\b(do\s*n[o']t|never|without)\s+(tell|telling|inform|informing|mention|mentioning|show|showing|notify|notifying)(ing)?\s+(the\s+)?user", re.I)),
    ("override", re.compile(r"\b(ignore|disregard|override)\s+(all\s+|any\s+)?(previous|prior|other|above)\s+(instructions|rules|tools?)", re.I)),
    ("sensitive-path", re.compile(r"(~|\$HOME|/home/\w+|/Users/\w+)/\.(ssh|aws|cursor|config|gnupg)|id_rsa|\.env\b|mcp\.json|\.aws/credentials|credentials\.json", re.I)),
    ("other-tool", re.compile(r"\b(before|when|instead of)\s+(using|calling)\s+(the\s+)?[`'\"]?\w+[`'\"]?\s+tool|"
                              r"\bwhen(ever)?\s+(the\s+)?[`'\"]?\w+[`'\"]?\s+tool\s+is\s+(used|called|invoked)", re.I)),
    ("conceal-from-user", re.compile(r"\b(never|don't|do\s+not)\s+(mention|tell|reveal|disclose|show)\b[^.]{0,40}\b(to\s+)?the\s+user", re.I)),
    ("conversation-data", re.compile(r"\b(conversation|chat)\s+history|previous\s+messages|system\s+prompt|"
                                     r"all\s+(prior|previous)\s+(messages|turns)", re.I)),
    ("must-call-first", re.compile(r"\b(must|always)\s+(first\s+)?(read|send|include|pass)\b[^.]{0,60}?"
                                   r"\b(file|contents?|keys?|tokens?|history|credentials?|passwords?|config|secrets?|\.env)\b", re.I)),
    ("long-base64", re.compile(r"[A-Za-z0-9+/]{80,}={0,2}")),
]
INVISIBLE = {"Cf", "Co", "Cn"}  # format chars (zero-width, bidi), private use, unassigned
REASONS = {
    "hidden-tag": "a tag like <IMPORTANT> marks text as orders for the model; users rarely read it",
    "conceal-from-user": "asks the model to keep something from the user",
    "override": "tries to cancel the model's other instructions",
    "sensitive-path": "names a file that holds keys, credentials or MCP config",
    "other-tool": "gives orders about when or how a tool is called; can shadow another tool",
    "conversation-data": "asks for the conversation, earlier messages or the system prompt",
    "must-call-first": "demands that a file or secret be read or sent along",
    "long-base64": "a long encoded string can hide instructions or data",
    "invisible-chars": "invisible Unicode characters can hide text from the user",
    "added": "tool is not in the lock file; review it, then run mcp-pin lock",
    "removed": "tool in the lock file is gone; review, then run mcp-pin lock",
    "changed": "description differs from the lock file; review it, then run mcp-pin lock",
    "changed-schema": "input schema or annotations differ from the lock file; review, then run mcp-pin lock",
}


def definition(tool) -> dict:
    return {
        "name": tool.name,
        "description": tool.description or "",
        "input_schema": tool.input_schema,
        "annotations": tool.annotations.model_dump(exclude_none=True) if tool.annotations else None,
    }


def digest(defn: dict) -> str:
    return hashlib.sha256(json.dumps(defn, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def lock_data(tools) -> dict:
    return {"tools": {t.name: {"sha256": digest(definition(t)), "description": t.description or ""}
                      for t in sorted(tools, key=lambda t: t.name)}}


def finding(tool: str, rule: str, match: str, reason: str = "") -> dict:
    return {"tool": tool, "rule": rule, "match": match, "reason": REASONS[reason or rule]}


def compare(lock: dict, tools) -> list[dict]:
    now = lock_data(tools)["tools"]
    old = lock["tools"]
    out = [finding(n, "added", now[n]["description"]) for n in sorted(now.keys() - old.keys())]
    out += [finding(n, "removed", old[n]["description"]) for n in sorted(old.keys() - now.keys())]
    out += [finding(n, "changed", now[n]["description"],
                    "changed" if now[n]["description"] != old[n]["description"] else "changed-schema")
            for n in sorted(now.keys() & old.keys()) if now[n]["sha256"] != old[n]["sha256"]]
    return out


def matches(text: str) -> dict[str, str]:
    """Rule name -> the first text it matched."""
    hits = {}
    for name, rx in PATTERNS:
        m = rx.search(text)
        if m and name not in hits:
            hits[name] = m.group(0)
    invisible = sorted({f"U+{ord(ch):04X}" for ch in text if unicodedata.category(ch) in INVISIBLE})
    if invisible:
        hits["invisible-chars"] = " ".join(invisible)
    return hits


def scan_text(text: str) -> list[str]:
    return list(matches(text))


def scan(tools) -> list[dict]:
    out = []
    for t in tools:
        hits = {}
        for text in [json.dumps(t.input_schema, ensure_ascii=False), t.description or ""]:
            hits.update(matches(text))  # the description's match wins
        out += [finding(t.name, rule, hits[rule]) for rule in sorted(hits)]
    return out


def show(f: dict) -> str:
    m = " ".join(f["match"].split())
    m = m if len(m) <= 70 else m[:69] + "…"
    return f'{f["tool"]}: {f["rule"]}: {json.dumps(m, ensure_ascii=False)} -- {f["reason"]}'


def leaves(e: BaseException) -> list:
    """The exceptions inside an exception group, or just e."""
    subs = getattr(e, "exceptions", None)
    if isinstance(subs, (list, tuple)) and subs:
        return [leaf for sub in subs for leaf in leaves(sub)]
    return [e]


async def list_tools(server) -> list:
    async with Client(server) as c:
        return list((await c.list_tools()).tools)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="mcp-pin", description=__doc__.split("\n")[0])
    ap.add_argument("action", choices=["lock", "check", "scan"])
    ap.add_argument("--file", default="mcp-lock.json")
    ap.add_argument("--format", choices=["text", "json"], default="text")
    argv = sys.argv[1:] if argv is None else list(argv)
    if "--" not in argv or argv.index("--") == len(argv) - 1:
        ap.error("give the server command after --")
    i = argv.index("--")
    a, cmd = ap.parse_args(argv[:i]), argv[i + 1:]
    if a.action == "check":
        try:
            with open(a.file) as f:
                lock = json.load(f)
            if not (isinstance(lock, dict) and isinstance(lock.get("tools"), dict) and all(
                    isinstance(e, dict) and isinstance(e.get("sha256"), str) and isinstance(e.get("description"), str)
                    for e in lock["tools"].values())):
                raise ValueError("not an mcp-pin lock file")
        except (OSError, ValueError) as e:
            ap.error(f"cannot read lock file {a.file} ({e}); run mcp-pin lock first")
    try:
        tools = anyio.run(list_tools, StdioServerParameters(command=cmd[0], args=cmd[1:], env=dict(os.environ)))
    except Exception as e:  # exit 2, so a broken setup is never mistaken for findings (exit 1)
        found = leaves(e)
        if not all(isinstance(x, (OSError, MCPError)) for x in found):
            traceback.print_exception(e)  # not a plain start/connection failure: may be a bug, show where
        causes = "; ".join(f"{type(x).__name__}: {x}" for x in found)
        print(f"mcp-pin: error talking to server {' '.join(cmd)}: {causes}", file=sys.stderr)
        return 2
    if a.action == "lock":
        try:
            with open(a.file, "w") as f:
                json.dump(lock_data(tools), f, indent=2)
        except OSError as e:
            print(f"mcp-pin: cannot write lock file {a.file}: {e}", file=sys.stderr)
            return 2
        problems = []
    else:
        problems = compare(lock, tools) if a.action == "check" else scan(tools)
    if a.format == "json":
        print(json.dumps({"command": a.action, "tools": len(tools), "findings": problems}, indent=2))
    elif a.action == "lock":
        print(f"locked {len(tools)} tools in {a.file}")
    else:
        for p in problems:
            print(show(p))
        print(f"{len(tools)} tools, {len(problems)} {'changes' if a.action == 'check' else 'findings'}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
