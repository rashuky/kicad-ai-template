"""Schematic change check: snapshot netlist, ERC and BOM with kicad-cli, then diff two snapshots.

usage:
  python tools/sch_check.py snapshot NAME [--project PATH]
  python tools/sch_check.py diff OLD NEW
  python tools/sch_check.py bom NAME          (parts missing Manufacturer, MPN or LCSC Part)

Snapshots go to .check/NAME/ (git-ignored). Typical use around an edit:
  snapshot before  ->  edit  ->  snapshot after  ->  diff before after

diff exit code: 0 no net or ERC change, 1 changes found (read them, they may be the intended ones).
"""
import argparse, csv, glob, json, os, shutil, subprocess, sys
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHECK = os.path.join(ROOT, ".check")
BOM_FIELDS = ["Reference", "Value", "Footprint", "Manufacturer", "MPN", "LCSC Part", "DNP"]
REQUIRED = ["Manufacturer", "MPN", "LCSC Part"]


def kicad_cli():
    env = os.environ.get("KICAD_CLI")
    if env:
        return env
    p = shutil.which("kicad-cli")
    if p:
        return p
    for cand in glob.glob(r"C:\Program Files\KiCad\10.*\bin\kicad-cli.exe"):
        return cand
    sys.exit("kicad-cli not found. Run setup.ps1, put it on PATH or set KICAD_CLI.")


def find_root_sch(project):
    if project:
        p = os.path.abspath(project)
        if os.path.isdir(p):
            pros = glob.glob(os.path.join(p, "*.kicad_pro"))
            if len(pros) != 1:
                sys.exit(f"expected one .kicad_pro in {p}, found {len(pros)}")
            p = pros[0]
        return os.path.splitext(p)[0] + ".kicad_sch"
    pros = [p for p in glob.glob(os.path.join(ROOT, "**", "*.kicad_pro"), recursive=True)
            if os.path.relpath(p, ROOT).split(os.sep)[0] not in ("tools", ".check")]
    if len(pros) != 1:
        sys.exit(f"found {len(pros)} projects, pass --project: " + ", ".join(pros))
    return os.path.splitext(pros[0])[0] + ".kicad_sch"


def run(args):
    r = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        sys.exit(f"failed: {' '.join(args)}\n{r.stdout}{r.stderr}")


# ---- tiny S-expression reader for the kicadsexpr netlist ----
def parse_sexpr(text):
    stack, cur, i, n = [], [], 0, len(text)
    while i < n:
        c = text[i]
        if c == "(":
            stack.append(cur); cur = []; i += 1
        elif c == ")":
            done = cur; cur = stack.pop(); cur.append(done); i += 1
        elif c == '"':
            j, buf = i + 1, []
            while text[j] != '"':
                if text[j] == "\\":
                    j += 1
                buf.append(text[j]); j += 1
            cur.append("".join(buf)); i = j + 1
        elif c.isspace():
            i += 1
        else:
            j = i
            while j < n and not text[j].isspace() and text[j] not in '()"':
                j += 1
            cur.append(text[i:j]); i = j
    return cur[0]


def child(node, key):
    return next((c for c in node if isinstance(c, list) and c and c[0] == key), None)


def nets_of(path):
    tree = parse_sexpr(open(path, encoding="utf-8").read())
    nets = {}
    for net in child(tree, "nets")[1:]:
        name = child(net, "name")[1]
        nodes = sorted(f"{child(nd, 'ref')[1]}.{child(nd, 'pin')[1]}"
                       for nd in net[1:] if isinstance(nd, list) and nd[0] == "node")
        nets[name] = nodes
    return nets


def erc_of(path):
    d = json.load(open(path, encoding="utf-8"))
    out = Counter()
    for sheet in d.get("sheets", []):
        for v in sheet.get("violations", []):
            items = " | ".join(sorted(it.get("description", "") for it in v.get("items", [])))
            out[f"[{v.get('severity')}] {v.get('type')}: {v.get('description')} :: {sheet.get('path')} :: {items}"] += 1
    return out


def bom_of(path):
    with open(path, encoding="utf-8", newline="") as f:
        return {row["Reference"]: row for row in csv.DictReader(f)}


def snapshot(name, project):
    sch = find_root_sch(project)
    out = os.path.join(CHECK, name)
    os.makedirs(out, exist_ok=True)
    cli = kicad_cli()
    run([cli, "sch", "export", "netlist", sch, "-o", os.path.join(out, "netlist.net")])
    run([cli, "sch", "erc", sch, "--format", "json", "--severity-all", "-o", os.path.join(out, "erc.json")])
    run([cli, "sch", "export", "bom", sch, "-o", os.path.join(out, "bom.csv"),
         "--fields", ",".join(BOM_FIELDS), "--labels", ",".join(BOM_FIELDS), "--ref-range-delimiter", ""])
    nets, erc, bom = nets_of(os.path.join(out, "netlist.net")), erc_of(os.path.join(out, "erc.json")), bom_of(os.path.join(out, "bom.csv"))
    print(f"snapshot '{name}': {os.path.relpath(sch, ROOT)}  {len(bom)} parts, {len(nets)} nets, {sum(erc.values())} ERC violations")


def missing_fields(rows):
    return {ref: [f for f in REQUIRED if not row.get(f, "").strip()] for ref, row in rows.items()
            if row.get("DNP", "").strip() == "" and any(not row.get(f, "").strip() for f in REQUIRED)}


def diff(a, b):
    pa, pb = os.path.join(CHECK, a), os.path.join(CHECK, b)
    na, nb = nets_of(os.path.join(pa, "netlist.net")), nets_of(os.path.join(pb, "netlist.net"))
    ea, eb = erc_of(os.path.join(pa, "erc.json")), erc_of(os.path.join(pb, "erc.json"))
    ba, bb = bom_of(os.path.join(pa, "bom.csv")), bom_of(os.path.join(pb, "bom.csv"))
    changed = False

    print(f"== Nets ({a} -> {b})")
    for name in sorted(set(na) | set(nb)):
        if name not in nb:
            print(f"  - removed {name}: {' '.join(na[name])}"); changed = True
        elif name not in na:
            print(f"  + added   {name}: {' '.join(nb[name])}"); changed = True
        elif na[name] != nb[name]:
            gone, new = sorted(set(na[name]) - set(nb[name])), sorted(set(nb[name]) - set(na[name]))
            print(f"  ~ changed {name}:" + (f" -{' -'.join(gone)}" if gone else "") + (f" +{' +'.join(new)}" if new else ""))
            changed = True
    if not changed:
        print("  no change")

    print("== ERC")
    new, fixed = eb - ea, ea - eb
    for k, v in sorted(new.items()):
        print(f"  + new     {v}x {k}")
    for k, v in sorted(fixed.items()):
        print(f"  - gone    {v}x {k}")
    if not new and not fixed:
        print(f"  no change ({sum(eb.values())} violations)")
    changed |= bool(new or fixed)

    print("== BOM")
    added, removed = sorted(set(bb) - set(ba)), sorted(set(ba) - set(bb))
    edited = sorted(r for r in set(ba) & set(bb) if ba[r] != bb[r])
    for r in added:
        print(f"  + {r}: {bb[r]['Value']}  {bb[r]['Footprint']}")
    for r in removed:
        print(f"  - {r}: {ba[r]['Value']}")
    for r in edited:
        diffs = [f"{f}: '{ba[r].get(f, '')}' -> '{bb[r].get(f, '')}'" for f in BOM_FIELDS if ba[r].get(f) != bb[r].get(f)]
        print(f"  ~ {r}: " + ", ".join(diffs))
    if not (added or removed or edited):
        print("  no change")
    miss = {r: m for r, m in missing_fields(bb).items() if r in added or r in edited}
    for r, m in sorted(miss.items()):
        print(f"  ! {r} missing {', '.join(m)}")
    return 1 if changed else 0


def bom_check(name):
    rows = bom_of(os.path.join(CHECK, name, "bom.csv"))
    miss = missing_fields(rows)
    for r, m in sorted(miss.items()):
        print(f"{r}: missing {', '.join(m)}")
    print(f"{len(miss)} of {len(rows)} parts miss sourcing fields")
    return 1 if miss else 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("snapshot"); s.add_argument("name"); s.add_argument("--project")
    d = sub.add_parser("diff"); d.add_argument("old"); d.add_argument("new")
    b = sub.add_parser("bom"); b.add_argument("name")
    a = ap.parse_args()
    if a.cmd == "snapshot":
        snapshot(a.name, a.project)
    elif a.cmd == "diff":
        sys.exit(diff(a.old, a.new))
    else:
        sys.exit(bom_check(a.name))


if __name__ == "__main__":
    main()
