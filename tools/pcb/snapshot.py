"""Copy of a board with the GND fills removed, so a render shows the tracks (KiCad python).
usage: "C:/Program Files/KiCad/10.0/bin/python.exe" tools/pcb/snapshot.py <board.kicad_pcb> <out.kicad_pcb> [GND]
then:  tools/kschlint pcb-render <out.kicad_pcb> --region x0,y0,x1,y1 --layers "F.Cu,B.Cu,Edge.Cuts,F.Silkscreen" -o snap.png

Take snapshots only at key points: routing plan, after the escapes, after the buses, final.
"""
import sys

import pcbnew

b = pcbnew.LoadBoard(sys.argv[1])
gnd = sys.argv[3] if len(sys.argv) > 3 else "GND"
for z in b.Zones():
    if z.GetNetname() == gnd:
        z.UnFill()
pcbnew.SaveBoard(sys.argv[2], b)
print(sys.argv[2])
