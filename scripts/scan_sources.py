"""Scan tool and parameter descriptions found in MCP server source code.

  python scripts/scan_sources.py <folder of downloaded source files>

Reads .ts/.py/.go files as text (nothing is run), pulls out description
strings with regexes, and prints what `mcppin.scan_text` flags. Used to
measure false alarms on real servers without executing them.
"""
import collections, json, pathlib, re, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import mcppin
root = pathlib.Path(sys.argv[1])
STR = r'"((?:[^"\\]|\\.)*)"|\'((?:[^\'\\]|\\.)*)\'|`([^`]*)`'
pats = [
    re.compile(r'(?:description|Description)\s*[:=]\s*(?:t\(\s*"[^"]*"\s*,\s*)?(?:' + STR + r')((?:\s*\+\s*(?:' + STR + r'))*)', re.S),
    re.compile(r'\.describe\(\s*(?:' + STR + r')', re.S),
    re.compile(r'(?:WithDescription|mcp\.Description)\(\s*(?:t\(\s*"[^"]*"\s*,\s*)?(?:' + STR + r')', re.S),
    re.compile(r'description\s*=\s*"""(.*?)"""', re.S),
    re.compile(r'description\s*=\s*\(\s*((?:"[^"]*"\s*)+)\)', re.S),
]
found = []
for f in root.rglob("*"):
    if not f.is_file():
        continue
    src = f.read_text(errors="ignore")
    for rx in pats:
        for m in rx.finditer(src):
            parts = [g for g in m.groups() if g]
            text = " ".join(re.findall(r'"((?:[^"\\]|\\.)*)"', parts[0])) if rx is pats[4] else " ".join(parts)
            text = re.sub(r'\s*\+\s*', ' ', text).replace('\\n', ' ').replace('\\"', '"').strip()
            if len(text) >= 15:
                found.append((str(f.relative_to(root)), text))
uniq = sorted(set(found))
by_repo = collections.Counter(p.split("/")[0] for p, _ in uniq)
flagged = [(p, t, mcppin.scan_text(t)) for p, t in uniq if mcppin.scan_text(t)]
print("descriptions:", len(uniq), dict(by_repo))
print("flagged:", len(flagged), collections.Counter(h for _, _, hs in flagged for h in hs))
for p, t, h in flagged:
    print("--", h, p, "|", t[:220])
