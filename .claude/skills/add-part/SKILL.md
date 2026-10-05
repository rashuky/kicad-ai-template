---
name: add-part
description: Choose and document a new part. Sourcing check, datasheet markdown, BOM fields, symbol and footprint, power budget. Use whenever a new non-commodity part enters the design.
---

# Add a part

1. **Choose.** Write or extend `tradeoff/<topic>.md` (requirements, 2 to 4 candidates, decision). Check stock and lifecycle at LCSC/JLCPCB (Konnect has JLCPCB part search). Avoid NRND/EOL.
   Note the JLCPCB library class (basic or extended) and the piece price at the planned order size. A basic part with the same ratings is only better if it is not dearer per piece (CLAUDE.md, Cost rules).
   Without Konnect: JLCPCB answers `POST https://jlcpcb.com/api/overseas-pcb-order/v1/shoppingCart/smtGood/selectSmtComponentList` with JSON `{"keyword": "<LCSC number or text>", "currentPage": 1, "pageSize": 10}` (add `"componentLibraryType": "base"` for basic parts only). No key. `tools/bom.py` uses it.
2. **Datasheet.** Download the PDF to `datasheet/<Part>.pdf`. Then
   ```sh
   python tools/pdf2md.py datasheet/<Part>.pdf
   ```
   Condense `datasheet/<Part>.raw.md` into `datasheet/<Part>.md` using `datasheet/_TEMPLATE.md`: ratings, pinout, the equations and tables the design uses, layout notes. Move the `.raw.md` to `datasheet/full/<Part>.md` (kept for lookup). Check every table value you copy against the PDF. Fill in the Project notes: how it is used, chosen values, margins.
3. **Symbol and footprint.** KiCad built-in first (search `C:/Program Files/KiCad/10.0/share/kicad/symbols` and `footprints`). If missing: add to `kicad/lib/Project.kicad_sym` and `kicad/lib/Project.pretty/`, 3D model in `kicad/lib/Project.3dshapes/`. Check pin numbers against the datasheet pinout, pad by pad.
4. **Fields.** `Manufacturer`, `MPN`, `LCSC Part`, `Datasheet` (URL) on the symbol.
5. **Power.** If it draws or switches current, update `docs/power_budget.md` (DS, EST or TBD per value).
6. **Place and wire,** then run `/verify-schematic`.
