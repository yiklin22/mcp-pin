"""mcp-pin: pin an MCP server's tool definitions and scan them for hidden instructions.

  mcppin lock  [--file mcp-lock.json] -- <server command...>   record each tool's definition hash
  mcppin check [--file mcp-lock.json] -- <server command...>   fail if any tool was added, removed or changed
  mcppin scan                         -- <server command...>   fail if a description looks like a prompt injection

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
import unicodedata

import anyio
from mcp import Client, StdioServerParameters

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
    ("must-call-first", re.compile(r"\b(must|always)\s+(first\s+)?(read|send|include|pass)\b", re.I)),
    ("long-base64", re.compile(r"[A-Za-z0-9+/]{80,}={0,2}")),
]
INVISIBLE = {"Cf", "Co", "Cn"}  # format chars (zero-width, bidi), private use, unassigned


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


def compare(lock: dict, tools) -> list[str]:
    now = lock_data(tools)["tools"]
    old = lock["tools"]
    out = [f"added: {n}" for n in sorted(now.keys() - old.keys())]
    out += [f"removed: {n}" for n in sorted(old.keys() - now.keys())]
    out += [f"changed: {n}" for n in sorted(now.keys() & old.keys()) if now[n]["sha256"] != old[n]["sha256"]]
    return out


def scan_text(text: str) -> list[str]:
    hits = [name for name, rx in PATTERNS if rx.search(text)]
    if any(unicodedata.category(ch) in INVISIBLE for ch in text):
        hits.append("invisible-chars")
    return hits


def scan(tools) -> list[str]:
    out = []
    for t in tools:
        texts = [t.description or ""] + [json.dumps(t.input_schema)]
        hits = sorted({h for s in texts for h in scan_text(s)})
        if hits:
            out.append(f"{t.name}: {', '.join(hits)}")
    return out


async def list_tools(server) -> list:
    async with Client(server) as c:
        return list((await c.list_tools()).tools)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="mcppin", description=__doc__.split("\n")[0])
    ap.add_argument("action", choices=["lock", "check", "scan"])
    ap.add_argument("--file", default="mcp-lock.json")
    argv = sys.argv[1:] if argv is None else list(argv)
    if "--" not in argv or argv.index("--") == len(argv) - 1:
        ap.error("give the server command after --")
    i = argv.index("--")
    a, cmd = ap.parse_args(argv[:i]), argv[i + 1:]
    tools = anyio.run(list_tools, StdioServerParameters(command=cmd[0], args=cmd[1:], env=dict(os.environ)))
    if a.action == "lock":
        with open(a.file, "w") as f:
            json.dump(lock_data(tools), f, indent=2)
        print(f"locked {len(tools)} tools in {a.file}")
        return 0
    problems = compare(json.load(open(a.file)), tools) if a.action == "check" else scan(tools)
    for p in problems:
        print(p)
    print(f"{len(tools)} tools, {len(problems)} {'changes' if a.action == 'check' else 'flagged'}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
