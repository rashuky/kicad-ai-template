---
name: start-project
description: Turn a fresh copy of kicad-ai-template into a real project. Rename, fill in CLAUDE.md Project section, README, first trade-offs. Use once, at the start.
---

# Start a project from the template

1. Check the environment: `./setup.cmd -CheckOnly` (Bash) or `.\setup.cmd -CheckOnly` (PowerShell). Ask the user to run `setup.cmd` if programs are missing.
2. Ask the user for: project name, what the board does, input power and rails, main loads and sensors, MCU, sources of truth (firmware repo, requirements doc), fab and assembly house, layer count, size limits.
3. KiCad closed (no `kicad/*.lck`). Rename: `powershell -ExecutionPolicy Bypass -File tools/rename_project.ps1 -Name <Name>`.
4. Fill in the **Project** section of CLAUDE.md and adjust the design rules defaults if the user wants.
5. Rewrite the top of README.md for the project (keep the tools and setup sections).
6. Seed `TODO.md` with the open decisions and `docs/power_budget.md` with the rails and known loads.
7. For each big block (power, MCU, sensors, actuators) open a `tradeoff/<topic>.md` from `tradeoff/_TEMPLATE.md`.
8. Branch, commit, PR.
