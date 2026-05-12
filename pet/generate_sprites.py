"""Generate sprite frames from the AI-generated base character image.

Pipeline:
  1. Load assets/aigen-idle-v1.png (AI-generated chibi penguin girl on a
     near-white studio backdrop).
  2. Remove the near-white background via per-pixel alpha keying with a
     small feather, producing a clean transparent cutout.
  3. Tightly crop to the character bounding box, then place onto a square
     200x200 canvas with a small margin.
  4. For each of the 7 phases, render multiple frames composing the base
     character with phase-specific overlays (question mark, thinking dots,
     keyboard, sparkles, etc.) and tiny per-frame motion (breathing bob).

This keeps the character 100% consistent across phases — only environment
and small accessories change — which is the most failure-proof way to use
AI-generated art for sprite animation.
"""
import math
import os
import random
from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = os.path.dirname(__file__)
ASSETS_DIR = os.path.join(HERE, "..", "assets")
SPRITES_DIR = os.path.join(HERE, "sprites")

OUT_SIZE = 200

# Each phase has its own AI-generated base image (different pose / expression).
# Frame counts kept modest because the heavy lifting now happens in the base
# images themselves; per-frame variation only adds a small bob + optional
# environmental overlay (question mark, thinking dots, sparkles).
PHASES = {
    "idle":      {"frames": 6, "base": "aigen-idle-v1.png"},
    "question":  {"frames": 4, "base": "aigen-question-v1.png"},
    "reading":   {"frames": 6, "base": "aigen-reading-v1.png"},
    "thinking":  {"frames": 6, "base": "aigen-thinking-v1.png"},
    "writing":   {"frames": 4, "base": "aigen-writing-v1.png"},
    "executing": {"frames": 6, "base": "aigen-executing-v1.png"},
    "done":      {"frames": 4, "base": "aigen-done-v1.png"},
    # Used only locally when the user grabs the pet — never sent over IPC.
    "dragged":   {"frames": 4, "base": "aigen-dragged-v1.png"},
}

ACCENT_BLUE = (70, 150, 210, 255)
ACCENT_YEL  = (245, 184, 36, 255)
DARK        = (32, 38, 52, 255)


# ============================================================================
# Step 1 — background removal: turn the studio backdrop into alpha.
# IMPORTANT: only remove the *outside* white that's connected to the image
# border. White pixels trapped inside the character (the belly patch!) must
# stay opaque. This is done via a 4-corner edge flood fill on a binary
# brightness mask.
# ============================================================================
def alpha_key_white(img: Image.Image, white_threshold: int = 235,
                    feather: float = 1.2) -> Image.Image:
    img = img.convert("RGBA")
    w, h = img.size

    # 1. Binary brightness mask: 255 = near-white candidate, 0 = definitely subject.
    lum = img.convert("L")
    mask = lum.point(lambda v: 255 if v >= white_threshold else 0)

    # 2. Flood from each border seed: any near-white connected to the edge
    #    becomes the "outside" (marked with 128). Internal whites stay 255.
    seeds = []
    # Sample several points along all four edges for robustness.
    edge_step = max(1, min(w, h) // 16)
    for x in range(0, w, edge_step):
        seeds.append((x, 0))
        seeds.append((x, h - 1))
    for y in range(0, h, edge_step):
        seeds.append((0, y))
        seeds.append((w - 1, y))

    fill_marker = 128
    for sx, sy in seeds:
        if 0 <= sx < w and 0 <= sy < h and mask.getpixel((sx, sy)) == 255:
            ImageDraw.floodfill(mask, (sx, sy), fill_marker, thresh=0)

    # 3. Build alpha from the mask:
    #    128 = outside background -> alpha 0
    #    everything else (subject, including internal white belly) -> alpha 255
    alpha = mask.point(lambda v: 0 if v == fill_marker else 255)

    # 4. Soft feather to avoid jagged 1-pixel edges from the threshold.
    if feather > 0:
        alpha = alpha.filter(ImageFilter.GaussianBlur(feather))

    img.putalpha(alpha)
    return img


def trim_and_fit(img: Image.Image, out_size: int, margin: float = 0.06) -> Image.Image:
    """Crop tightly to non-transparent bbox, then fit into a square out_size."""
    bbox = img.getbbox()
    if bbox is None:
        return img.resize((out_size, out_size), Image.LANCZOS)
    cropped = img.crop(bbox)
    w, h = cropped.size
    target = int(out_size * (1.0 - margin * 2))
    scale = min(target / w, target / h)
    new_w = max(1, int(w * scale))
    new_h = max(1, int(h * scale))
    resized = cropped.resize((new_w, new_h), Image.LANCZOS)
    canvas = Image.new("RGBA", (out_size, out_size), (0, 0, 0, 0))
    canvas.paste(resized,
                 ((out_size - new_w) // 2, (out_size - new_h) // 2),
                 resized)
    return canvas


# ============================================================================
# Step 2 — fonts (for ? overlay)
# ============================================================================
def _font(size: int) -> ImageFont.FreeTypeFont:
    for name in ("seguiemj.ttf", "arialbd.ttf", "Arial Bold.ttf",
                 "DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except (OSError, IOError):
            continue
    return ImageFont.load_default()


# ============================================================================
# Step 3 — overlays per phase
# ============================================================================
def overlay_question(canvas: Image.Image, frame: int, total: int):
    draw = ImageDraw.Draw(canvas)
    w, h = canvas.size
    bob = int(math.sin(frame / total * 2 * math.pi) * h * 0.018)
    size = int(h * 0.20)
    font = _font(size)
    x, y = int(w * 0.78), int(h * 0.18) + bob
    # outline
    for ox, oy in [(-2, 0), (2, 0), (0, -2), (0, 2), (-2, -2), (2, 2)]:
        draw.text((x + ox, y + oy), "?", anchor="mm", font=font, fill=(20, 20, 30))
    draw.text((x, y), "?", anchor="mm", font=font, fill=ACCENT_YEL[:3])


def overlay_thinking(canvas: Image.Image, frame: int, total: int):
    draw = ImageDraw.Draw(canvas)
    w, h = canvas.size
    cx0 = int(w * 0.82)
    cy0 = int(h * 0.20)
    for i in range(3):
        angle = (frame / total * 2 * math.pi) + i * (2 * math.pi / 3)
        ox = cx0 + int(math.cos(angle) * h * 0.06)
        oy = cy0 + int(math.sin(angle) * h * 0.04)
        r = max(2, int(h * 0.020) - i)
        draw.ellipse((ox - r, oy - r, ox + r, oy + r), fill=(190, 195, 205, 255))
    # tiny thought-bubble lead
    for r, dy in ((4, 0), (3, 8)):
        draw.ellipse((int(w * 0.70) - r, int(h * 0.32) - r + dy,
                      int(w * 0.70) + r, int(h * 0.32) + r + dy),
                     fill=(220, 226, 234, 255))


def overlay_executing(canvas: Image.Image, frame: int, total: int):
    """A rotating blue spinner ring in the top-right corner — pairs nicely
    with the character's 'fired up fists + blue aura' base pose."""
    draw = ImageDraw.Draw(canvas)
    w, h = canvas.size
    sx = int(w * 0.86)
    sy = int(h * 0.18)
    sr = int(h * 0.06)
    start = (frame / total) * 360
    draw.arc((sx - sr, sy - sr, sx + sr, sy + sr),
             start=start, end=start + 270,
             fill=ACCENT_BLUE[:3], width=4)


def overlay_done(canvas: Image.Image, frame: int, total: int):
    draw = ImageDraw.Draw(canvas)
    w, h = canvas.size
    rng = random.Random(frame * 13 + 7)
    for _ in range(6):
        sx = rng.randint(int(w * 0.08), int(w * 0.92))
        sy = rng.randint(int(h * 0.04), int(h * 0.42))
        size = rng.randint(int(h * 0.025), int(h * 0.045))
        points = [
            (sx, sy - size),
            (sx + size // 3, sy - size // 3),
            (sx + size, sy),
            (sx + size // 3, sy + size // 3),
            (sx, sy + size),
            (sx - size // 3, sy + size // 3),
            (sx - size, sy),
            (sx - size // 3, sy - size // 3),
        ]
        draw.polygon(points, fill=(255, 215, 80, 255))


OVERLAYS = {
    "idle":      None,
    "question":  overlay_question,
    "reading":   None,                # pose already shows the book
    "thinking":  overlay_thinking,
    "writing":   None,                # pose already shows the laptop
    "executing": overlay_executing,
    "done":      overlay_done,
    "dragged":   None,                # pose + AI-rendered swoosh handles it
}


# ============================================================================
# Step 4 — assemble
# ============================================================================
def base_sprite(phase_name: str) -> Image.Image:
    cfg = PHASES[phase_name]
    path = os.path.join(ASSETS_DIR, cfg["base"])
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"AI base image not found for phase {phase_name!r} at {path}. "
            "Regenerate it via the GenerateImage tool first."
        )
    raw = Image.open(path).convert("RGBA")
    cut = alpha_key_white(raw)
    return trim_and_fit(cut, OUT_SIZE)


def render_frame(base: Image.Image, phase: str, frame: int, total: int) -> Image.Image:
    canvas = Image.new("RGBA", (OUT_SIZE, OUT_SIZE), (0, 0, 0, 0))
    # Gentle breathing bob across all phases.
    bob = int(math.sin(frame / max(1, total) * 2 * math.pi) * 3)
    canvas.paste(base, (0, bob), base)

    overlay = OVERLAYS.get(phase)
    if overlay is not None:
        overlay(canvas, frame, total)
    return canvas


def generate_sprites():
    for phase, cfg in PHASES.items():
        phase_dir = os.path.join(SPRITES_DIR, phase)
        os.makedirs(phase_dir, exist_ok=True)
        base = base_sprite(phase)
        total = cfg["frames"]
        for i in range(total):
            img = render_frame(base, phase, i, total)
            filepath = os.path.join(phase_dir, f"frame_{i+1:02d}.png")
            img.save(filepath)
            print(f"  {filepath}")


if __name__ == "__main__":
    print("Generating sprites from AI base...")
    generate_sprites()
    print("Done.")
