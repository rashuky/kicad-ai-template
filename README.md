# kicad-ai-template

A KiCad 10 project template for designing boards together with **Claude Code**.
It gives the AI eyes and a safety net: it can read and edit schematics, see what they look like,
and prove after every edit that only the intended connections changed.

Built and proven on a real 200-part board (a grow box controller with power stages, MCU, sensors and
10 switched loads). Windows 10/11 for now.

## How it works

```
             you (chat)                              KiCad (you look, you approve)
                 │                                          ▲
                 ▼                                          │ same files
          Claude Code ──── reads/edits ────►  kicad/*.kicad_sch, *.kicad_pcb  (plain text)
           │   │   │
           │   │   └── Konnect MCP ........ 200+ KiCad tools: schematic edits, PCB, routing,
           │   │                            JLCPCB part search, ERC/DRC, exports
           │   └────── kschlint MCP ....... lint (overlaps, wires through parts, floating labels),
           │                                PNG render, exact pin tips, free space, safe text fixer
           └────────── kicad-cli ......... netlist, ERC, DRC, BOM: the ground truth
                         via tools/sch_check.py: snapshot before, snapshot after, diff
```

The rules the AI follows are in [CLAUDE.md](CLAUDE.md): branch per change, edit a copy, verify
(netlist diff, ERC diff, BOM fields, lint, render, independent review agent), then PR.
Workflows live as Claude Code skills: `/start-project`, `/add-part`, `/verify-schematic`, `/plan-routing`.
PCBs are routed by planned scripts, never by an autorouter (helpers in `tools/pcb/`).

## Requirements

| Tool | Version | Why | Get it | setup.ps1 installs it |
|---|---|---|---|---|
| Windows | 10 / 11 | | | |
| [KiCad](https://www.kicad.org/download/windows/) | 10.0.x | the EDA suite, `kicad-cli` | `winget install KiCad.KiCad` | yes |
| [Git for Windows](https://git-scm.com/download/win) | any recent | version control, Git Bash for Claude Code | `winget install Git.Git` | yes |
| [Python](https://www.python.org/downloads/windows/) | 3.10+ | kschlint, check scripts | `winget install Python.Python.3.12` | yes |
| [pymupdf](https://pypi.org/project/PyMuPDF/), [pymupdf4llm](https://pypi.org/project/pymupdf4llm/) | latest | schematic render, PDF to markdown | `python -m pip install --user pymupdf pymupdf4llm` | yes |
| [Claude Code](https://code.claude.com/docs/en/setup) | latest | the AI | `irm https://claude.ai/install.ps1 \| iex` | yes (if neither CLI nor VS Code extension found) |
| [Konnect](https://github.com/mixelpixx/Konnect) | 0.12+ | KiCad plugin + MCP server | [release zip](https://github.com/mixelpixx/Konnect/releases/latest), KiCad Plugin Manager | yes |
| [kicad-sch-lint](https://github.com/rashuky/kicad-sch-lint) | submodule | lint, render, pin tips, fixer | `git submodule update --init` | yes |
| [GitHub CLI](https://cli.github.com/) | any | PRs from Claude Code | `winget install GitHub.cli` | yes |
| [VS Code](https://code.visualstudio.com/) + [Claude Code extension](https://marketplace.visualstudio.com/items?itemName=anthropic.claude-code) | optional | Claude Code in the editor | `winget install Microsoft.VisualStudioCode` | with `-WithVSCode` |

You also need a Claude subscription (Pro, Max, Team or Enterprise) or an Anthropic API key for Claude Code.

## Quick start

1. **Create your repo from the template.** On GitHub: **Use this template** → **Create a new repository**. Or:
   ```powershell
   gh repo create my-board --template rashuky/kicad-ai-template --private --clone
   cd my-board
   ```
   (`git clone --recursive` also works for a plain copy.)
2. **Close KiCad**, then run the setup from the repo folder:
   ```powershell
   .\setup.cmd
   ```
   It installs what is missing, adds `kicad-cli` to your PATH, fetches kschlint, installs Konnect,
   writes `.mcp.json` and runs a health check. Re-run it any time, it skips what is done.
   Options: `-CheckOnly` (report only), `-NoInstall` (configure only), `-SkipKonnect`, `-WithVSCode`,
   `-KonnectVersion 0.12.1`.
3. **Open a new terminal** (PATH changes need it) in the repo and start Claude Code:
   ```powershell
   claude
   ```
   or open the folder in VS Code and open the Claude Code panel.
   Type `/mcp` to check that `konnect` and `kschlint` are connected (the repo's `.claude/settings.json` enables them, approve them if asked).
4. Type **`/start-project`**. Claude asks about your board, renames the KiCad project
   and fills in the project section of CLAUDE.md.

## Manual install

Use this if you do not want the script, or a step failed.

1. Install KiCad 10, Git, Python 3.10+ and GitHub CLI from the links above. Tick "Add python.exe to PATH" in the Python installer.
2. Add `C:\Program Files\KiCad\10.0\bin` to your user PATH (Start → "Edit environment variables for your account" → Path → New). Check in a new terminal: `kicad-cli version`.
3. `git submodule update --init`
4. `python -m pip install --user pymupdf pymupdf4llm`
5. **Konnect**, in KiCad:
   1. Download `konnect-pcm-v<version>-windows.zip` from [Konnect releases](https://github.com/mixelpixx/Konnect/releases/latest). Take the `konnect-pcm-` file, not the standalone binary.
   2. KiCad project manager → **Plugin and Content Manager** → **Install from File...** → pick the zip.
   3. Restart KiCad. Check: PCB Editor → **Tools → External Plugins** shows Konnect.
   4. The server binary is now at `%USERPROFILE%\Documents\KiCad\10.0\3rdparty\plugins\com_github_mixelpixx_konnect\bin\konnect.exe` (your Documents folder, which may be under OneDrive).
6. Copy `.mcp.json.example` to `.mcp.json` and fix the three paths (python, kschlint folder, konnect.exe).
   Or run `python tools\setup_helpers.py mcp`, which fills them in.
7. Install Claude Code: `irm https://claude.ai/install.ps1 | iex` in PowerShell, or the VS Code extension.

Optional: `konnect init` installs Konnect's own Claude skills, agents and hooks into `~/.claude`. Not
needed for this template, and they apply to all your projects.

## Working with it

Talk to Claude like to a colleague who does the drawing. Good first prompts:

- `/start-project` then "a 12 V fan controller, 4 PWM channels, ESP32-C3, USB-C power"
- "Pick a 5 V 3 A buck converter from 12 V, in stock at JLCPCB. Write the trade-off."
- `/add-part TPS62933` "and put it on a new Power sheet"
- "Draw the power sheet from tradeoff/power.md"
- "Lint and render the Power sheet, show me what it looks like"
- "Why does ERC complain about U101 pin 4?"
- "Make the BOM for JLCPCB assembly, 5 boards"

What happens on every schematic change:

1. Claude checks KiCad is closed (`kicad/*.lck`) and makes a branch.
2. `python tools/sch_check.py snapshot before`
3. Edits a scratch copy of `kicad/`, using exact pin tips from kschlint so wires really connect.
4. `/verify-schematic`: net and ERC diff (only intended nets may change), BOM fields, lint, render,
   a separate review agent checks against the datasheets.
5. Copies the verified files into `kicad/`, commits, opens a PR, and asks you to look at the sheet in KiCad.

**Keep KiCad closed while Claude edits.** KiCad does not reload files and overwrites them on save.
Open KiCad to review, close it before the next request.

Records the AI keeps up to date, so decisions survive between sessions:

| File | Content |
|---|---|
| `datasheet/<Part>.md` + `.pdf` | condensed datasheet and how the part is used, margins |
| `tradeoff/<topic>.md` | requirements, candidates, decision |
| `docs/power_budget.md` | current per rail, each value DS / EST / TBD |
| `decisions.md` | choices made without you, waiting for your review |
| `TODO.md` | open questions and missing parts |

## Tools you can run yourself

```powershell
python tools\sch_check.py snapshot before          # netlist, ERC, BOM into .check\before
python tools\sch_check.py diff before after        # what changed
python tools\sch_check.py bom after                # parts missing Manufacturer / MPN / LCSC Part
tools\kschlint lint kicad                          # readability lint, all sheets
tools\kschlint render kicad --sheet Power --around U101,C101
tools\kschlint fix kicad --write                   # move colliding text, rollback on netlist change
tools\kschlint inspect kicad --sheet Power --refs U101
python tools\pdf2md.py datasheet\TPS62933.pdf      # raw markdown of a datasheet
python tools\pcb\drc_summary.py kicad\Project.kicad_pcb   # DRC errors per type, unconnected per net
& "C:\Program Files\KiCad\10.0\bin\python.exe" tools\pcb\snapshot.py kicad\Project.kicad_pcb snap.kicad_pcb   # board without GND fill, to render
powershell -ExecutionPolicy Bypass -File tools\rename_project.ps1 -Name MyBoard
```

Full kschlint reference: [tools/kicad-sch-lint/README.md](tools/kicad-sch-lint/README.md).

## Repo layout

| Path | Content |
|---|---|
| `kicad/` | KiCad project: `Project.kicad_pro`, `.kicad_sch`, `.kicad_pcb` (empty, rename with `/start-project`) |
| `kicad/lib/` | project library `Project` (symbols, footprints for parts missing from KiCad) |
| `datasheet/`, `tradeoff/`, `docs/` | records, with `_TEMPLATE.md` files |
| `tools/kicad-sch-lint/` | kschlint (git submodule) |
| `tools/sch_check.py` | netlist / ERC / BOM snapshot and diff |
| `tools/pdf2md.py` | datasheet PDF to markdown |
| `tools/pcb/` | routing helpers: `maze.py` (path inside a planned corridor), `drc_summary.py`, `snapshot.py`, `plan_overlay.py` |
| `docs/layout_rules.md`, `docs/routing_plan.md` | PCB checklist and routing plan templates |
| `tools/setup_helpers.py` | Konnect installer, `.mcp.json` writer (used by setup) |
| `tools/rename_project.ps1` | rename the KiCad project |
| `setup.cmd`, `setup.ps1` | one-shot setup |
| `CLAUDE.md` | rules for the AI |
| `.claude/skills/` | `/start-project`, `/add-part`, `/verify-schematic`, `/plan-routing` |
| `.claude/settings.json` | enables the MCP servers, lets kicad-cli, kschlint, the check scripts and read-only git run without prompts |
| `.mcp.json` | MCP servers with your machine's paths (generated, git-ignored) |

## Updating

- kschlint: `git submodule update --remote tools/kicad-sch-lint`, then commit the new pointer.
- Konnect: close KiCad, `.\setup.cmd` (installs the latest release), or pin with `-KonnectVersion`.
- KiCad minor updates: run `tools\kschlint selftest kicad` on a project with content to confirm the text geometry still matches.

## Troubleshooting

| Problem | Fix |
|---|---|
| `kicad-cli` not found | open a new terminal after setup, or add `C:\Program Files\KiCad\10.0\bin` to PATH |
| `python` opens the Microsoft Store | Settings → Apps → Advanced app settings → App execution aliases → turn off `python.exe`, then install Python |
| `/mcp` shows no servers | run `.\setup.cmd`, restart Claude Code in the repo folder, approve the servers |
| MCP server failed to start | run the command from `.mcp.json` by hand to see the error |
| setup says KiCad or Konnect is running | close every KiCad window and Claude Code (it keeps `konnect.exe` open), re-run |
| Claude's edit vanished | KiCad was open and saved over it. Close KiCad, ask Claude to redo it |
| `Filename too long` during clone | `git config --global core.longpaths true`, then `git submodule update --init` (setup does this for the submodule) |
| `setup.cmd` blocked | right-click → Properties → Unblock, or run `powershell -ExecutionPolicy Bypass -File setup.ps1` |

## License

MIT, see [LICENSE](LICENSE). kicad-sch-lint is MIT. Konnect is a separate project by
[mixelpixx](https://github.com/mixelpixx/Konnect) under AGPL-3.0. This template does not bundle it,
setup downloads it from the official releases.
