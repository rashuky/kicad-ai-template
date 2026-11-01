# BOM and cost

What one complete unit of the product costs, delivered to Poland, at the cheapest suppliers, and where to save. Result: [cost.md](cost.md) (also `cost.xlsx`).

| File | Kept by | Content |
|---|---|---|
| `purchase.csv` | hand | Every part of a unit besides the JLCPCB board: modules, power, loads, sensors, wiring, mechanical, equipment. Part numbers, search terms, hand-kept prices, alternatives |
| `shops.csv` | hand | Shipping to Poland, free-shipping threshold (gross goods value, VAT included), delivery time per shop |
| `orders.csv` | hand | Placed JLCPCB orders. An `Amount` replaces the board estimate at that board count |
| `board_bom.csv` | `tools/bom_cost.py` | Fitted board parts per line, JLCPCB library and price |
| `cost.md`, `cost.xlsx` | `tools/bom_cost.py` | Cost per unit at 1, 5 and 10 units, most expensive items, where to save, every item with its supplier, distributor quotes, checks |

## Product cost

```
python tools/bom_cost.py
```

- Every `use` row is bought for a batch of units (`Qty_per_unit` x units, rounded up to whole pieces) at the cheapest combination of shops, shipping included. The batch total divided by the units is the cost per unit. Parts you already own count too: this is the product cost, not a shopping list.
- Batch sizes: `--units 1,5,10`. Item tables: `--detail 5`. Leave a shop out: `--skip-shop TME`.
- "Where to save" in `cost.md`: cheaper `option` rows per part (same `Function`), the effect of the batch size, hand estimates to verify, the board cost split.
- Needs kicad-cli (schematic BOM) and openpyxl (`cost.xlsx`). `--no-board` skips the schematic.
- Commit the CSVs and the regenerated outputs together.

## Ad hoc order (not in the repo)

```
python tools/bom_cost.py --order out/order.csv
```

- `out/order.csv` has two columns, `Item` and `Qty`. `Item` is a part number (any of the `~` equivalents) or the start of an `Item` name in `purchase.csv`.
- Writes `out/order.xlsx` and `out/order.md` (shopping list per shop with shipping and subtotals, links) and `out/order_list.csv`. `out/` is git-ignored. `--out` picks another folder.
- The same shop picking as the product cost, for the quantities in the file.

## Prices

Refreshed on every run: JLCPCB prices of the board parts, USD and EUR rates (NBP), distributor quotes. Every row is searched at TME, Farnell (pl.farnell.com), Mouser and DigiKey (PL site, PLN):

1. By `MPN`, matched loosely (case, dashes and spaces ignored: `EEE-FK1E221P` = `EEEFK1E221P`), same manufacturer. Every variant (cut tape, reel, pack) counts, the cheapest in-stock one at the quantity wins.
2. If no shop has that exact number: the same number with a packaging suffix only (`SHT40-CD1B-R3`, `-TR`, `-CT`, `-REEL`), from the named manufacturer. Marked for a check.
3. If no shop knows the part number: the `Search` words, kept only when the offer holds every `Must` term. Marked for a check.

The hand-kept price in `purchase.csv` competes with the quotes of the other shops. A live in-stock quote of the same part number from the row's own shop replaces it. Rows without `Search` (a specific module, a part chosen for its exact model) are never replaced by a look-alike. Shops without an API keep their hand-kept price: update `Price` and `Price_date`. The checks list prices older than 90 days. TME uses API v2 (keys made after 14 May 2026 do not work with v1).

## API keys

| Shop | Where | What you get | Environment variables |
|---|---|---|---|
| TME | developers.tme.eu, log in with the TME account, add an application (API v2) | token, application secret | `TME_TOKEN`, `TME_SECRET` |
| Farnell | partner.element14.com, register, register an application (Product Search API) | API key | `FARNELL_API_KEY` |
| Mouser | mouser.pl, My Account, APIs, Search API | API key | `MOUSER_API_KEY` |
| DigiKey | developer.digikey.com, create an organization, create a production app with ProductInformation V4, callback `https://localhost` | client ID, client secret | `DIGIKEY_CLIENT_ID`, `DIGIKEY_CLIENT_SECRET` |

All are free. Store them as user environment variables (PowerShell), then restart VS Code:

```
foreach ($n in "TME_TOKEN","TME_SECRET","FARNELL_API_KEY","MOUSER_API_KEY","DIGIKEY_CLIENT_ID","DIGIKEY_CLIENT_SECRET") {
  $v = Read-Host "$n (Enter to skip)"
  if ($v) { [Environment]::SetEnvironmentVariable($n, $v, "User") }
}
```

Keys never go into the repo or a chat.

Shops without a usable price API (prices hand-kept, `Price_src` DS when read from the page, EST for an estimate):

| Shop | Why |
|---|---|
| Allegro | The app key works, but offer search with prices (`/offers/listing`) is closed until Allegro enables it for the app. Ask on developer.allegro.pl. Send the User-Agent generated for the app |
| Amazon | The Product Advertising API is retired. Its successor needs an affiliate account with 10 sales |
| RS | The API portal did not give a working key |
| Small web shops | No customer API |

Never scrape shop pages past a bot check or CAPTCHA. The check "Distributor API keys set" lists the missing ones.

Shipping and free-shipping thresholds in `shops.csv` are mostly estimates. Correct them from the cart: the shop choice depends on them.

## purchase.csv

| Column | Meaning |
|---|---|
| `Group` | One of `GROUPS` in `tools/bom_cost.py` (edit the list per project). `Board` holds hand-fitted board parts, `Equipment` is counted once |
| `Function` | What the part does. An `option` row with the same `Function` is an alternative to the part in use |
| `Status` | `use` (part of the product) or `option` (alternative, compared under "Where to save", not counted) |
| `Qty_per_unit` | Amount one unit uses. Equipment rows: amount needed once |
| `Refs` | Schematic parts fitted by hand (left out of the JLCPCB board cost) |
| `MPN` | Manufacturer part number. Searched first at every distributor. Equivalent numbers separated by `~` (JST loose `B...` and reel `S...` contacts): each shop is quoted for the cheapest of them |
| `Search` | Search words for a part with no MPN, or one no distributor knows. Empty: no look-alikes |
| `Must` | Terms every search result must hold, separated by `\|`. `a~b` = a or b. `>=6A` = a value of at least 6 with the unit A in the description (ratings). Matched without spaces and case. A term with digits does not match inside a longer number (`20V` is not in `120V`). Farnell and Mouser describe parts in Polish: add Polish alternatives (`capacitive~pojemno`) |
| `Shop`, `Price`, `Currency` | Hand-kept offer: gross price each (VAT included) |
| `Price_src` | DS = read from the shop page, EST = estimate |
