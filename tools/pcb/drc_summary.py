"""DRC with schematic parity, summarised: errors per type, unconnected items per net.
usage: python tools/pcb/drc_summary.py <board.kicad_pcb> [--net SUBSTRING] [--all]

Runs kicad-cli (must be on PATH). --all also counts warnings. --net lists the unconnected pairs of matching nets.
Use it after every routing group: no new errors, and the unconnected count only goes down.
"""
import argparse
import collections
import json
import os
import re
import subprocess
import sys
import tempfile


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("board")
    ap.add_argument("--net", default="")
    ap.add_argument("--all", action="store_true")
    a = ap.parse_args()
    out = os.path.join(tempfile.gettempdir(), "drc_summary.json")
    cmd = ["kicad-cli", "pcb", "drc", "--schematic-parity", "--format", "json", "-o", out, a.board]
    if not a.all:
        cmd[4:4] = ["--severity-error"]
    if os.path.exists(out):
        os.remove(out)                                    # never read a report from an earlier run
    r = subprocess.run(cmd, capture_output=True, text=True)
    if not os.path.exists(out):
        sys.exit(f"kicad-cli drc failed: {r.stderr.strip() or r.stdout.strip()}")
    d = json.load(open(out, encoding="utf-8"))
    viol = collections.Counter((v["severity"], v["type"]) for v in d["violations"])
    print("violations:", sum(viol.values()), dict(viol))
    for v in d["violations"]:
        if v["severity"] == "error":
            print("  ", v["type"], "|", " / ".join(
                f"{i['description'][:60]} @({i['pos']['x']:.2f},{i['pos']['y']:.2f})" for i in v["items"]))
    per_net = collections.Counter()
    for u in d["unconnected_items"]:
        for i in u["items"]:
            m = re.search(r"\[([^\]]+)\]", i["description"])
            if m:
                per_net[m.group(1)] += 1
    print("unconnected:", len(d["unconnected_items"]), "| parity:", len(d.get("schematic_parity", [])))
    for n, k in sorted(per_net.items()):
        print(f"  {k:4d} {n}")
    if a.net:
        for u in d["unconnected_items"]:
            if any(a.net in i["description"] for i in u["items"]):
                print("  ", " <-> ".join(
                    f"{i['description'][:45]} @({i['pos']['x']:.1f},{i['pos']['y']:.1f})" for i in u["items"]))


if __name__ == "__main__":
    main()
