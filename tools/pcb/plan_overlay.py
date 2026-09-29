"""Draw planned routing corridors over a board render, for docs/img/routing_plan.png (Pillow).
usage: "C:/Program Files/KiCad/10.0/bin/python.exe" tools/pcb/plan_overlay.py <render.png> <spec.json> <out.png>
(KiCad's python ships Pillow. Any python with Pillow works too.)

The render must cover the region given in the spec. spec.json:
{
  "region": [x0, y0, x1, y1],                        mm, same as the pcb-render --region
  "items": [
    {"kind": "band", "box": [x0, y0, x1, y1], "layer": "F", "tag": "7"},
    {"kind": "line", "pts": [[x, y], [x, y]], "layer": "B", "width": 1.2, "tag": "4"},
    {"kind": "ring", "center": [x, y], "r": 3.5}       keep-out, e.g. a mounting hole
  ]
}
layer: F (orange), B (green, dashed), P (red, power), I (yellow, inner-layer island).
"""
import json
import math
import sys

from PIL import Image, ImageDraw, ImageFont

COL = {"F": (255, 140, 0), "B": (0, 230, 120), "P": (255, 60, 60), "I": (255, 230, 0)}


def main(render, spec, out):
    sp = json.load(open(spec, encoding="utf-8"))
    im = Image.open(render).convert("RGBA")
    x0, y0, x1, y1 = sp["region"]
    s = im.size[0] / (x1 - x0)

    def P(x, y):
        return (x - x0) * s, (y - y0) * s

    ov = Image.new("RGBA", im.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    try:
        font = ImageFont.truetype("arialbd.ttf", 22)
    except OSError:
        font = ImageFont.load_default()

    def tag(x, y, t):
        tx, ty = P(x, y)
        w = d.textlength(t, font=font)
        d.rectangle([tx - 4, ty - 4, tx + w + 4, ty + 26], fill=(0, 0, 0, 230))
        d.text((tx, ty), t, fill="white", font=font)

    for it in sp["items"]:
        c = COL.get(it.get("layer", "F"), COL["F"])
        if it["kind"] == "band":
            bx0, by0, bx1, by1 = it["box"]
            d.rectangle([P(bx0, by0), P(bx1, by1)], fill=c + (90,), outline=c + (255,), width=3)
            if it.get("tag"):
                tag((bx0 + bx1) / 2, (by0 + by1) / 2, it["tag"])
        elif it["kind"] == "line":
            w = int(it.get("width", 1.2) * s)
            dash = it.get("layer") == "B"
            for (ax, ay), (bx, by) in zip(it["pts"], it["pts"][1:]):
                a, b_ = P(ax, ay), P(bx, by)
                n = max(1, int(math.dist(a, b_) / 14)) if dash else 1
                for k in range(0, n, 2 if dash else 1):
                    t0, t1 = k / n, min(1, (k + 1) / n)
                    d.line([(a[0] + (b_[0] - a[0]) * t0, a[1] + (b_[1] - a[1]) * t0),
                            (a[0] + (b_[0] - a[0]) * t1, a[1] + (b_[1] - a[1]) * t1)], fill=c + (200,), width=w)
            if it.get("tag"):
                tag(*it["pts"][len(it["pts"]) // 2], it["tag"])
        elif it["kind"] == "ring":
            cx, cy = it["center"]
            r = it["r"]
            d.ellipse([P(cx - r, cy - r), P(cx + r, cy + r)], outline=(255, 255, 255, 255), width=3)
    Image.alpha_composite(im, ov).convert("RGB").quantize(128).save(out, optimize=True)
    print(out)


if __name__ == "__main__":
    main(*sys.argv[1:4])
