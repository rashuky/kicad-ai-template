---
name: verify-schematic
description: Verify a KiCad schematic change before commit. Netlist and ERC diff, BOM fields, readability lint, render, independent review. Use after every schematic edit.
---

# Verify a schematic change

Run from the repo root. `WORK` is the scratchpad copy of `kicad/` that holds the edit (CLAUDE.md: edit a copy).
The repo's `kicad/` is still the old state, so it is the baseline.

## 1. Connectivity, ERC, BOM
```sh
python tools/sch_check.py snapshot before                   # repo kicad/, if not taken yet
python tools/sch_check.py snapshot after --project "$WORK"
python tools/sch_check.py diff before after
```
- **Nets:** every added, removed or changed net must be one you intended. An unexpected change means a wire end missed a pin tip or a label was renamed.
- **ERC:** new violations need a fix or a written reason in the PR.
- **BOM:** `!` lines are new parts missing `Manufacturer`, `MPN` or `LCSC Part`. Fill them.

## 2. Pin mapping and polarity
Read the changed nets in `.check/after/netlist.net` (node `pinfunction`). Check against the datasheet:
diode anode/cathode, FET gate/drain/source, IC pin numbers vs footprint pads, connector pinout.
Never conclude from coordinates.

## 3. Readability
- `sch_lint` (MCP, project = `$WORK`) or `tools/kschlint lint "$WORK" --sheet <Sheet>`. No new errors.
- Text collisions: `sch_fix` with write, or `tools/kschlint fix "$WORK" --sheet <Sheet> --write`. It rolls back if the netlist changes.
- Geometry errors (wire through body, wire end on pin line, body overlap): fix by hand, then lint again.

## 4. Look at it
`sch_render` with `around` = the changed refs (CLI: `tools/kschlint render "$WORK" --sheet <Sheet> --around U101,R101`).
Open the PNG and check that it reads like a schematic a human drew. Nearby parts are wired, not joined by labels (CLAUDE.md, two passes).

## 5. Independent review
Launch a review agent (Agent tool) with: the git diff of the copy against `kicad/`, the `sch_check diff` output,
the relevant `datasheet/*.md` files and CLAUDE.md. Ask it to check values, pinout, polarity, ratings and margins
against the datasheets and the design rules. Fix or report every finding.

## 6. Apply and hand over
KiCad still closed (no `kicad/*.lck`): copy the changed files from `$WORK` into `kicad/`, then
`python tools/sch_check.py snapshot applied` and `diff after applied` must show no change.
Tell the user which sheets changed and ask them to open them in KiCad for a final visual check.
