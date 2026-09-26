"""Synthetic test screens for tools/ai_eval.py's screen-clicking test.

Each screen is an HTML page with absolutely positioned elements, rendered by headless Chrome at 1920x1080,
so the exact area of every target is known. No real screen content is used (nothing private is sent to
the AI services being tested).
"""

import subprocess
import tempfile
from pathlib import Path

W, H = 1920, 1080
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

_CSS = """<style>body{margin:0;width:1920px;height:1080px;font-family:Arial;position:relative;overflow:hidden}
.a{position:absolute;box-sizing:border-box}</style>"""


def _box(x, y, w, h, style="", text=""):
    return f'<div class="a" style="left:{x}px;top:{y}px;width:{w}px;height:{h}px;{style}">{text}</div>'


def video_site(popup=False):
    """A YouTube-like page: header with search, an ad card first, a video grid, optionally a 'Premium' pop-up."""
    els, truth = [], {}
    els.append(_box(0, 0, W, 64, "background:#fff;border-bottom:1px solid #ddd"))
    els.append(_box(24, 16, 160, 32, "font:bold 26px Arial;color:#e00", "VideoTube"))
    els.append(_box(600, 12, 640, 40, "border:1px solid #ccc;border-radius:20px;padding:9px 16px;color:#888", "Search"))
    truth["search box"] = (600, 12, 640, 40)
    els.append(_box(1760, 14, 120, 36, "border:1px solid #06c;border-radius:18px;color:#06c;padding:8px 22px", "Sign in"))
    titles = ["Lofi beats to study to", "Aari Aari (Official Video)", "Physics: Laws of Motion in 1 shot",
              "Top 10 chess traps", "Daily news roundup", "How rockets work", "Cooking pasta 101", "Rain sounds 10 hours"]
    colours = ["#8a6", "#a68", "#68a", "#aa6", "#6aa", "#a66", "#6a6", "#888"]
    x0, y0, cw, ch, gap = 60, 110, 420, 236, 30
    cards = []
    for i in range(8):
        r, c = divmod(i, 4)
        x, y = x0 + c * (cw + gap), y0 + r * (ch + 110)
        cards.append((x, y))
        if i == 0:  # the first card is an ad, as on YouTube
            els.append(_box(x, y, cw, ch, "background:#ddd", '<div style="padding:90px 120px;font:22px Arial">Shop the sale</div>'))
            els.append(_box(x, y + ch + 8, cw, 60, "font:18px Arial", "<b>Sponsored</b> · MegaStore"))
            continue
        t = titles[i - 1]
        els.append(_box(x, y, cw, ch, f"background:{colours[i - 1]}"))
        els.append(_box(x, y + ch + 8, cw, 60, "font:bold 18px Arial", t))
        truth[f"video:{t}"] = (x, y, cw, ch + 68)
    if not popup:
        return els, truth
    truth = {}  # with the pop-up up, only its buttons count
    els.append(_box(0, 0, W, H, "background:rgba(0,0,0,.45)"))
    els.append(_box(700, 330, 520, 300, "background:#fff;border-radius:12px;padding:30px;font:22px Arial",
                    "<b>Try VideoTube Premium free</b><br><br>Ad-free videos and background play."))
    els.append(_box(760, 540, 180, 50, "border:1px solid #999;border-radius:25px;padding:14px 38px;font:18px Arial", "No thanks"))
    els.append(_box(980, 540, 180, 50, "background:#06c;color:#fff;border-radius:25px;padding:14px 26px;font:18px Arial", "Get Premium"))
    truth["No thanks"] = (760, 540, 180, 50)
    truth["Get Premium"] = (980, 540, 180, 50)
    return els, truth


_PIECES = {"K": "&#9812;", "Q": "&#9813;", "R": "&#9814;", "B": "&#9815;", "N": "&#9816;", "P": "&#9817;",
           "k": "&#9818;", "q": "&#9819;", "r": "&#9820;", "b": "&#9821;", "n": "&#9822;", "p": "&#9823;"}
_START = ["rnbqkbnr", "pppppppp", "", "", "", "", "PPPPPPPP", "RNBQKBNR"]  # rank 8 first


def square_rect(sq: str, left: int, top: int, size: int, white_bottom: bool):
    f, r = "abcdefgh".index(sq[0]), int(sq[1])
    col = f if white_bottom else 7 - f
    row = 8 - r if white_bottom else r - 1
    return (left + col * size, top + row * size, size, size)


def chess_board(white_bottom=True):
    """A chess.com-like board (green/cream) in the starting position, with a side panel."""
    left, top, size = 420, 60, 120
    els, truth = [], {}
    els.append(_box(0, 0, W, H, "background:#312e2b"))
    for rank in range(1, 9):
        for fi, f in enumerate("abcdefgh"):
            sq = f"{f}{rank}"
            x, y, s, _ = square_rect(sq, left, top, size, white_bottom)
            light = (fi + rank) % 2 == 0  # a1 is a dark square
            piece_row = _START[8 - rank]
            piece = piece_row[fi] if piece_row else ""
            glyph = _PIECES.get(piece, "")
            colour = "#fff;text-shadow:0 0 3px #000" if piece.isupper() else "#000"
            els.append(_box(x, y, s, s, f"background:{'#ebecd0' if light else '#779556'};font-size:96px;"
                                        f"line-height:{s}px;text-align:center;color:{colour}", glyph))
    # coordinates, like chess.com (file letters on the bottom row, rank numbers on the left column)
    for i in range(8):
        f = "abcdefgh"[i] if white_bottom else "abcdefgh"[7 - i]
        r = 8 - i if white_bottom else i + 1
        els.append(_box(left + i * size + size - 18, top + 8 * size - 22, 16, 20, "font:bold 16px Arial;color:#555", f))
        els.append(_box(left + 4, top + i * size + 2, 16, 20, "font:bold 16px Arial;color:#555", str(r)))
    els.append(_box(1440, 60, 420, 960, "background:#262421;color:#ddd;font:20px Arial;padding:24px",
                    "Play vs Bot · Martin (250)<br><br>You are playing " + ("White" if white_bottom else "Black")))
    els.append(_box(1480, 900, 340, 60, "background:#81b64c;color:#fff;font:bold 22px Arial;border-radius:8px;"
                                        "padding:16px 110px", "Resign"))
    truth["Resign"] = (1480, 900, 340, 60)
    for sq in ["e2", "g1", "f3", "d2", "d4", "e7", "b8", "c6", "d8"]:
        truth[f"square:{sq}"] = square_rect(sq, left, top, size, white_bottom)
    return els, truth


def render(els) -> bytes:
    """Render to a 1920x1080 PNG with headless Chrome."""
    with tempfile.TemporaryDirectory() as d:
        page, png = Path(d) / "page.html", Path(d) / "shot.png"
        page.write_text("<!doctype html><html><head><meta charset='utf-8'>" + _CSS + "</head><body>"
                        + "".join(els) + "</body></html>", encoding="utf-8")
        subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", f"--user-data-dir={d}\\p",
                        "--force-device-scale-factor=1", f"--window-size={W},{H}", f"--screenshot={png}",
                        page.as_uri()], check=True, capture_output=True, timeout=60)
        return png.read_bytes()


def to_jpeg(png: bytes, max_width: int = 1100) -> bytes:
    """Same scaling and quality as Jarvis's real screenshots (desktop.screenshot_jpeg)."""
    import io

    from PIL import Image
    img = Image.open(io.BytesIO(png)).convert("RGB")
    img = img.resize((max_width, round(img.height * max_width / img.width)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=70)
    return buf.getvalue()


# (screen, request, target(s) that must be hit: one for click, two for click_pair)
def cases():
    return [
        ("video_popup", "click No thanks", ["No thanks"]),
        ("video", "play the second video", ["video:Aari Aari (Official Video)"]),
        ("video", "open the physics video", ["video:Physics: Laws of Motion in 1 shot"]),
        ("video", "click the search box", ["search box"]),
        ("video", "play the cooking video", ["video:Cooking pasta 101"]),
        ("chess_white", "move the pawn from e2 to e4... first just click the pawn on e2", ["square:e2"]),
        ("chess_white", "click the knight on g1", ["square:g1"]),
        ("chess_white", "move knight g1 to f3", ["square:g1", "square:f3"]),
        ("chess_white", "move pawn d2 to d4", ["square:d2", "square:d4"]),
        ("chess_white", "click the black queen", ["square:d8"]),
        ("chess_black", "I'm black. Move my pawn e7 to e5... just click the pawn on e7", ["square:e7"]),
        ("chess_black", "move knight b8 to c6", ["square:b8", "square:c6"]),
    ]


def build_screens() -> dict:
    """{name: (jpeg bytes, truth dict)}"""
    out = {}
    for name, (els, truth) in {"video": video_site(), "video_popup": video_site(True), "chess_white": chess_board(True),
                               "chess_black": chess_board(False)}.items():
        out[name] = (to_jpeg(render(els)), truth)
    return out


def hit(truth_rect, x1000: float, y1000: float) -> bool:
    """Is the AI's point (0-1000 scale) inside the target rectangle (pixels at 1920x1080)?"""
    px, py = x1000 / 1000 * W, y1000 / 1000 * H
    x, y, w, h = truth_rect
    return x <= px <= x + w and y <= py <= y + h
