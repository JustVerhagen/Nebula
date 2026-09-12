"""Small, window-specific screenshots, including when another app covers Spotify."""
import io
import time


def await_result(start, timeout=4):
    import Foundation as F
    result = []
    def completed(value, error):
        result.append((value, error))
    start(completed)
    deadline = time.monotonic() + timeout
    while not result and time.monotonic() < deadline:
        F.NSRunLoop.currentRunLoop().runUntilDate_(F.NSDate.dateWithTimeIntervalSinceNow_(.01))
    if not result:
        raise TimeoutError('Spotify window capture timed out')
    value, error = result[0]
    if error is not None or value is None:
        raise RuntimeError('macOS could not capture Spotify; check Screen Recording permission')
    return value


class WindowCapture:
    def __init__(self):
        import ScreenCaptureKit as SC
        import Quartz as Q
        self.SC, self.Q = SC, Q
        self.windows = []
        self.refreshed = 0

    def spotify_window(self):
        # Cheap live inventory prevents a cached closed window from being captured.
        inventory = self.Q.CGWindowListCopyWindowInfo(
            self.Q.kCGWindowListOptionAll | self.Q.kCGWindowListExcludeDesktopElements,
            self.Q.kCGNullWindowID) or []
        ids = {int(w['kCGWindowNumber']) for w in inventory
               if w.get('kCGWindowOwnerName') == 'Spotify' and w.get('kCGWindowLayer') == 0
               and w['kCGWindowBounds']['Width'] > 400 and w['kCGWindowBounds']['Height'] > 300}
        if not ids:
            return None
        if time.monotonic()-self.refreshed > 3 or not any(int(w.windowID()) in ids for w in self.windows):
            content = await_result(lambda done: self.SC.SCShareableContent.
                getShareableContentExcludingDesktopWindows_onScreenWindowsOnly_completionHandler_(True, False, done))
            self.windows = [w for w in content.windows()
                            if w.owningApplication() and str(w.owningApplication().bundleIdentifier()) == 'com.spotify.client'
                            and w.windowLayer() == 0]
            self.refreshed = time.monotonic()
        candidates = [w for w in self.windows if int(w.windowID()) in ids]
        return max(candidates, key=lambda w: (bool(w.isOnScreen()), w.frame().size.width*w.frame().size.height), default=None)

    def capture(self, window):
        from AppKit import NSBitmapImageRep, NSBitmapImageFileTypePNG
        from PIL import Image
        frame = window.frame()
        scale = min(320/frame.size.width, 240/frame.size.height)
        config = self.SC.SCStreamConfiguration.alloc().init()
        config.setWidth_(max(1, round(frame.size.width*scale)))
        config.setHeight_(max(1, round(frame.size.height*scale)))
        config.setShowsCursor_(False)
        config.setIgnoreShadowsSingleWindow_(True)
        content_filter = self.SC.SCContentFilter.alloc().initWithDesktopIndependentWindow_(window)
        captured = await_result(lambda done: self.SC.SCScreenshotManager.
            captureImageWithFilter_configuration_completionHandler_(content_filter, config, done))
        bitmap = NSBitmapImageRep.alloc().initWithCGImage_(captured)
        png = bitmap.representationUsingType_properties_(NSBitmapImageFileTypePNG, {})
        return Image.open(io.BytesIO(bytes(png))).convert('RGB')
