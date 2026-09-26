import ctypes

# Work in real screen pixels. With Windows display scaling (125% on this PC) a
# non-aware process sees a shrunken 1536x864 screen, so screenshots and mouse
# clicks wouldn't line up. Must happen before any window or screenshot call.
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # per-monitor aware
except (AttributeError, OSError):
    pass  # already set, or very old Windows
