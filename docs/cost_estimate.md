# BOM and cost estimate

Prices checked _YYYY-MM-DD_. Legend: **DS** = live distributor price, **EST** = estimate (check with a live quote).

BOM files are generated, not committed. `python tools/bom.py` writes to `out/`:
- `bom.xlsx`: priced view (JLCPCB and a European distributor, 1 / 5 / 10 boards, basic or extended, stock, lead time).
- `bom_jlcpcb.csv`: the JLCPCB assembly BOM upload.
- `bom_order_<N>.csv`: manufacturer, MPN, quantity for N boards. Upload it to the TME or Farnell BOM tool for a real quote.

Modules and other things bought for the board but not on the schematic (MCU module, display, PSU, cables) go into `docs/external_parts.csv`. The tool lists them too.

## Board facts

| Item | Value |
|---|---:|
| BOM lines / parts per board | _ / _ |
| SMD parts / joints | _ / _ |
| THT parts / joints | _ / _ |
| JLCPCB library: basic / extended lines | _ / _ |
| PCB | _W × H mm, layers, thickness_ |

- **BOM line:** one unique part (one MPN), however many times it is used.
- **Part:** one placed component (one reference).
- **Joint:** one soldered pad. JLCPCB charges assembly per joint, THT about 10× more than SMD.
- **Basic / extended:** JLCPCB library class. Each extended line costs a setup fee per order. Basic lines cost nothing extra.

## Components only

| Source | 1 board [USD] | 5 boards, total [USD] | Source |
|---|---:|---:|---|
| JLCPCB parts (for PCBA) | | | DS |
| European distributor | | | DS / EST |

## PCB fabrication (5 boards)

| Item | 5 pcs total [USD] | Per board [USD] | Source |
|---|---:|---:|---|
| Bare PCB | | | EST |
| Stencil | | | EST |
| Shipping | | | EST |

## Assembly scenarios (5 PCBs)

| Scenario | Parts [USD] | Extended fees [USD] | Assembly fees [USD] | PCB + ship [USD] | Total excl. VAT [USD] | With VAT [USD] | Per board [USD] |
|---|---:|---:|---:|---:|---:|---:|---:|
| A. Fab assembles everything | | | | | | | |
| B. Fab assembles SMD only, you solder THT | | | | | | | |
| C. Bare PCB + stencil, you assemble | | | | | | | |

## Recommendation
_Which scenario for the first prototypes and why._
