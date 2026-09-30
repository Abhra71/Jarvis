"""Windows' own text reading (OCR) and media status: offline, free, no AI.

OCR is the agent's backup eyes for windows that don't name their buttons (games, some web and Electron
apps, pictures of text). It returns each line's position too, so Jarvis can click text it reads.
Media status is what Windows' media keys see: whether any app (Chrome, Spotify…) is playing or paused.
That's how "resume the video" is checked, even in full screen, where a player hides its buttons.

Python can't reach these Windows features without extra compiled packages (which Smart App Control may
block), so a small PowerShell helper does it. It starts on first use, stays running while it's being used
(~0.1-0.3 s a read instead of ~2 s to start PowerShell) and exits after IDLE_SECONDS, like the GPU hearing:
nothing runs while Jarvis just waits.
"""

import logging
import os
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass, field

from rapidfuzz import fuzz

log = logging.getLogger(__name__)

IDLE_SECONDS = 120
READ_TIMEOUT = 6.0

# stdin: an image path (answer: "L|W <tab> x,y,w,h <tab> text" per line/word) or "::media" (answer:
# "app <tab> status" per media session). Each answer ends with "<<END>>".
_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8  # "™" etc. (30 Sep: a byte 0x99 broke a read)
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics, ContentType = WindowsRuntime]
$null = [Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager, Windows.Media.Control, ContentType = WindowsRuntime]
$asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
    $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Await($op, [Type]$type) {
    $t = $asTask.MakeGenericMethod($type).Invoke($null, @($op)); $t.Wait(-1) | Out-Null; $t.Result }
function Box($r) { '{0:0},{1:0},{2:0},{3:0}' -f $r.X, $r.Y, $r.Width, $r.Height }
$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
$media = $null
[Console]::Out.WriteLine('<<READY>>'); [Console]::Out.Flush()
while ($true) {
    $cmd = [Console]::In.ReadLine()
    if ($cmd -eq $null -or $cmd -eq '') { break }
    try {
        if ($cmd -eq '::media') {
            if ($media -eq $null) {
                $media = Await ([Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager]::RequestAsync()) ([Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager])
            }
            foreach ($s in $media.GetSessions()) {
                [Console]::Out.WriteLine($s.SourceAppUserModelId + "`t" + $s.GetPlaybackInfo().PlaybackStatus) }
        } else {
            $file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($cmd)) ([Windows.Storage.StorageFile])
            $stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
            $decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
            $bitmap = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
            $result = Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
            foreach ($line in $result.Lines) {
                $w = $line.Words
                $x1 = ($w | ForEach-Object { $_.BoundingRect.X } | Measure-Object -Minimum).Minimum
                $y1 = ($w | ForEach-Object { $_.BoundingRect.Y } | Measure-Object -Minimum).Minimum
                $x2 = ($w | ForEach-Object { $_.BoundingRect.X + $_.BoundingRect.Width } | Measure-Object -Maximum).Maximum
                $y2 = ($w | ForEach-Object { $_.BoundingRect.Y + $_.BoundingRect.Height } | Measure-Object -Maximum).Maximum
                [Console]::Out.WriteLine(('L' + "`t" + ('{0:0},{1:0},{2:0},{3:0}' -f $x1, $y1, ($x2 - $x1), ($y2 - $y1)) + "`t" + $line.Text))
                foreach ($word in $w) { [Console]::Out.WriteLine('W' + "`t" + (Box $word.BoundingRect) + "`t" + $word.Text) }
            }
            $stream.Dispose()
        }
    } catch { [Console]::Out.WriteLine('<<ERROR>> ' + $_.Exception.Message) }
    [Console]::Out.WriteLine('<<END>>'); [Console]::Out.Flush()
}
"""


class _Worker:
    def __init__(self):
        self.proc: subprocess.Popen | None = None
        self.lock = threading.Lock()
        self.last_used = 0.0
        self.script = None

    def _start(self):
        if self.script is None:
            fd, self.script = tempfile.mkstemp(suffix=".ps1", prefix="jarvis_ocr_")
            with os.fdopen(fd, "w", encoding="utf-8-sig") as f:
                f.write(_SCRIPT)
        self.proc = subprocess.Popen(
            ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", self.script],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
            encoding="utf-8", errors="replace", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if self._wait_for("<<READY>>", 15) is None:
            self.stop()
            raise RuntimeError("the Windows OCR helper didn't start")
        threading.Thread(target=self._reaper, name="ocr-idle", daemon=True).start()

    def _wait_for(self, marker: str, timeout: float) -> list[str] | None:
        """The lines before `marker`, or None if it didn't come in time (the helper is then killed)."""
        proc, lines = self.proc, []
        watchdog = threading.Timer(timeout, proc.kill)  # a stuck read ends with the process
        watchdog.start()
        try:
            while True:
                line = proc.stdout.readline()
                if not line:
                    return None
                line = line.strip("﻿\r\n")
                if line == marker:
                    return lines
                lines.append(line)
        finally:
            watchdog.cancel()

    def _reaper(self):
        while self.proc and self.proc.poll() is None:
            time.sleep(10)
            if time.monotonic() - self.last_used > IDLE_SECONDS:
                with self.lock:
                    if time.monotonic() - self.last_used > IDLE_SECONDS:
                        log.info("OCR helper idle; closing it")
                        self.stop()
                return

    def stop(self):
        if self.proc:
            try:
                self.proc.kill()
            except Exception:
                pass
        self.proc = None

    def ask(self, command: str) -> list[str]:
        with self.lock:
            self.last_used = time.monotonic()
            if not self.proc or self.proc.poll() is not None:
                self._start()
            self.proc.stdin.write(command + "\n")
            self.proc.stdin.flush()
            lines = self._wait_for("<<END>>", READ_TIMEOUT)
            self.last_used = time.monotonic()
            if lines is None:
                self.stop()  # stuck: start fresh next time
                raise RuntimeError("the Windows helper took too long")
        if lines and lines[0].startswith("<<ERROR>>"):
            raise RuntimeError(lines[0][10:])
        return [ln for ln in lines if ln.strip()]


_worker = _Worker()


# ---- text with positions ---------------------------------------------------------------

@dataclass
class Line:
    text: str
    rect: tuple[int, int, int, int]                  # left, top, right, bottom in screen pixels
    words: list[tuple[str, tuple]] = field(default_factory=list)


_last: list[Line] = []  # the latest read, for clicking text by name


def _rect(box: str, scale: float, ox: int, oy: int) -> tuple[int, int, int, int]:
    x, y, w, h = (float(v) for v in box.split(","))
    return (round(ox + x * scale), round(oy + y * scale), round(ox + (x + w) * scale), round(oy + (y + h) * scale))


def parse_lines(raw: list[str], scale: float = 1.0, ox: int = 0, oy: int = 0) -> list[Line]:
    lines: list[Line] = []
    for row in raw:
        kind, _, rest = row.partition("\t")
        box, _, text = rest.partition("\t")
        try:
            rect = _rect(box, scale, ox, oy)
        except ValueError:
            continue
        if kind == "L":
            lines.append(Line(text.strip(), rect))
        elif kind == "W" and lines:
            lines[-1].words.append((text.strip(), rect))
    return [ln for ln in lines if ln.text]


def read_image_lines(path: str) -> list[Line]:
    return parse_lines(_worker.ask(os.path.abspath(path)))


def read_front_lines(max_width: int = 1600) -> list[Line]:
    """The text lines in the front window, top to bottom, with where they are on screen."""
    global _last
    import win32gui
    from PIL import ImageGrab

    t0 = time.monotonic()
    l, t, r, b = win32gui.GetWindowRect(win32gui.GetForegroundWindow())
    l, t = max(l, 0), max(t, 0)
    img = ImageGrab.grab(bbox=(l, t, r, b), all_screens=True)
    from ..skills import desktop
    desktop.blank_secret_windows(img, (l, t))  # never read a secrets file, even one peeking in from behind
    scale = 1.0
    if img.width > max_width:
        scale = img.width / max_width
        img = img.resize((max_width, round(img.height / scale)))
    fd, path = tempfile.mkstemp(suffix=".png", prefix="jarvis_ocr_")
    os.close(fd)
    try:
        img.save(path)
        try:
            _last = parse_lines(_worker.ask(path), scale, l, t)
        except RuntimeError as e:
            # 30 Sep (10x run): after a while the helper answered every read with a Windows error ("Exception
            # calling Wait"), and PW failed 5 rounds running. A fresh helper reads fine: restart it and try once more.
            log.warning("OCR helper failed (%s); restarting it", e)
            _worker.stop()
            _last = parse_lines(_worker.ask(path), scale, l, t)
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
    log.info("OCR read %d lines in %.2fs", len(_last), time.monotonic() - t0)
    return _last


def read_front() -> list[str]:
    return [ln.text for ln in read_front_lines()]


def find(name: str, lines: list[Line] | None = None) -> tuple[str, tuple] | None:
    """The on-screen text that best matches `name` (a whole line, or a run of words inside one), with its
    screen rectangle; None if nothing matches well or it's ambiguous."""
    want = " ".join((name or "").lower().split())
    if not want:
        return None
    best: list[tuple[float, str, tuple]] = []
    n_words = len(want.split())
    for ln in (lines if lines is not None else _last):
        cands = [(ln.text, ln.rect)]
        ws = ln.words
        for size in {n_words, n_words + 1, max(1, n_words - 1)}:
            for i in range(0, max(0, len(ws) - size + 1)):
                run = ws[i:i + size]
                text = " ".join(w for w, _ in run)
                rect = (min(r[0] for _, r in run), min(r[1] for _, r in run),
                        max(r[2] for _, r in run), max(r[3] for _, r in run))
                cands.append((text, rect))
        for text, rect in cands:
            score = fuzz.ratio(want, " ".join(text.lower().split()))
            best.append((score, text, rect))
    if not best:
        return None
    best.sort(key=lambda s: -s[0])
    score, text, rect = best[0]
    if score < 80:
        return None
    rivals = [b for b in best[1:] if b[0] >= score - 2 and b[2] != rect and b[1].lower() != text.lower()]
    if any(abs(b[2][1] - rect[1]) > 5 for b in rivals if b[0] >= score):
        return None  # the same words twice in different places: don't guess
    return text, rect


# ---- media status ------------------------------------------------------------------------

def media_status() -> dict[str, str]:
    """{app id: 'Playing' | 'Paused' | 'Stopped' | …} for every media session Windows knows about."""
    out = {}
    for row in _worker.ask("::media"):
        app, _, status = row.partition("\t")
        if app:
            out[app] = status.strip()
    return out


def playing(app: str = "") -> bool | None:
    """Is `app`'s media playing ("brave", "chrome", "spotify"…)? True/False, or None when that can't be told.

    Only the app in front counts: 30 Sep, a video paused fine in Brave while Chrome (chess.com's sounds) was
    "Playing", and a check that looked at every app said the pause had failed, three requests in a row."""
    status = media_status()
    if not status:
        return None
    app = app.lower().removesuffix(".exe")
    app = {"msedge": "edge"}.get(app, app)
    mine = [s for name, s in status.items() if app and app in name.lower()]
    if mine:
        return any(s == "Playing" for s in mine)
    if len(status) == 1 and not app:
        return next(iter(status.values())) == "Playing"
    return None  # the front app has no media of its own: nothing to judge by
