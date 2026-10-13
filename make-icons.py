"""Generates PNG icons. Run: python3 tools/make-icons.py  (needs Pillow)"""
from PIL import Image, ImageDraw, ImageFilter
import os
OUT = os.path.join(os.path.dirname(__file__), "..", "icons")
def glyph(size, scale, bg_round):
    S = size * 2  # supersample
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    bg = Image.new("RGBA", (S, S), (7, 11, 22, 255))
    # soft cyan / magenta glows
    glow = Image.new("RGBA", (S, S), (0, 0, 0, 0)); g = ImageDraw.Draw(glow)
    g.ellipse([S*-.1, S*-.2, S*.7, S*.6], fill=(0, 229, 255, 90)); g.ellipse([S*.4, S*.5, S*1.2, S*1.3], fill=(255, 43, 214, 70))
    glow = glow.filter(ImageFilter.GaussianBlur(S * .12)); bg = Image.alpha_composite(bg, glow)
    d = ImageDraw.Draw(bg)
    def P(x, y): return (S * (.5 + (x - .5) * scale), S * (.5 + (y - .5) * scale))
    top = [P(.5, .2), P(.78, .35), P(.5, .5), P(.22, .35)]
    d.polygon(top, fill=(0, 229, 255, 70))
    w = max(2, int(S * .045 * scale))
    hexa = [P(.5, .2), P(.78, .35), P(.78, .65), P(.5, .8), P(.22, .65), P(.22, .35), P(.5, .2)]
    lay = Image.new("RGBA", (S, S), (0, 0, 0, 0)); dl = ImageDraw.Draw(lay)
    for pts in (hexa, [P(.22, .35), P(.5, .5), P(.78, .35)], [P(.5, .5), P(.5, .8)]):
        dl.line(pts, fill=(0, 229, 255, 255), width=w, joint="curve")
        for p in pts: dl.ellipse([p[0]-w/2, p[1]-w/2, p[0]+w/2, p[1]+w/2], fill=(0, 229, 255, 255))
    halo = lay.filter(ImageFilter.GaussianBlur(S * .018)); bg = Image.alpha_composite(bg, halo); bg = Image.alpha_composite(bg, lay)
    if bg_round:
        m = Image.new("L", (S, S), 0); ImageDraw.Draw(m).rounded_rectangle([0, 0, S-1, S-1], radius=int(S*.22), fill=255)
        out = Image.new("RGBA", (S, S), (0, 0, 0, 0)); out.paste(bg, (0, 0), m); bg = out
    return bg.resize((size, size), Image.LANCZOS)
def save(name, size, scale, rnd): glyph(size, scale, rnd).save(os.path.join(OUT, name))
save("icon-192.png", 192, 1.0, True); save("icon-512.png", 512, 1.0, True)
save("maskable-512.png", 512, .72, False)       # full-bleed, glyph inside the safe zone
save("apple-touch-icon.png", 180, .9, False)    # iOS applies its own rounding
save("favicon-32.png", 32, 1.0, True)
open(os.path.join(OUT, "icon.svg"), "w").write('''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><rect width="100" height="100" rx="22" fill="#070b16"/><g fill="none" stroke="#00e5ff" stroke-width="4.5" stroke-linecap="round" stroke-linejoin="round"><path d="M50 20L78 35V65L50 80L22 65V35Z"/><path d="M22 35L50 50L78 35M50 50V80"/></g></svg>''')
print("icons written")
