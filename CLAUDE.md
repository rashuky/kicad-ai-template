# Rules for AI sessions

KiCad 10 hardware project. Read [README.md](README.md) for the tools and layout.
Project-specific facts go in the **Project** section at the end. Edit the rest only to change the workflow.

## Tools
- **kicad-cli** (on PATH): netlist, ERC, DRC, BOM, plots. The ground truth for connectivity.
- **kschlint** MCP (`sch_*`, `pcb_*` tools) or CLI `tools/kschlint`: lint, render to PNG, pin tips (`inspect`), free space (`free`), text fixer (`fix`).
- **Konnect** MCP: 200+ KiCad tools (schematic editing, PCB, routing, JLCPCB part search, ERC/DRC, exports). Use it when loaded.
- `python tools/sch_check.py snapshot|diff|bom`: before/after check of nets, ERC and BOM fields.
- `python tools/pdf2md.py <pdf>`: raw markdown from a datasheet PDF.
- `python tools/bom.py`: priced BOM in `out/` (Excel view, JLCPCB upload, distributor order list). Generated, never committed.
- `gh` for branches and PRs.
- If an MCP server is missing, ask the user to run `setup.cmd` and restart Claude Code. The CLI tools work without MCP.

## Git
- Never commit to `main`. One branch per change, then a PR with a description.
- No AI author, co-author or "generated with" lines in commits or PRs.
- Force-push only when the user asks.
- **Never merge a PR** unless the user says so for that PR.
- Work in stages as **stacked PRs** (each branch on top of the previous one). Do not wait for approval between stages: the user reviews later. Exception: a PCB routing plan waits for the user's go (`/plan-routing`).
- **Independent review after every commit:** a separate review agent checks the commit against the datasheets, the rules and the plan. Fix its findings in a follow-up commit before opening or updating the PR.
- If you work in a scratch `git worktree`, remove it after pushing. A branch checked out in a worktree cannot be checked out by the user.
- PR review comments: answer every comment. Resolve a thread only when a follow-up commit addressed it. Pure questions get an answer and stay open.
- When the user only asks a question, answer it. Do not edit files until asked.
- **After a PR of the stack is merged:** merge the new base into the next branch and cascade the merges up the stack (no force-push, each conflict resolved once). Never text-merge a `.kicad_pcb`: take the branch's own board when it is newer, or rebuild it from that branch's netlist with the build script. After every step: ERC, DRC with parity, and check the board is unchanged where it should be.
- Review agents recompute every number from the source data (prices, counts, totals), they do not just read the text. Shared BOM lines, price breaks and stale counts are where the mistakes hide.

## Before editing KiCad files
1. KiCad must be closed. Check for `*.lck` files in `kicad/`. If any exist, ask the user to close KiCad. Otherwise KiCad overwrites the edit on its next save.
2. `git status` must be clean for the files you touch.
3. `python tools/sch_check.py snapshot before` (baseline from the repo's `kicad/`).
4. Copy `kicad/` to the scratchpad, edit the copy, verify it (below, tools take the copy's folder as project), then copy the changed files back into `kicad/`.

## Editing rules
- `.kicad_*` files are S-expressions with **CRLF** line endings. Keep them.
- Escape `"` inside strings as `\"`.
- Every new item gets a fresh UUID.
- Symbols on a reused sheet need an `instances` entry per sheet path, with a unique reference each.
- Prefer KiCad built-in symbols and footprints. Parts missing from KiCad go into the project library `kicad/lib/Project.*` (already in the lib tables). No other external libraries.
- Search the `Diode`, `Device`, `Connector*` and vendor libraries before drawing a symbol or settling for a look-alike. Example: a unidirectional TVS is `Diode:SM6T*`, `Diode:SMAJ*` or `Diode:PTVS*` (drawn like a zener), `Device:D_TVS` is bidirectional.
- Changing a symbol's `lib_id`: embed the new library symbol in `lib_symbols`. A derived symbol (`extends`) must be flattened onto its parent's graphics with the units renamed. The pin positions must match the old symbol, or wires silently disconnect. The netlist diff proves it.
- Things with no part to buy or place (wire pads, test pads, fiducials): `in_bom no`, not DNP. DNP draws a red cross that reads as "removed". `tools/bom.py` names excluded refs in its checks.
- Field changes on a symbol (Value, MPN, LCSC Part, Datasheet, Description) go to the PCB footprint too. DRC with `--schematic-parity` flags every mismatch.
- Before drawing wires, get pin tips from `sch_inspect`. Wires end on pin tips, never on pin lines.
- **Pin stubs:** every pin starts with a straight wire of at least one grid step (1.27 mm) in the pin's own direction. Bends, junction dots, labels, power symbols and other pins attach at the end of that stub, never on the pin tip. Power symbols and PWR_FLAG need no stub of their own. Check: `python tools/sch_pin_stubs.py`.
- Place new blocks in space found by `sch_free_space`.
- Reference numbers by sheet (100s on sheet 1, 200s on sheet 2...) unless the Project section says otherwise.
- Insert new top-level items before `(sheet_instances` / `(embedded_fonts`, never just before the final `)`. Copied symbols need their per-pin `(pin "n" (uuid ...))` entries. Otherwise KiCad reports "an error was found ... automatically fixed" on load.
- After a scripted edit, ask the user to open the sheet in KiCad, save and close. Commit that re-save only after a netlist diff shows no change.

## Draw a new block in two passes
1. **Labels first.** Connect every pin with a net label (or a power symbol for rails). Text edits get connectivity right easily, and the netlist diff proves it.
2. **Then wires.** Replace the labels between parts that sit close together with wires that end on pin tips. Keep labels only for far-apart nets, buses and hierarchy. Place passives next to the pin they serve (pull-ups, decoupling, filters) so they can be wired.
3. The netlist must not change between pass 1 and pass 2 (`sch_check.py diff`).

A label-only schematic is hard to read. The labels are a verification step, not the result.

## Verify every schematic change
Details and commands: skill `/verify-schematic`.
1. `sch_check.py snapshot after --project <copy>` and `diff before after`. Only the intended nets may change. No new ERC violations unless expected and explained.
2. New parts carry `Manufacturer`, `MPN`, `LCSC Part` (diff flags missing ones).
3. Check diode polarity and pin mapping in the netlist, not by coordinates.
4. `sch_lint` on the changed sheets. No new errors. Move colliding fields and labels with `sch_fix` (write mode, netlist checked, rolled back on change). Fix geometry errors by hand.
5. `sch_render` around the changed refs and look at the PNG.
6. **Independent review:** launch a separate review agent with the diff, the netlist change and the datasheets. It checks against datasheets and this file. Fix or report its findings before the PR.
7. Tell the user to open the sheet in KiCad for a final visual check.

## PCB
**Never use an autorouter** (Freerouting, Konnect autoroute or any other), not even for "the last few nets".
It produces tracks nobody planned, splits power pours and leaves dead ends in dense spots. Every track is planned.

Stages, each a PR with an independent review:
1. **Constraints:** `docs/layout_rules.md` (per block: placement and routing checklist from the datasheet layout examples), net classes in the `.kicad_pro`, hard limits in the `.kicad_dru` (DRC errors, not advice).
2. **Placement** by script (functional groups, datasheet loops). Then review against `layout_rules.md`.
3. **Critical copper** by script and locked: power pours, buck loops, sense lines, high-current paths.
4. **Routing plan first:** `docs/routing_plan.md` with signal groups, a corridor and layer per group, via locations, inner-layer islands, the routing order, and one snapshot with the corridors drawn. The user approves the plan before routing. Skill `/plan-routing`.
5. **Routing** by script, group by group, in the plan's order: dense escapes (fine-pitch ICs) first, then power trees, then buses, then locals, GND last. DRC after every group: no new errors, the unconnected count only goes down.
6. **Final:** DRC 0 errors, 0 unconnected, parity 0, zones filled, fab DFM check.

Routing rules (defaults, edit per project):
- Layer directions: one outer layer runs N-S, the other E-W. Crossings switch layer at a via.
- Inner layers stay solid GND under signals. A power island on an inner plane only where no signal on the adjacent outer layer crosses its edge (a plane gap under a track forces the return current around it).
- Vias never in pads. Signal vias 0.6/0.3 mm, power vias sized per net class with ≥ 2 per amp at a layer change.
- Scripts are rerunnable from the placed board: the first routing script clears all tracks, the rest add locked copper. Never rerun build or placement scripts on a routed board.
- Corridors are planned by hand. A maze helper (`tools/pcb/maze.py`) may find the exact path inside a box the script gives it, with the layer directions as costs. It never picks the corridor, the order or the layers.
- Snapshots only at key points: plan, after the escapes, after the buses, final (`tools/pcb/snapshot.py` hides the GND fill).

## Verify every PCB change
- `kicad-cli pcb drc --schematic-parity`: diff against the previous report (`tools/pcb/drc_summary.py` counts errors per type and unconnected items per net).
- `pcb_lint`, `pcb_fix` for reference designators, `pcb_render` and look at it.

## KiCad python (pcbnew) pitfalls
- Run it with KiCad's interpreter: `C:/Program Files/KiCad/10.0/bin/python.exe`.
- Via width: `via.GetWidth(pcbnew.F_Cu)` / `SetWidth(pcbnew.F_Cu, w)`. Without the layer, KiCad 10 opens a blocking wx dialog.
- Deleting while iterating crashes: collect `list(board.GetTracks())` and zones first, then `board.Delete(item)`.
- `SaveBoard` can rewrite the `.kicad_pro`: back it up and restore it.
- DRU rules: KiCad evaluates `&&` and `||` left to right with equal precedence, so parenthesise every pair. The last matching rule wins: generic rules first, specific ones after. Scope special widths with `enclosedByArea('<rule area name>')` and check each rule with a negative test (a too-thin track must fail).
- Git Bash rewrites arguments that start with `/` into Windows paths (net names like `/SDA`) and `ref:path` in `git show`: set `MSYS_NO_PATHCONV=1`.
- After moving or swapping a pad, refill the zones before DRC (`pcbnew.ZONE_FILLER(board).Fill(board.Zones())`). Stale fills give false clearance errors.
- Footprint swaps after placement go into the placement fixup script, so a rerun of the routing chain keeps them. Keep the pad midpoint, not the footprint origin (origins differ between footprints). Build scripts place such parts by pad midpoint too.
- `Connector_Wire:SolderWire-<area>_..._D<x>mm_OD<y>mm`: D is the conductor diameter, not the drill. Read the pad from the footprint. The `_Relief` variants add strain-relief holes about 16 mm away: check the space.
- In Git Bash never run `cat > file` without a heredoc: it waits on stdin until the tool times out.

## Naming
- Sheet files: `PascalCase.kicad_sch`. Reused sheet instances: `<SheetType>_<Load>`, e.g. `HighSideSwitch_Pump`.
- Connectors are named after what plugs in (`Pump`, `Sensor1`), not `J3`.
- Branches: `kebab-case` describing the change.

## Design rules (defaults, edit per project)
- Passives: 0603 or larger (hand-solderable, cheap assembly).
- MLCC voltage rating ≥ 2x the rail voltage (DC bias derating).
- Inductive loads (motors, pumps, valves, relays, fans) get a flyback diode.
- Every enable and reset input is pulled to its **safe (off) level**, so loads stay off while the MCU boots or is unplugged: pull-down for active-high, pull-up for active-low. Exception: a reset whose asserted state is the safe one (e.g. an I/O expander that holds all outputs off in reset) is pulled to its active level.
- Open-drain flags pull up to the logic rail of the reader, never to a higher rail.
- Fuses and switches run at ≤ 75 % of rating in the worst case.
- Prefer parts in stock at LCSC/JLCPCB. Check lifecycle (avoid NRND/EOL).

## Cost rules (JLCPCB assembly)
- An **extended** library part costs a setup fee once per order and per BOM line. A **basic** part has no fee, but its piece price can be higher, and that difference repeats on every board.
- Swap to a basic part only when (new piece price - old piece price) × parts per board × boards per order stays below the fee at the planned order size. Price each BOM line at its total quantity: a line shared by several refs hits other price breaks than one ref alone.
- Bigger passive packages are not cheaper: in the basic library 0603 is the cheapest package for every common value (0805 about 1.5 to 2×, 1206 up to 4×). Go bigger only for a rating (voltage, DC bias, power).
- THT connectors are usually cheaper than SMD ones: genuine JST SMD costs several times the THT soldering labour it saves. Keep THT for anything that gets plugged or pulled.
- All parts on one side. A second side adds an assembly setup and a stencil.
- A cable that is soldered in needs no connector part: `Connector_Wire:SolderWire-*` pads, symbol excluded from the BOM (see KiCad pitfalls).
- Record every swap with old part, new part, why it is equivalent and the cost at 1 / 5 / 10+ boards (`docs/cost_estimate.md`).

## Datasheets
Details: skill `/add-part`.
- Every chosen non-commodity part gets `datasheet/<Part>.md` built from `datasheet/_TEMPLATE.md`. Convert the PDF (`tools/pdf2md.py`), condense, commit the PDF next to it.
- Keep the full conversion as `datasheet/full/<Part>.md` for lookup (troubleshooting, calibration, layout notes). Machine-converted tables can split or merge cells: check any value you rely on against the PDF.
- Record source URL, revision, date and lifecycle status.
- "Project notes" section: how the part is used, chosen values, margins.
- No official datasheet? Build the md from seller data and say so at the top.

## Records
- `docs/power_budget.md`: update whenever a load is added, removed or changed. Mark every value DS, EST or TBD.
- `tradeoff/<topic>.md`: requirements, candidates, decision, for every non-trivial choice.
- `decisions.md`: only decisions still waiting for the user. Delete a row once it is approved (no decision log). Point references to the deleted row at the approval ("approved in the PR #12 review").
- `TODO.md`: open questions and missing parts. Work for another repo (firmware, enclosure) lives in that repo's plan. TODO.md holds one pointer to it, no copied list.
- Generated files (BOM exports, priced lists, order lists) are not committed. The tool that makes them is.

## Writing
- Short and precise. Keep all facts, drop filler.
- No long dashes, no semicolons in prose, comments, commits or PRs.
- Tables carry the unit in [] in the header row (`Price [USD]`, `Current [A]`). Cells hold numbers only. Say whether a price is per board or for the whole order.

## Project
<!-- Fill in when starting a project. Examples: -->
- Board: _what it does, input power, rails_.
- Sources of truth: _e.g. firmware pin map file, requirements doc_. They win over this repo.
- Fab and assembly: _e.g. JLCPCB, 4 layers, PCBA with LCSC parts_.
