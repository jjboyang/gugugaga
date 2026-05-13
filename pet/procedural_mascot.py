"""Vector-style chibi penguin mascot drawn with Pillow (no external PNG assets).

Used by generate_sprites.py when assets/aigen-*.png files are missing so the
repo always ships drawable sleep / angry / hook phases.
"""
from __future__ import annotations

import math
from PIL import Image, ImageDraw


def render_phase_base(phase: str, size: int = 200) -> Image.Image:
    """One static pose per phase; per-frame motion comes from generate_sprites."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    s = size / 200.0
    cx = size * 0.5
    cy = size * 0.56

    if phase == "sleep":
        _draw_sleep_pose(draw, s, cx, cy + 8 * s)
    elif phase == "angry":
        _draw_angry_pose(draw, s, cx, cy)
    elif phase == "question":
        _draw_standard_body(draw, s, cx, cy, tilt=-8, flipper_l=25, flipper_r=-5)
        _draw_face(draw, s, cx, cy - 38 * s, eye="wide", blush=True)
        _draw_beak(draw, s, cx, cy - 22 * s, open_slight=True)
    elif phase == "reading":
        _draw_standard_body(draw, s, cx, cy, tilt=4, flipper_l=55, flipper_r=-40)
        _draw_face(draw, s, cx, cy - 38 * s, eye="down", blush=False)
        _draw_beak(draw, s, cx, cy - 22 * s, open_slight=False)
        _draw_book(draw, s, cx + 2 * s, cy - 8 * s)
    elif phase == "thinking":
        _draw_speed_lines_back(draw, s, cx, cy)
        _draw_standard_body(draw, s, cx, cy, tilt=0, flipper_l=78, flipper_r=-35)
        _draw_face(draw, s, cx, cy - 38 * s, eye="side", blush=True)
        _draw_beak(draw, s, cx, cy - 22 * s, open_slight=False)
        ex, ey, ew, eh = _flipper_rect(cx - 48 * s, cy - 18 * s, 38 * s, 16 * s, 35)
        draw.ellipse((ex, ey, ex + ew, ey + eh), fill=(45, 82, 130, 255))
    elif phase == "writing":
        _draw_standard_body(draw, s, cx, cy, tilt=6, flipper_l=20, flipper_r=-60)
        _draw_face(draw, s, cx, cy - 38 * s, eye="down", blush=False)
        _draw_beak(draw, s, cx, cy - 22 * s, open_slight=False)
        _draw_laptop(draw, s, cx, cy + 18 * s)
    elif phase == "executing":
        for i in range(5):
            ang = -130 + i * 26
            _speed_line(draw, s, cx, cy, ang)
        _draw_standard_body(draw, s, cx, cy, tilt=-4, flipper_l=-70, flipper_r=70)
        _draw_face(draw, s, cx, cy - 38 * s, eye="determined", blush=True)
        _draw_beak(draw, s, cx, cy - 22 * s, open_slight=True)
    elif phase == "done":
        _draw_standard_body(draw, s, cx, cy, tilt=0, flipper_l=-85, flipper_r=-85)
        _draw_face(draw, s, cx, cy - 38 * s, eye="happy", blush=True)
        _draw_beak(draw, s, cx, cy - 22 * s, open_slight=True)
    elif phase == "dragged":
        _draw_squash_body(draw, s, cx, cy)
        _draw_face(draw, s, cx, cy - 34 * s, eye="panic", blush=True)
        _draw_beak(draw, s, cx, cy - 18 * s, open_slight=True)
        draw.ellipse(
            (cx + 28 * s, cy - 62 * s, cx + 40 * s, cy - 50 * s),
            fill=(180, 210, 255, 200),
        )
    elif phase == "waddle":
        _draw_standard_body(draw, s, cx, cy, tilt=6, flipper_l=55, flipper_r=-55)
        _draw_face(draw, s, cx, cy - 38 * s, eye="determined", blush=True)
        _draw_beak(draw, s, cx, cy - 22 * s, open_slight=False)
    else:  # idle + fallback
        _draw_standard_body(draw, s, cx, cy, tilt=0, flipper_l=15, flipper_r=-15)
        _draw_face(draw, s, cx, cy - 38 * s, eye="normal", blush=True)
        _draw_beak(draw, s, cx, cy - 22 * s, open_slight=False)

    return img


def _flipper_rect(cx: float, cy: float, rw: float, rh: float, deg: float) -> tuple:
    rad = math.radians(deg)
    cos_r, sin_r = math.cos(rad), math.sin(rad)
    pts = []
    for sx, sy in ((-rw, -rh), (rw, -rh), (rw, rh), (-rw, rh)):
        x = cx + sx * cos_r - sy * sin_r
        y = cy + sx * sin_r + sy * cos_r
        pts.append((x, y))
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)


def _draw_standard_body(
    draw: ImageDraw.ImageDraw,
    s: float,
    cx: float,
    cy: float,
    tilt: float,
    flipper_l: float,
    flipper_r: float,
) -> None:
    # feet
    for ox in (-18, 18):
        draw.ellipse(
            (cx + ox * s - 14 * s, cy + 38 * s, cx + ox * s + 14 * s, cy + 52 * s),
            fill=(245, 158, 66, 255),
            outline=(200, 120, 40, 255),
            width=2,
        )
    # belly (white)
    draw.ellipse(
        (cx - 32 * s, cy - 12 * s, cx + 32 * s, cy + 42 * s),
        fill=(248, 252, 255, 255),
        outline=(210, 220, 232, 255),
        width=2,
    )
    # body (blue)
    body = (
        cx - 46 * s,
        cy - 48 * s,
        cx + 46 * s,
        cy + 44 * s,
    )
    draw.ellipse(body, fill=(61, 110, 168, 255), outline=(35, 70, 120, 255), width=3)
    # flippers
    ex1, ey1, ew1, eh1 = _flipper_rect(cx - 52 * s, cy - 5 * s, 22 * s, 40 * s, flipper_l)
    draw.ellipse((ex1, ey1, ex1 + ew1, ey1 + eh1), fill=(45, 82, 130, 255))
    ex2, ey2, ew2, eh2 = _flipper_rect(cx + 52 * s, cy - 5 * s, 22 * s, 40 * s, flipper_r)
    draw.ellipse((ex2, ey2, ex2 + ew2, ey2 + eh2), fill=(45, 82, 130, 255))


def _draw_squash_body(draw: ImageDraw.ImageDraw, s: float, cx: float, cy: float) -> None:
    draw.ellipse(
        (cx - 58 * s, cy - 28 * s, cx + 58 * s, cy + 36 * s),
        fill=(61, 110, 168, 255),
        outline=(35, 70, 120, 255),
        width=3,
    )
    draw.ellipse(
        (cx - 36 * s, cy - 8 * s, cx + 36 * s, cy + 32 * s),
        fill=(248, 252, 255, 255),
    )


def _draw_face(
    draw: ImageDraw.ImageDraw,
    s: float,
    cx: float,
    cy: float,
    eye: str,
    blush: bool,
) -> None:
    # white face patch
    draw.ellipse(
        (cx - 40 * s, cy - 8 * s, cx + 40 * s, cy + 36 * s),
        fill=(252, 254, 255, 255),
        outline=(200, 210, 225, 200),
        width=2,
    )
    ey = cy + 8 * s
    if eye == "happy":
        for ox in (-16, 16):
            draw.arc(
                (cx + ox * s - 10 * s, ey - 10 * s, cx + ox * s + 10 * s, ey + 6 * s),
                200,
                340,
                fill=(40, 45, 55, 255),
                width=4,
            )
    elif eye == "wide":
        for ox in (-16, 16):
            draw.ellipse(
                (cx + ox * s - 9 * s, ey - 10 * s, cx + ox * s + 9 * s, ey + 8 * s),
                fill=(255, 255, 255, 255),
                outline=(40, 45, 55, 255),
                width=2,
            )
            draw.ellipse(
                (cx + ox * s - 4 * s, ey - 2 * s, cx + ox * s + 4 * s, ey + 6 * s),
                fill=(30, 35, 45, 255),
            )
    elif eye == "down":
        for ox in (-16, 16):
            draw.ellipse(
                (cx + ox * s - 8 * s, ey - 4 * s, cx + ox * s + 8 * s, ey + 10 * s),
                fill=(255, 255, 255, 255),
                outline=(40, 45, 55, 255),
                width=2,
            )
            draw.ellipse(
                (cx + ox * s - 3 * s, ey + 2 * s, cx + ox * s + 5 * s, ey + 8 * s),
                fill=(30, 35, 45, 255),
            )
    elif eye == "side":
        for ox in (-16, 16):
            draw.ellipse(
                (cx + ox * s - 8 * s, ey - 8 * s, cx + ox * s + 8 * s, ey + 8 * s),
                fill=(255, 255, 255, 255),
                outline=(40, 45, 55, 255),
                width=2,
            )
            px = cx + ox * s + (4 if ox < 0 else -4) * s
            draw.ellipse(
                (px - 3 * s, ey - 2 * s, px + 3 * s, ey + 6 * s),
                fill=(30, 35, 45, 255),
            )
    elif eye == "determined":
        for ox in (-16, 16):
            draw.line(
                (cx + ox * s - 10 * s, ey, cx + ox * s + 10 * s, ey + 2 * s),
                fill=(30, 35, 45, 255),
                width=4,
            )
    elif eye == "angry":
        draw.line(
            (cx - 24 * s, ey - 6 * s, cx - 10 * s, ey + 6 * s),
            fill=(55, 30, 35, 255),
            width=4,
        )
        draw.line(
            (cx + 24 * s, ey - 6 * s, cx + 10 * s, ey + 6 * s),
            fill=(55, 30, 35, 255),
            width=4,
        )
        draw.line(
            (cx - 22 * s, ey - 22 * s, cx - 6 * s, ey - 26 * s),
            fill=(55, 30, 35, 255),
            width=4,
        )
        draw.line(
            (cx + 22 * s, ey - 22 * s, cx + 6 * s, ey - 26 * s),
            fill=(55, 30, 35, 255),
            width=4,
        )
    elif eye == "panic":
        for ox in (-14, 14):
            draw.ellipse(
                (cx + ox * s - 8 * s, ey - 10 * s, cx + ox * s + 8 * s, ey + 8 * s),
                fill=(255, 255, 255, 255),
                outline=(40, 45, 55, 255),
                width=2,
            )
            draw.ellipse(
                (cx + ox * s - 2 * s, ey - 2 * s, cx + ox * s + 2 * s, ey + 6 * s),
                fill=(30, 35, 45, 255),
            )
    else:  # normal
        for ox in (-16, 16):
            draw.ellipse(
                (cx + ox * s - 8 * s, ey - 8 * s, cx + ox * s + 8 * s, ey + 8 * s),
                fill=(255, 255, 255, 255),
                outline=(40, 45, 55, 255),
                width=2,
            )
            draw.ellipse(
                (cx + ox * s - 3 * s, ey - 2 * s, cx + ox * s + 3 * s, ey + 5 * s),
                fill=(30, 35, 45, 255),
            )

    if blush:
        for ox in (-26, 26):
            draw.ellipse(
                (cx + ox * s - 8 * s, ey + 12 * s, cx + ox * s + 8 * s, ey + 22 * s),
                fill=(255, 170, 190, 90),
            )


def _draw_beak(
    draw: ImageDraw.ImageDraw,
    s: float,
    cx: float,
    cy: float,
    open_slight: bool,
) -> None:
    if open_slight:
        draw.polygon(
            [
                (cx - 10 * s, cy),
                (cx + 10 * s, cy),
                (cx, cy + 14 * s),
            ],
            fill=(245, 158, 66, 255),
            outline=(200, 120, 40, 255),
        )
    else:
        draw.polygon(
            [
                (cx - 12 * s, cy - 2 * s),
                (cx + 12 * s, cy - 2 * s),
                (cx, cy + 12 * s),
            ],
            fill=(245, 158, 66, 255),
            outline=(200, 120, 40, 255),
        )


def _draw_book(draw: ImageDraw.ImageDraw, s: float, cx: float, cy: float) -> None:
    w, h = 36 * s, 28 * s
    draw.rounded_rectangle(
        (cx - w, cy - h, cx, cy + 4 * s),
        radius=4,
        fill=(120, 82, 58, 255),
        outline=(60, 40, 28, 255),
        width=2,
    )
    draw.rounded_rectangle(
        (cx - w + 3 * s, cy - h + 4 * s, cx - 2 * s, cy + 1 * s),
        radius=2,
        fill=(245, 240, 230, 255),
    )


def _draw_laptop(draw: ImageDraw.ImageDraw, s: float, cx: float, cy: float) -> None:
    draw.rounded_rectangle(
        (cx - 42 * s, cy - 8 * s, cx + 42 * s, cy + 22 * s),
        radius=6,
        fill=(75, 85, 98, 255),
        outline=(40, 45, 55, 255),
        width=2,
    )
    draw.rounded_rectangle(
        (cx - 36 * s, cy - 4 * s, cx + 36 * s, cy + 12 * s),
        radius=4,
        fill=(40, 48, 58, 255),
    )


def _draw_speed_lines_back(draw: ImageDraw.ImageDraw, s: float, cx: float, cy: float) -> None:
    for i in range(3):
        _speed_line(draw, s, cx, cy, -155 + i * 18)


def _speed_line(draw: ImageDraw.ImageDraw, s: float, cx: float, cy: float, deg: float) -> None:
    rad = math.radians(deg)
    r0, r1 = 55 * s, 78 * s
    x0 = cx + r0 * math.cos(rad)
    y0 = cy + r0 * math.sin(rad)
    x1 = cx + r1 * math.cos(rad)
    y1 = cy + r1 * math.sin(rad)
    draw.line((x0, y0, x1, y1), fill=(120, 180, 255, 200), width=3)


def _draw_sleep_pose(draw: ImageDraw.ImageDraw, s: float, cx: float, cy: float) -> None:
    # pillow
    draw.rounded_rectangle(
        (cx - 62 * s, cy + 8 * s, cx + 18 * s, cy + 32 * s),
        radius=10,
        fill=(200, 215, 235, 255),
        outline=(150, 170, 200, 255),
        width=2,
    )
    # body lying (horizontal oval)
    draw.ellipse(
        (cx - 35 * s, cy - 18 * s, cx + 55 * s, cy + 28 * s),
        fill=(61, 110, 168, 255),
        outline=(35, 70, 120, 255),
        width=3,
    )
    draw.ellipse(
        (cx - 15 * s, cy - 8 * s, cx + 38 * s, cy + 18 * s),
        fill=(248, 252, 255, 255),
    )
    # head on pillow side
    hx, hy = cx - 48 * s, cy - 22 * s
    draw.ellipse(
        (hx - 28 * s, hy - 26 * s, hx + 28 * s, hy + 22 * s),
        fill=(61, 110, 168, 255),
        outline=(35, 70, 120, 255),
        width=2,
    )
    draw.ellipse(
        (hx - 20 * s, hy - 12 * s, hx + 20 * s, hy + 14 * s),
        fill=(252, 254, 255, 255),
    )
    # closed eyes ~~
    ey = hy + 2 * s
    for ox in (-10, 10):
        draw.arc(
            (hx + ox * s - 8 * s, ey - 4 * s, hx + ox * s + 8 * s, ey + 8 * s),
            0,
            180,
            fill=(45, 50, 62, 255),
            width=3,
        )
    # tiny beak
    draw.polygon(
        [
            (hx - 6 * s, hy + 14 * s),
            (hx + 6 * s, hy + 14 * s),
            (hx, hy + 22 * s),
        ],
        fill=(245, 158, 66, 255),
    )
    for i, (dx, dy) in enumerate(((38, -32), (48, -26), (56, -20))):
        r = (3 - i) * s
        draw.ellipse(
            (cx + dx * s - r, hy + dy * s - r, cx + dx * s + r, hy + dy * s + r),
            fill=(170, 185, 205, 200),
        )


def _draw_angry_pose(draw: ImageDraw.ImageDraw, s: float, cx: float, cy: float) -> None:
    _draw_standard_body(draw, s, cx, cy, tilt=0, flipper_l=38, flipper_r=-38)
    draw.ellipse(
        (cx - 44 * s, cy - 88 * s, cx + 44 * s, cy - 28 * s),
        fill=(255, 110, 110, 70),
    )
    _draw_face(draw, s, cx, cy - 38 * s, eye="angry", blush=True)
    _draw_beak(draw, s, cx, cy - 22 * s, open_slight=True)
    for i, ox in enumerate((-58, 60)):
        px = cx + ox * s
        py = cy - 95 * s + i * 5 * s
        draw.ellipse(
            (px - 11 * s, py - 16 * s, px + 11 * s, py + 4 * s),
            fill=(245, 245, 255, 140),
        )
