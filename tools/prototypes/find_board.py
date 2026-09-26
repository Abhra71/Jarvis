"""Find a chess board on screen with plain code (no AI): look for 9 evenly spaced grid lines in both
directions, then decide which side White is on. Saves an image with e2, e4, g1, f3 marked."""
import sys, time
sys.path.insert(0, r"C:\Syntax_Assembler\Jarvis")
import numpy as np
from PIL import Image, ImageDraw, ImageGrab
from jarvis.skills import desktop

OUT = str(__import__("pathlib").Path(__file__).resolve().parents[2] / "logs")
tab = next(t for t in desktop._browser_tabs() if "chess" in t[1].lower())
desktop._focus(tab[0])
time.sleep(0.8)
t0 = time.monotonic()
img = ImageGrab.grab()
a = np.asarray(img.convert("RGB")).astype(np.int16)


def lines(profile, lo, hi):
    """Best set of 9 evenly spaced peaks in an edge profile: (start, step)."""
    best, best_score = None, 0
    for step in range(40, 140):
        for start in range(lo, hi - 8 * step):
            idx = start + step * np.arange(9)
            s = profile[idx].sum()
            if s > best_score:
                best, best_score = (start, step), s
    return best


# colour change between neighbouring pixels, summed along each column / row
dx = np.abs(np.diff(a, axis=1)).sum(axis=2)          # H x (W-1)
dy = np.abs(np.diff(a, axis=0)).sum(axis=2)          # (H-1) x W
col = (dx > 60).sum(axis=0).astype(float)
row = (dy > 60).sum(axis=1).astype(float)
_, step = lines(col, 0, len(col))  # the square size is reliable from grid lines


def peaks(profile, n=40):
    idx = np.argsort(profile)[::-1]
    out = []
    for i in idx:
        if all(abs(i - j) > 5 for j in out):
            out.append(int(i))
        if len(out) >= n:
            break
    return out


def checker_score(x0, y0, s):
    """Sample a small patch near each square's corner (pieces rarely reach corners): a real board has two
    colours in a strict checker pattern."""
    if x0 < 0 or y0 < 0 or x0 + 8 * s >= a.shape[1] or y0 + 8 * s >= a.shape[0]:
        return -1e9
    m = max(2, s // 10)
    cols = np.array([[a[y0 + r * s + m: y0 + r * s + 2 * m, x0 + c * s + m: x0 + c * s + 2 * m].reshape(-1, 3).mean(0)
                      for c in range(8)] for r in range(8)])
    parity = (np.add.outer(np.arange(8), np.arange(8)) % 2).astype(bool)
    A, B = cols[parity], cols[~parity]
    return np.abs(A.mean(0) - B.mean(0)).sum() - 2 * (A.std(0).sum() + B.std(0).sum())


best = max(((checker_score(x, y, s), x, y, s) for s in (step - 1, step, step + 1)
            for x in peaks(col) for y in peaks(row)), key=lambda t: t[0])
_, x0, y0, sx = best

# Fine search: every offset within one square of the rough answer, scored all at once with numpy.
# Patch means come from a summed-area table, so each sample is 4 lookups.
m = max(2, sx // 10)
csum = np.pad(a.astype(np.float64).cumsum(0).cumsum(1), ((1, 0), (1, 0), (0, 0)))
def patch_mean(ys, xs):  # top-left corners (arrays) of m x m patches -> mean colour
    return (csum[ys + m, xs + m] - csum[ys, xs + m] - csum[ys + m, xs] + csum[ys, xs]) / (m * m)
dy_, dx_ = np.meshgrid(np.arange(-sx, sx + 1), np.arange(-sx, sx + 1), indexing="ij")
cy, cx = (y0 + dy_).ravel(), (x0 + dx_).ravel()
ok = (cy >= 0) & (cx >= 0) & (cy + 8 * sx + m < a.shape[0]) & (cx + 8 * sx + m < a.shape[1])
cy, cx = cy[ok], cx[ok]
samples = np.stack([patch_mean(cy + r * sx + m, cx + c * sx + m) for r in range(8) for c in range(8)], 1)  # N x 64 x 3
parity = np.array([(r + c) % 2 == 1 for r in range(8) for c in range(8)])
A, B = samples[:, parity], samples[:, ~parity]
score = np.abs(A.mean(1) - B.mean(1)).sum(1) - 2 * (A.std(1).sum(1) + B.std(1).sum(1))
k = int(score.argmax())
x0, y0 = int(cx[k]), int(cy[k])
sy = sx
elapsed = time.monotonic() - t0
size = (sx + sy) / 2
print(f"board at x={x0}, y={y0}, square {sx}x{sy}px, found in {elapsed:.2f}s")


def brightness_of_pieces(r):
    """Average brightness of the very light/dark (piece) pixels in board row r (0 = top)."""
    band = a[y0 + r * sy + sy // 4: y0 + r * sy + 3 * sy // 4, x0: x0 + 8 * sx].mean(axis=2)
    return (band > 235).sum(), (band < 40).sum()


top_light, top_dark = brightness_of_pieces(0)
bot_light, bot_dark = brightness_of_pieces(7)
white_bottom = bot_light - bot_dark > top_light - top_dark
print("White is at the", "bottom" if white_bottom else "top", f"(light/dark piece pixels top {top_light}/{top_dark}, bottom {bot_light}/{bot_dark})")


def centre(sq):
    f, r = "abcdefgh".index(sq[0]), int(sq[1])
    c = f if white_bottom else 7 - f
    rr = 8 - r if white_bottom else r - 1
    return x0 + c * sx + sx // 2, y0 + rr * sy + sy // 2


im = img.convert("RGB")
d = ImageDraw.Draw(im)
d.rectangle([x0, y0, x0 + 8 * sx, y0 + 8 * sy], outline=(255, 0, 0), width=4)
for sq in ("e2", "e4", "g1", "f3", "a8", "h1"):
    x, y = centre(sq)
    d.ellipse([x - 14, y - 14, x + 14, y + 14], outline=(0, 120, 255), width=5)
    d.text((x + 16, y - 10), sq, fill=(0, 120, 255))
im.resize((1100, 619)).save(fr"{OUT}\board_found.jpg", quality=80)

claude = next((w for w in desktop._app_windows() if "claude" in w[1]), None)
if claude:
    desktop._focus(claude[0])
