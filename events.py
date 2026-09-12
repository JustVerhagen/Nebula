"""Wake on Spotify playback notifications; poll slowly as a compatibility fallback."""
import time


class Schedule:
    def __init__(self, fallback=5.0, clock=time.monotonic):
        self.clock = clock
        self.fallback = fallback
        self.fast_until = clock() + 3
        self.due = clock()
        self.last_playback = None
        self.events = 0

    def trigger(self, seconds=4):
        now = self.clock()
        self.fast_until = max(self.fast_until, now + seconds)
        self.due = min(self.due, now + .05)

    def playback(self, info):
        # Position changes alone do not require another artwork capture burst.
        identity = tuple(str(info.get(k, '')) for k in ('Track ID', 'Name', 'Artist', 'Player State'))
        if any(identity) and identity == self.last_playback:
            return False
        self.last_playback = identity
        self.events += 1
        self.trigger()
        return True

    def sampled(self):
        now = self.clock()
        self.due = now + (.25 if now < self.fast_until else self.fallback)

    def backoff(self, seconds=15):
        self.fast_until = 0
        self.due = self.clock() + seconds


class PlaybackEvents:
    def __init__(self, schedule, workspace, logger, notification_name='com.spotify.client.PlaybackStateChanged'):
        import Foundation as F
        self.F = F
        self.schedule = schedule
        self.center = F.NSDistributedNotificationCenter.defaultCenter()
        self.workspace_center = workspace.notificationCenter()
        def changed(notification):
            if schedule.playback(notification.userInfo() or {}):
                logger.info('Spotify playback event; checking new artwork')
        def activated(notification):
            schedule.trigger(seconds=2)
        # Keep Python blocks and returned observer tokens alive until close().
        self.callbacks = (changed, activated)
        self.playback_observer = self.center.addObserverForName_object_queue_usingBlock_(
            notification_name, None, None, changed)
        self.focus_observer = self.workspace_center.addObserverForName_object_queue_usingBlock_(
            'NSWorkspaceDidActivateApplicationNotification', None, None, activated)

    def wait(self, stop):
        import CoreFoundation as CF
        import objc
        while not stop.is_set():
            remaining = self.schedule.due - self.schedule.clock()
            if remaining <= 0:
                return
            # Sleep in the native event loop, waking immediately for notifications.
            # This services NSWorkspace updates without repeatedly reading the screen.
            with objc.autorelease_pool():
                CF.CFRunLoopRunInMode(CF.kCFRunLoopDefaultMode, min(remaining, .5), True)

    def close(self):
        self.center.removeObserver_(self.playback_observer)
        self.workspace_center.removeObserver_(self.focus_observer)
