"""Re-derive a board from its parent board file so the git diff shows only real changes.
usage: python tools/pcb/transplant.py <parent.kicad_pcb> <child.kicad_pcb> <out.kicad_pcb>

A routing script rerun gives every item a new uuid and KiCad may reorder the file, so the PR diff is the whole
board. This keeps the parent text where nothing changed. Top-level blocks are compared with their uuids stripped:
a parent block that has an equal block in the child is kept as is (same text, same uuids), child blocks with no
equal parent block are added, parent blocks with no equal child block are dropped. Then KiCad loads and saves the
result until the file is stable (KiCad python, KICAD_PY or the default install path).
Check the result with DRC like any other board. Use it for stacked PRs: parent = the board of the base branch.
"""
import collections
import os
import re
import subprocess
import sys

PY = os.environ.get("KICAD_PY", r"C:\Program Files\KiCad\10.0\bin\python.exe")


def blocks(path):
    s = open(path, encoding="utf-8", newline="").read().replace("\r\n", "\n")
    assert s.startswith("(kicad_pcb"), path
    out, i, n = [], s.index("\n") + 1, len(s)
    while True:
        while i < n and s[i] in " \t\n":
            i += 1
        if s[i] == ")":
            break
        d, j, ins = 0, i, False
        while True:
            ch = s[j]
            if ins:
                if ch == "\\":
                    j += 1
                elif ch == '"':
                    ins = False
            elif ch == '"':
                ins = True
            elif ch == "(":
                d += 1
            elif ch == ")":
                d -= 1
                if d == 0:
                    break
            j += 1
        out.append(s[i:j + 1])
        i = j + 1
    return s[:s.index("\n") + 1], out


def norm(b):
    return re.sub(r'\(uuid "[^"]+"\)', "", b)


def kind(b):
    return re.match(r"\((\w+)", b).group(1)


def main(parent, child, out):
    _, bp = blocks(parent)
    hc, bc = blocks(child)
    avail = collections.Counter(norm(b) for b in bc)
    res, dropped = [], 0
    for b in bp:
        k = norm(b)
        if avail[k] > 0:
            avail[k] -= 1
            res.append(b)
        else:
            dropped += 1
    pc = collections.Counter(norm(b) for b in bp)
    added = []
    for b in bc:
        k = norm(b)
        if pc[k] > 0:
            pc[k] -= 1
        else:
            added.append(b)
    kept = len(res)
    for b in added:                     # after the last kept block of the same kind
        idx = max([i for i, x in enumerate(res) if kind(x) == kind(b)], default=len(res) - 1)
        res.insert(idx + 1, b)
    open(out, "w", encoding="utf-8", newline="\n").write(hc + "".join("\t" + b + "\n" for b in res) + ")\n")
    for _ in range(4):                  # KiCad reorders some items on the first load: save until the file is stable
        before = open(out, encoding="utf-8", newline="").read()
        r = subprocess.run([PY, "-c", "import pcbnew,sys; b=pcbnew.LoadBoard(sys.argv[1]); pcbnew.SaveBoard(sys.argv[1], b)",
                            out], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr[-500:]
        if open(out, encoding="utf-8", newline="").read() == before:
            break
    else:
        sys.exit("board file does not settle")
    print(f"kept {kept}, dropped {dropped}, added {len(added)}: {dict(collections.Counter(kind(b) for b in added))}")


if __name__ == "__main__":
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    main(*sys.argv[1:4])
