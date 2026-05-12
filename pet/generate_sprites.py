"""Generate sprite frames for the desktop pet.

Pipeline A — AI bases (optional):
  When assets/aigen-*.png exist, load + alpha-key + trim, then add motion/overlays.

Pipeline B — procedural mascot (default when AI files are missing):
  pet/procedural_mascot.py draws a consistent chibi penguin; motion/overlays match pipeline A.

Run from repo root:  python pet/generate_sprites.py
Requires: Pillow
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
    "idle":      {"frames": 12, "base": "aigen-idle-v1.png"},
    "question":  {"frames": 8, "base": "aigen-question-v1.png"},
    "reading":   {"frames": 12, "base": "aigen-reading-v1.png"},
    "thinking":  {"frames": 12, "base": "aigen-thinking-v1.png"},
    "writing":   {"frames": 10, "base": "aigen-writing-v1.png"},
    "executing": {"frames": 10, "base": "aigen-executing-v1.png"},
    "done":      {"frames": 8, "base": "aigen-done-v1.png"},
    "dragged":   {"frames": 6, "base": "aigen-dragged-v1.png"},
    "sleep":     {"frames": 10, "base": "aigen-idle-v1.png"},
    "angry":     {"frames": 8, "base": "aigen-idle-v1.png"},
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


def overlay_sleep(canvas: Image.Image, frame: int, total: int):
    """Floating Zs (closed eyes are drawn on the procedural / AI base)."""
    draw = ImageDraw.Draw(canvas)
    w, h = canvas.size
    bob = int(math.sin(frame / max(1, total) * 2 * math.pi) * 7)
    font = _font(max(12, int(h * 0.11)))
    zz = "Z" * (1 + (frame % 3))
    draw.text(
        (int(w * 0.76), int(h * 0.12) + bob), zz, anchor="mm", font=font,
        fill=(140, 150, 168, 255),
    )


def overlay_angry(canvas: Image.Image, frame: int, total: int):
    """Popping vein + cheek flush (face is on the base sprite)."""
    draw = ImageDraw.Draw(canvas)
    w, h = canvas.size
    shake = int(5 * math.sin(frame * 2.9))
    cx = int(w * 0.74) + shake
    cy = int(h * 0.26)
    draw.line((cx - 11, cy - 11, cx + 11, cy + 11), fill=(215, 60, 55), width=4)
    draw.line((cx - 11, cy + 11, cx + 11, cy - 11), fill=(215, 60, 55), width=4)
    r = max(3, int(h * 0.035))
    for sx in (int(w * 0.30), int(w * 0.70)):
        draw.ellipse(
            (sx - r, int(h * 0.48) - r, sx + r, int(h * 0.48) + r),
            fill=(255, 120, 120, 110),
        )


OVERLAYS = {
    "idle":      None,
    "question":  overlay_question,
    "reading":   None,                # pose already shows the book
    "thinking":  overlay_thinking,
    "writing":   None,                # pose already shows the laptop
    "executing": overlay_executing,
    "done":      overlay_done,
    "dragged":   None,                # pose + AI-rendered swoosh handles it
    "sleep":     overlay_sleep,
    "angry":     overlay_angry,
}


# ============================================================================
# Step 4 — per-frame body motion (translate + rotate) then assemble
# ============================================================================
def _motion_triplet(phase: str, frame: int, total: int) -> tuple[float, float, float]:
    """Return (dx, dy, rotate_deg) for Pillow rotate(..., translate=(dx,dy))."""
    u = frame / max(1, total)
    t = u * 2 * math.pi

    if phase == "idle":
        # Subtle idle — window drag already adds rotation; keep base almost still.
        return (
            math.sin(t * 0.85) * 3.0,
            math.sin(t) * 4.0,
            math.sin(t * 0.65 + 0.25) * 4.5,
        )
    if phase == "sleep":
        ts = t * 0.38
        return (
            math.sin(ts) * 5.0,
            math.sin(ts * 1.3) * 6.0,
            -10.0 + math.sin(ts * 0.9) * 4.0,
        )
    if phase == "angry":
        return (
            math.sin(t * 4.2) * 12.0 + math.sin(t * 6.1) * 4.0,
            math.sin(t * 3.0) * 5.0,
            math.sin(t * 3.8) * 14.0,
        )
    if phase == "question":
        return (
            math.sin(t * 1.4) * 6.0,
            math.sin(t * 2.0) * 9.0,
            math.sin(t * 2.1) * 16.0,
        )
    if phase == "reading":
        return (
            math.sin(t * 1.25) * 16.0,
            abs(math.sin(t * 1.25)) * 10.0,
            math.sin(t * 0.9) * 13.0,
        )
    if phase == "thinking":
        return (
            math.sin(t * 0.75) * 11.0,
            math.sin(t * 1.1) * 10.0,
            math.sin(t) * 17.0 + math.sin(2 * t) * 8.0,
        )
    if phase == "writing":
        return (
            math.sin(t * 1.5) * 7.0,
            math.sin(t * 2.7) * 9.0,
            math.sin(t * 1.9) * 10.0,
        )
    if phase == "executing":
        return (
            math.sin(t * 1.7) * 12.0,
            math.sin(t * 1.4) * 8.0,
            math.sin(t * 1.55) * 14.0,
        )
    if phase == "done":
        return (
            math.sin(t * 1.2) * 9.0,
            math.sin(t) * 11.0,
            math.sin(t * 0.8) * 13.0,
        )
    if phase == "dragged":
        # Light loop while grabbed; main motion comes from PetWindow sway.
        return (
            math.sin(t * 1.1) * 2.5,
            math.sin(t * 1.6) * 3.0,
            math.sin(t * 1.5) * 5.0,
        )
    # fallback
    return (math.sin(t) * 6.0, math.sin(t) * 7.0, math.sin(t) * 8.0)


def apply_body_motion(base: Image.Image, phase: str, frame: int, total: int) -> Image.Image:
    dx, dy, rot = _motion_triplet(phase, frame, total)
    ix = int(round(dx))
    iy = int(round(dy))
    return base.rotate(
        rot,
        resample=Image.BICUBIC,
        expand=False,
        translate=(ix, iy),
        fillcolor=(0, 0, 0, 0),
    )


# ============================================================================
# Step 5 — assemble
# ============================================================================
def base_sprite(phase_name: str) -> Image.Image:
    cfg = PHASES[phase_name]
    base_file = cfg.get("base")
    path = os.path.join(ASSETS_DIR, base_file) if base_file else ""
    if base_file and os.path.isfile(path):
        raw = Image.open(path).convert("RGBA")
        cut = alpha_key_white(raw)
        return trim_and_fit(cut, OUT_SIZE)
    from procedural_mascot import render_phase_base
    return render_phase_base(phase_name, OUT_SIZE)


def render_frame(base: Image.Image, phase: str, frame: int, total: int) -> Image.Image:
    body = apply_body_motion(base, phase, frame, total)
    canvas = Image.new("RGBA", (OUT_SIZE, OUT_SIZE), (0, 0, 0, 0))
    canvas.paste(body, (0, 0), body)

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
    print("Generating sprites (AI assets if present, else procedural mascot)...")
    generate_sprites()
    print("Done.")
