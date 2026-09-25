# Rules for AI sessions

KiCad 10 hardware project. Read [README.md](README.md) for the tools and layout.
Project-specific facts go in the **Project** section at the end. Edit the rest only to change the workflow.

## Tools
- **kicad-cli** (on PATH): netlist, ERC, DRC, BOM, plots. The ground truth for connectivity.
- **kschlint** MCP (`sch_*`, `pcb_*` tools) or CLI `tools/kschlint`: lint, render to PNG, pin tips (`inspect`), free space (`free`), text fixer (`fix`).
- **Konnect** MCP: 200+ KiCad tools (schematic editing, PCB, routing, JLCPCB part search, ERC/DRC, exports). Use it when loaded.
- `python tools/sch_check.py snapshot|diff|bom`: before/after check of nets, ERC and BOM fields.
- `python tools/pdf2md.py <pdf>`: raw markdown from a datasheet PDF.
- `gh` for branches and PRs.
- If an MCP server is missing, ask the user to run `setup.cmd` and restart Claude Code. The CLI tools work without MCP.

## Git
- Never commit to `main`. One branch per change, then a PR with a description.
- No AI author, co-author or "generated with" lines in commits or PRs.
- Force-push only when the user asks.

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
- Before drawing wires, get pin tips from `sch_inspect`. Wires end on pin tips, never on pin lines.
- Place new blocks in space found by `sch_free_space`.
- Reference numbers by sheet (100s on sheet 1, 200s on sheet 2...) unless the Project section says otherwise.

## Verify every schematic change
Details and commands: skill `/verify-schematic`.
1. `sch_check.py snapshot after --project <copy>` and `diff before after`. Only the intended nets may change. No new ERC violations unless expected and explained.
2. New parts carry `Manufacturer`, `MPN`, `LCSC Part` (diff flags missing ones).
3. Check diode polarity and pin mapping in the netlist, not by coordinates.
4. `sch_lint` on the changed sheets. No new errors. Move colliding fields and labels with `sch_fix` (write mode, netlist checked, rolled back on change). Fix geometry errors by hand.
5. `sch_render` around the changed refs and look at the PNG.
6. **Independent review:** launch a separate review agent with the diff, the netlist change and the datasheets. It checks against datasheets and this file. Fix or report its findings before the PR.
7. Tell the user to open the sheet in KiCad for a final visual check.

## Verify every PCB change
- `kicad-cli pcb drc --schematic-parity`: diff against the previous report.
- `pcb_lint`, `pcb_fix` for reference designators, `pcb_render` and look at it.

## Naming
- Sheet files: `PascalCase.kicad_sch`. Reused sheet instances: `<SheetType>_<Load>`, e.g. `HighSideSwitch_Pump`.
- Connectors are named after what plugs in (`Pump`, `Sensor1`), not `J3`.
- Branches: `kebab-case` describing the change.

## Design rules (defaults, edit per project)
- Passives: 0603 or larger (hand-solderable, cheap assembly).
- MLCC voltage rating ≥ 2x the rail voltage (DC bias derating).
- Inductive loads (motors, pumps, valves, relays, fans) get a flyback diode.
- Every enable input gets a pull-down (or pull-up for active-low) so loads stay off while the MCU boots.
- Open-drain flags pull up to the logic rail of the reader, never to a higher rail.
- Fuses and switches run at ≤ 75 % of rating in the worst case.
- Prefer parts in stock at LCSC/JLCPCB. Check lifecycle (avoid NRND/EOL).

## Datasheets
Details: skill `/add-part`.
- Every chosen non-commodity part gets `datasheet/<Part>.md` built from `datasheet/_TEMPLATE.md`. Convert the PDF (`tools/pdf2md.py`), condense, commit the PDF next to it.
- Record source URL, revision, date and lifecycle status.
- "Project notes" section: how the part is used, chosen values, margins.
- No official datasheet? Build the md from seller data and say so at the top.

## Records
- `docs/power_budget.md`: update whenever a load is added, removed or changed. Mark every value DS, EST or TBD.
- `tradeoff/<topic>.md`: requirements, candidates, decision, for every non-trivial choice.
- `decisions.md`: decisions taken without the user. Each waits for review.
- `TODO.md`: open questions and missing parts.

## Writing
- Short and precise. Keep all facts, drop filler.
- No long dashes, no semicolons in prose, comments, commits or PRs.

## Project
<!-- Fill in when starting a project. Examples: -->
- Board: _what it does, input power, rails_.
- Sources of truth: _e.g. firmware pin map file, requirements doc_. They win over this repo.
- Fab and assembly: _e.g. JLCPCB, 4 layers, PCBA with LCSC parts_.
