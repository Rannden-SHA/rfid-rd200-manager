"""
generate_icon.py
Generates a professional RFID Reader Manager application icon.
Output: assets/icons/app_icon.ico (multi-size ICO file)

Usage:
    venv\Scripts\python.exe generate_icon.py
"""

import os
import math
from PIL import Image, ImageDraw


# ---------------------------------------------------------------------------
# Colour palette
# ---------------------------------------------------------------------------
BG_COLOR = (21, 101, 192)        # Deep blue  #1565C0
CHIP_COLOR = (255, 255, 255)     # White
WAVE_COLOR = (200, 230, 255)     # Light blue-white for wave arcs
TRANSPARENT = (0, 0, 0, 0)


def rounded_rectangle(draw, xy, radius, fill):
    """Draw a rounded-corner rectangle (compatible with older Pillow)."""
    x0, y0, x1, y1 = xy
    r = radius
    # Four corner circles
    draw.ellipse([x0, y0, x0 + 2 * r, y0 + 2 * r], fill=fill)
    draw.ellipse([x1 - 2 * r, y0, x1, y0 + 2 * r], fill=fill)
    draw.ellipse([x0, y1 - 2 * r, x0 + 2 * r, y1], fill=fill)
    draw.ellipse([x1 - 2 * r, y1 - 2 * r, x1, y1], fill=fill)
    # Two rectangles to fill the body
    draw.rectangle([x0 + r, y0, x1 - r, y1], fill=fill)
    draw.rectangle([x0, y0 + r, x1, y1 - r], fill=fill)


def draw_arc_band(draw, center, inner_r, outer_r, start_deg, end_deg, fill, steps=120):
    """Draw a thick arc (annular sector) as a filled polygon."""
    cx, cy = center
    points_outer = []
    points_inner = []
    for i in range(steps + 1):
        angle = math.radians(start_deg + (end_deg - start_deg) * i / steps)
        points_outer.append((cx + outer_r * math.cos(angle),
                             cy - outer_r * math.sin(angle)))
        points_inner.append((cx + inner_r * math.cos(angle),
                             cy - inner_r * math.sin(angle)))
    points_inner.reverse()
    draw.polygon(points_outer + points_inner, fill=fill)


def generate_icon_image(size):
    """Create a single icon image at the given pixel size."""
    img = Image.new("RGBA", (size, size), TRANSPARENT)
    draw = ImageDraw.Draw(img)

    margin = max(1, int(size * 0.06))
    corner_r = max(2, int(size * 0.18))

    # --- Background rounded square ---
    rounded_rectangle(draw, (margin, margin, size - margin, size - margin),
                      corner_r, fill=BG_COLOR)

    # --- RFID chip / card rectangle (lower-left area) ---
    chip_w = int(size * 0.36)
    chip_h = int(size * 0.26)
    chip_x = int(size * 0.16)
    chip_y = int(size * 0.48)
    chip_r = max(1, int(size * 0.04))

    rounded_rectangle(draw, (chip_x, chip_y, chip_x + chip_w, chip_y + chip_h),
                      chip_r, fill=CHIP_COLOR)

    # Small contact pad inside chip (the gold square on a smart card)
    pad_size = max(2, int(size * 0.12))
    pad_x = chip_x + int(chip_w * 0.18)
    pad_y = chip_y + int(chip_h * 0.22)
    pad_r = max(1, int(size * 0.02))
    pad_color = (180, 210, 255)  # Subtle light blue
    rounded_rectangle(draw, (pad_x, pad_y, pad_x + pad_size, pad_y + pad_size),
                      pad_r, fill=pad_color)

    # Tiny lines inside the contact pad (etched circuit look)
    if size >= 48:
        line_color = BG_COLOR
        lw = max(1, int(size * 0.008))
        mid_x = pad_x + pad_size // 2
        mid_y = pad_y + pad_size // 2
        draw.line([(mid_x, pad_y + 2), (mid_x, pad_y + pad_size - 2)],
                  fill=line_color, width=lw)
        draw.line([(pad_x + 2, mid_y), (pad_x + pad_size - 2, mid_y)],
                  fill=line_color, width=lw)

    # --- Signal / wave arcs (upper-right, radiating from chip corner) ---
    wave_origin_x = chip_x + chip_w
    wave_origin_y = chip_y
    wave_center = (wave_origin_x, wave_origin_y)

    arc_thickness = max(2, int(size * 0.045))
    gap = max(2, int(size * 0.06))

    for i in range(3):
        inner_r = int(size * 0.12) + i * (arc_thickness + gap)
        outer_r = inner_r + arc_thickness
        # Arcs sweep from roughly 20 to 70 degrees (upper-right quadrant)
        alpha = max(80, 255 - i * 55)
        arc_color = (WAVE_COLOR[0], WAVE_COLOR[1], WAVE_COLOR[2], alpha)
        draw_arc_band(draw, wave_center, inner_r, outer_r,
                      start_deg=20, end_deg=70, fill=arc_color)

    return img


def main():
    sizes = [16, 32, 48, 64, 128, 256]
    images = [generate_icon_image(s) for s in sizes]

    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "assets", "icons")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "app_icon.ico")

    # Use the largest image as the base; append all others
    images[0].save(
        out_path,
        format="ICO",
        sizes=[(s, s) for s in sizes],
        append_images=images[1:],
    )
    print(f"Icon saved to: {out_path}")
    print(f"Sizes included: {', '.join(f'{s}x{s}' for s in sizes)}")


if __name__ == "__main__":
    main()
