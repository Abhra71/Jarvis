"""Windows' own text reading (OCR): offline, free, no AI. The agent's backup eyes for windows that don't
name their buttons (games, some web apps, pictures of text).

Windows 10/11 ship an OCR engine (Windows.Media.Ocr). Python can't reach it without extra compiled
packages (which Smart App Control may block), so a small PowerShell helper does the reading. It starts on
first use, stays running while it's being used (~0.2-0.4 s a read instead of ~2 s to start PowerShell
each time) and exits after IDLE_SECONDS, like the GPU hearing: nothing runs while Jarvis just waits.
"""

import logging
import os
import subprocess
import tempfile
import threading
import time

log = logging.getLogger(__name__)

IDLE_SECONDS = 120
READ_TIMEOUT = 6.0

# Reads image paths from stdin, one per line; answers each with the text lines, then a line "<<END>>".
_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics, ContentType = WindowsRuntime]
$asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
    $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Await($op, [Type]$type) {
    $t = $asTask.MakeGenericMethod($type).Invoke($null, @($op)); $t.Wait(-1) | Out-Null; $t.Result }
$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
[Console]::Out.WriteLine('<<READY>>'); [Console]::Out.Flush()
while ($true) {
    $path = [Console]::In.ReadLine()
    if ($path -eq $null -or $path -eq '') { break }
    try {
        $file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($path)) ([Windows.Storage.StorageFile])
        $stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
        $decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
        $bitmap = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
        $result = Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
        foreach ($line in $result.Lines) { [Console]::Out.WriteLine($line.Text) }
        $stream.Dispose()
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
            encoding="utf-8", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
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

    def read(self, image_path: str) -> list[str]:
        with self.lock:
            self.last_used = time.monotonic()
            if not self.proc or self.proc.poll() is not None:
                self._start()
            self.proc.stdin.write(image_path + "\n")
            self.proc.stdin.flush()
            lines = self._wait_for("<<END>>", READ_TIMEOUT)
            self.last_used = time.monotonic()
            if lines is None:
                self.stop()  # stuck: start fresh next time
                raise RuntimeError("OCR took too long")
        if lines and lines[0].startswith("<<ERROR>>"):
            raise RuntimeError(lines[0][10:])
        return [ln.strip() for ln in lines if ln.strip()]


_worker = _Worker()


def read_image(path: str) -> list[str]:
    return _worker.read(os.path.abspath(path))


def read_front(max_width: int = 1600) -> list[str]:
    """The text lines in the front window, top to bottom."""
    import win32gui
    from PIL import ImageGrab

    t0 = time.monotonic()
    l, t, r, b = win32gui.GetWindowRect(win32gui.GetForegroundWindow())
    img = ImageGrab.grab(bbox=(max(l, 0), max(t, 0), r, b), all_screens=True)
    if img.width > max_width:
        img = img.resize((max_width, round(img.height * max_width / img.width)))
    fd, path = tempfile.mkstemp(suffix=".png", prefix="jarvis_ocr_")
    os.close(fd)
    try:
        img.save(path)
        lines = read_image(path)
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
    log.info("OCR read %d lines in %.2fs", len(lines), time.monotonic() - t0)
    return lines
