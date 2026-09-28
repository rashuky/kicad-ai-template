# Layout rules (placement and routing checklist)

Every PCB stage is checked against this file. Hard limits live in the project `.kicad_dru` (DRC errors).

## Stackup and planes
- _Layers, copper weight, fab stackup name._
- _Which layer is solid GND. In1 under the switching regulators must be GND (most buck datasheets say so)._
- _Which layers carry parts, power pours and signals._

## Current and widths
| Net / class | Current | Min track (DRC) | Default | Notes |
|---|---:|---:|---:|---|
| HighCurrent | | | | use pours, vias ≥ 0.8/0.4 mm, several per layer change |
| Power | ≤ 1 A | 0.5 mm | 0.6 mm | vias ≥ 0.6/0.3 mm, ≥ 2 per amp |
| Signals | < 50 mA | 0.15 mm | 0.2 mm | |

- Neck-downs and thin taps (Kelvin sense, µA branches) only inside named rule areas, each with its own DRC rule.
- Documented exceptions: _list each one with the reason and the current it carries._

## Per block (from the datasheet layout examples)
### _Buck converter_
- _Input cap loop, SW node area, FB divider at the IC away from SW (DRC rule), boot cap, GND return._

### _Load switches, current sense, MCU, connectors and ESD_
- _…_

## Silkscreen and fab
- _Reference placement, keep-outs, fab limits._
