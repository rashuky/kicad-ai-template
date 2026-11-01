---
name: product-cost
description: Build and keep the product BOM and cost estimate in bom/, priced live at TME, Farnell, Mouser, DigiKey and JLCPCB, at the cheapest shop mix with shipping. Also ad hoc shopping lists outside the repo. Use when parts are added or changed, when the user asks what the product costs or where to buy parts, or before ordering.
---

# Product cost and BOM

The cost model is `tools/bom_cost.py` with `tools/suppliers.py`. Folder layout, columns and API keys: [bom/README.md](../../../bom/README.md).

## 1. Shop access
1. Check the keys: run `python tools/bom_cost.py --no-board` and read the check "Distributor API keys set".
2. A missing key: give the user the table in `bom/README.md` ("API keys") and the `Read-Host` snippet. Keys go into user environment variables only. Never ask for a key in the chat, never print one, never commit one. Mask key values in any debug output.
3. After the user adds a key, VS Code (or the terminal) must restart to see it. To test before that, read the value from the user environment (`[Environment]::GetEnvironmentVariable(name, "User")`) inside the same command.
4. A key that answers 403: read the shop's current API docs before blaming the key (TME tokens made after 14 May 2026 work only with API v2).

## 2. Fill bom/purchase.csv
One row per part bought outside the JLCPCB assembly. Schematic parts JLCPCB cannot place go in too, with `Refs`.
1. **Part number first.** `Manufacturer` and `MPN` from the datasheet or the shop page. Equivalent numbers as `a~b` (JST loose `B...` and reel `S...` contacts). The tool searches every distributor by part number.
2. **Search words only when no distributor has a part number** (generic cables, modules): `Search` plus `Must` terms that every offer must hold (ratings like `>=6A`, `a~b` alternatives, Polish words for Farnell and Mouser). Check every "found by search" result by hand.
3. **No `Search` for a part chosen for its exact model** (a specific valve, sensor module): the tool never swaps it for a look-alike.
4. **Shops without an API** (Allegro, Amazon, small web shops): `Shop`, gross `Price`, `Currency`, `Price_date`, `Price_src` DS (read from the page or from the user) or EST, `Link`. Prices come from the user's links, screenshots or search-result snippets. Never scrape past a bot check or CAPTCHA.
5. **Minimum orders.** Look at the minimum and multiple of the picked offer. A reel-only part (thousands of pieces) needs a loose-piece equivalent or another shop.
6. **Alternatives** are `option` rows with the same `Function`. "Where to save" in `cost.md` prices each one for the whole batch, shipping included.
7. Add every shop used to `bom/shops.csv` (shipping to Poland, free-shipping threshold, gross). Correct the estimates from a real cart.

## 3. Run and check
```
python tools/bom_cost.py                 # cost.md, cost.xlsx, board_bom.csv in bom/
```
- Every check in `cost.md` must be OK, or explained to the user.
- Read "Most expensive items" and "Where to save" and tell the user the top items and the largest savings.
- Links must open the product (Farnell needs the full `/maker/mpn/desc/dp/<sku>` link, the tool builds it).
- Commit the CSVs and the regenerated outputs together, then an independent review agent on the diff.

## 4. Ad hoc order (not committed)
The user wants to buy a few parts now: write `out/order.csv` (`Item`, `Qty`), run
```
python tools/bom_cost.py --order out/order.csv
```
and give the user `out/order.xlsx` (one block per shop, shipping, subtotal, links, alternatives). Nothing in `bom/` changes. If the file is open in Excel the tool says so: ask the user to close it and rerun.
