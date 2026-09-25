@echo off
rem kschlint from the submodule, no install needed. Usage: tools\kschlint lint kicad
set "PYTHONPATH=%~dp0kicad-sch-lint;%PYTHONPATH%"
python -m kschlint %*
