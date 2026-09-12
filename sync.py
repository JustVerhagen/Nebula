"""Sync Spotify's visible artwork atmosphere to the lights selected in Nebula.

Run `python sync.py --help`. Screenshots stay in memory; tokens live in Keychain.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import fcntl
import getpass
import json
import logging
from logging.handlers import RotatingFileHandler
import math
import os
from pathlib import Path
import plistlib
import signal
import statistics
import subprocess
import sys
import threading
import time
from urllib.parse import urlsplit

SOURCE_ROOT = Path(__file__).resolve().parent
ROOT = Path(os.environ.get('NEBULA_DATA_DIR', SOURCE_ROOT))
CONFIG = ROOT / 'config.json'
LABEL = 'local.spotify-hue.sync'
KEYCHAIN_SERVICE = 'spotify-hue-home-assistant'
LOG = logging.getLogger('spotify-hue')
STOP = threading.Event()


def validate_address(address):
    message = ('The Home Assistant ADDRESS is invalid (this is not the strip entity). '
               'Enter http://homeassistant.local:8123 or press Enter to use the saved address.')
    try:
        parsed = urlsplit(address.strip())
        if (parsed.scheme not in ('http', 'https') or not parsed.hostname
                or parsed.username or parsed.password or parsed.query or parsed.fragment
                or parsed.path not in ('', '/') or any(c.isspace() for c in address.strip())):
            raise ValueError(message)
        _ = parsed.port
    except ValueError:
        raise ValueError(message) from None
    return address.strip().rstrip('/')


def load_config():
    path = CONFIG if CONFIG.exists() else SOURCE_ROOT / 'config.example.json'
    config = json.loads(path.read_text())
    from nebula_settings import defaults
    config = defaults(config)
    config.setdefault('fallback_seconds', 5)
    for key, low, high in [('interval_seconds', 1, 60), ('idle_seconds', 3, 120),
                           ('transition_seconds', 0, 10), ('fallback_seconds', 2, 60), ('minimum_color_change', 1, 100),
                           ('patch_size', 4, 100)]:
        if not low <= config[key] <= high:
            raise ValueError(f'{key} must be between {low} and {high}.')
    points = config['sample_points']
    if not points or len(points) > 12 or any(
        len(p) != 2 or any(not 0.02 <= v <= 0.98 for v in p) for p in points
    ):
        raise ValueError('Use 1–12 sample points with coordinates between .02 and .98.')
    if not config['fullscreen_labels']:
        raise ValueError('At least one full-screen exit label is required.')
    return config


def median_color(pixels):
    return tuple(round(statistics.median(channel)) for channel in zip(*pixels))


def color_distance(a, b):
    return math.sqrt(sum((x-y)**2 for x, y in zip(a, b)))


class ColorGate:
    """Require two agreeing samples, then send only meaningful changes."""
    def __init__(self, threshold):
        self.threshold = threshold
        self.previous = None
        self.sent = None

    def reset(self):
        self.previous = self.sent = None

    def candidate(self, color):
        stable = self.previous is not None and color_distance(color, self.previous) < 12
        self.previous = color
        return stable and (self.sent is None or color_distance(color, self.sent) >= self.threshold)


class SpotifyScreen:
    def __init__(self, config):
        import AppKit
        import ApplicationServices as AX
        import Quartz
        import Foundation
        self.Foundation = Foundation
        self.workspace = AppKit.NSWorkspace.sharedWorkspace()
        self.AppKit, self.AX, self.Q = AppKit, AX, Quartz
        self.config = config
        self.last_labels = []
        from window_capture import WindowCapture
        self.capture = WindowCapture()

    def permissions(self, request=False):
        if request:
            self.Q.CGRequestScreenCaptureAccess()
        return bool(self.AX.AXIsProcessTrusted()), bool(self.Q.CGPreflightScreenCaptureAccess())

    def attr(self, element, name):
        err, value = self.AX.AXUIElementCopyAttributeValue(element, name, None)
        return value if err == 0 else None

    def foreground_app(self):
        # NSWorkspace caches app state until the main run loop processes events.
        # threading.Event.wait alone does not service Cocoa notifications.
        self.Foundation.NSRunLoop.currentRunLoop().runUntilDate_(
            self.Foundation.NSDate.dateWithTimeIntervalSinceNow_(0.02))
        return self.workspace.frontmostApplication()

    def active_window(self):
        from visual import inspect_artwork
        self.last_labels = []
        self._captured_color = None
        if not self.permissions()[1]:
            raise RuntimeError('Screen Recording permission is required')
        window = self.capture.spotify_window()
        if window is None:
            return None, 'Spotify artwork window is closed'
        self._captured_color, reason = inspect_artwork(self.capture.capture(window))
        if self._captured_color is None:
            return None, reason
        return window, reason

    def sample(self, bounds):
        # Reuse the very same frame that passed the artwork check.
        if self._captured_color is None:
            raise RuntimeError('No validated artwork colour is available')
        return self._captured_color


class HomeAssistant:
    def __init__(self, config, token=None):
        import keyring
        import requests
        self.config = config
        self.base = config['home_assistant_url'].rstrip('/')
        token = token or keyring.get_password(KEYCHAIN_SERVICE, self.base)
        if not token:
            raise ValueError('No token in Keychain. Run: python sync.py setup')
        self.session = requests.Session()
        self.session.headers.update({'Authorization': 'Bearer ' + token})

    def request(self, method, path, **kwargs):
        response = self.session.request(method, self.base + '/api/' + path,
                                        timeout=(3, 5), allow_redirects=False, **kwargs)
        if not 200 <= response.status_code < 300:
            raise RuntimeError(f'Home Assistant returned HTTP {response.status_code}; check address, token and entity.')
        return response.json()

    def state(self):
        return self.request('GET', 'states/' + self.config['entity_id'])

    def color(self, rgb):
        # Never send brightness or an off command. Recheck state before every write.
        if self.state().get('state') != 'on':
            return False
        self.request('POST', 'services/light/turn_on', json={
            'entity_id': self.config['entity_id'], 'rgb_color': list(rgb),
            'transition': self.config['transition_seconds']})
        return True

    def warm(self):
        mode = self.config.get('return_mode', 'warm')
        if mode == 'keep':
            return False
        state = self.state()
        if state.get('state') != 'on':
            return False
        attributes = state.get('attributes', {})
        payload = {'entity_id': self.config['entity_id'], 'transition': 1.2}
        if mode == 'custom':
            value = self.config.get('return_color', '#FFCD9B').lstrip('#')
            payload['rgb_color'] = [int(value[i:i+2], 16) for i in (0, 2, 4)]
        elif 'color_temp' in attributes.get('supported_color_modes', []):
            kelvin = self.config.get('warm_kelvin', 3000)
            kelvin = max(attributes.get('min_color_temp_kelvin', 2000),
                         min(attributes.get('max_color_temp_kelvin', 6500), kelvin))
            payload['color_temp_kelvin'] = kelvin
        else:
            payload['rgb_color'] = [255, 205, 155]
        self.request('POST', 'services/light/turn_on', json=payload)
        return True


class LightingController:
    """Fan commands out to selected lights while isolating provider failures."""
    def __init__(self, config):
        import keyring
        from providers import make_provider
        self.config = config
        self.providers = {}
        for connection in config.get('connections', []):
            secret = keyring.get_password('nebula-lighting', connection['id']) or ''
            self.providers[connection['id']] = make_provider(connection, secret)

    def selected(self):
        return [light for light in self.config.get('lights', []) if light.get('sync', True)]

    def color(self, rgb):
        changed = False
        for light in self.selected():
            provider = self.providers.get(light['connection_id'])
            if provider:
                provider.set_state(light['id'], rgb=rgb,
                                   transition=self.config.get('transition_seconds', .25))
                changed = True
        return changed

    def state(self):
        # Compatibility with the event loop's inexpensive periodic check.
        return {'state': 'on' if self.selected() else 'off'}

    def warm(self):
        mode = self.config.get('return_mode', 'warm')
        if mode == 'keep':
            return False
        if mode == 'custom':
            value = self.config.get('return_color', '#FFCD9B').lstrip('#')
            rgb = tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))
        else:
            # Cross-provider warm-white approximation; providers can add native
            # temperature support later without changing the engine.
            rgb = (255, 205, 155)
        changed = False
        for light in self.selected():
            provider = self.providers.get(light['connection_id'])
            if provider:
                provider.set_state(light['id'], rgb=rgb, transition=1.2)
                changed = True
        return changed

class ArtworkExit:
    """Restore warm light once after two seconds of confirmed non-artwork frames."""
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.active = False
        self.missing_since = None

    def seen(self):
        self.active = True
        self.missing_since = None

    def missing(self):
        if not self.active:
            return False
        if self.missing_since is None:
            self.missing_since = self.clock()
        return self.clock()-self.missing_since >= 2

    def restored(self):
        self.active = False
        self.missing_since = None


@contextmanager
def single_instance():
    with (ROOT / '.sync.lock').open('w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('A sync process is already running. Stop it before starting another.')
        yield


def run(config, dry_run=False):
    screen = SpotifyScreen(config)
    if not screen.permissions()[1]:
        raise RuntimeError('Run python sync.py doctor --request-permissions, grant permissions, then restart.')
    client = None if dry_run else LightingController(config)
    gate = ColorGate(config['minimum_color_change'])
    artwork_exit = ArtworkExit()
    last_status = None
    def status(message):
        nonlocal last_status
        if message != last_status:
            LOG.info(message)
            last_status = message
    from events import Schedule, PlaybackEvents
    schedule = Schedule(config.get('fallback_seconds', 5))
    events = PlaybackEvents(schedule, screen.workspace, LOG)
    LOG.info('Listening for Spotify track changes; backup check every %s seconds', schedule.fallback)
    try:
        with single_instance():
            while not STOP.is_set():
                events.wait(STOP)
                if STOP.is_set():
                    break
                try:
                    bounds, reason = screen.active_window()
                    if bounds is None:
                        gate.reset()
                        status(reason)
                        first_missing = artwork_exit.active and artwork_exit.missing_since is None
                        if artwork_exit.missing():
                            if dry_run:
                                LOG.info('Preview: returning to gentle warm white')
                            elif client.warm():
                                LOG.info('Returned to your resting light colour')
                            artwork_exit.restored()
                        elif first_missing:
                            schedule.trigger(seconds=2.5)
                    else:
                        artwork_exit.seen()
                        color = screen.sample(bounds)
                        status('Artwork mode detected; previewing colours' if dry_run else 'Artwork mode detected; syncing')
                        changed = gate.previous is None or color_distance(color, gate.previous) >= 12
                        if changed:
                            schedule.trigger(seconds=1.5)
                        if gate.candidate(color):
                            if dry_run or client.color(color):
                                gate.sent = color
                                LOG.info('%s RGB %s', 'Preview' if dry_run else 'Applied', color)
                            else:
                                status('Strip is off or unavailable; waiting without changing it')
                        elif client and schedule.clock() >= schedule.fast_until:
                            if client.state().get('state') != 'on':
                                gate.reset()
                    schedule.sampled()
                except Exception as exc:
                    status(f'Waiting after {type(exc).__name__}; run doctor if this persists')
                    gate.reset()
                    schedule.backoff()
    finally:
        events.close()


def setup(config):
    import keyring
    print('Home Assistant setup. Your token will be hidden and stored in macOS Keychain.')
    while True:
        address = input(f"Home Assistant address [{config['home_assistant_url']}]: ").strip() or config['home_assistant_url']
        try:
            config['home_assistant_url'] = validate_address(address)
            break
        except ValueError as exc:
            print(exc)
    while True:
        entity = input(f"Strip entity [{config['entity_id']}]: ").strip() or config['entity_id']
        if entity.startswith('light.') and len(entity) > 6 and all(c.isalnum() or c in '._' for c in entity):
            config['entity_id'] = entity
            break
        print('The strip entity must look like light.light. Please try again.')
    token = getpass.getpass('Home Assistant long-lived access token: ').strip()
    if not token:
        raise ValueError('No token entered.')
    client = HomeAssistant(config, token)
    state = client.state()
    modes = state.get('attributes', {}).get('supported_color_modes', [])
    if not set(modes) & {'hs', 'xy', 'rgb', 'rgbw', 'rgbww'}:
        raise ValueError('This entity does not report colour support. Check the entity ID.')
    keyring.set_password(KEYCHAIN_SERVICE, client.base, token)
    CONFIG.write_text(json.dumps(config, indent=2) + '\n')
    CONFIG.chmod(0o600)
    print('Connection verified; settings saved. No light changes were made.')


def doctor(config, request=False):
    screen = SpotifyScreen(config)
    accessibility, recording = screen.permissions(request)
    print(f'Screen Recording: {recording}\nAccessibility (not required): {accessibility}')
    bounds, reason = screen.active_window()
    print(reason)
    if bounds:
        print('Background RGB:', screen.sample(bounds))
    if CONFIG.exists():
        try:
            state = HomeAssistant(config).state()
            print('Home Assistant light:', state.get('state'))
        except Exception as exc:
            print('Home Assistant check:', type(exc).__name__, str(exc))
    else:
        print('Home Assistant not configured. Run setup when ready.')


def service(action):
    target = Path.home() / 'Library' / 'LaunchAgents' / (LABEL + '.plist')
    domain = f'gui/{os.getuid()}'
    if action == 'install':
        if not CONFIG.exists():
            raise ValueError('Run setup before enabling automatic startup.')
        target.parent.mkdir(parents=True, exist_ok=True)
        data = {
            'Label': LABEL,
            'ProgramArguments': [str(ROOT / '.venv' / 'bin' / 'python'), str(ROOT / 'sync.py'), 'run'],
            'WorkingDirectory': str(ROOT), 'RunAtLoad': True,
            'KeepAlive': {'SuccessfulExit': False}, 'ThrottleInterval': 30,
            'ProcessType': 'Background', 'LimitLoadToSessionType': 'Aqua',
            'EnvironmentVariables': {'PYTHONUNBUFFERED': '1'},
        }
        subprocess.run(['launchctl', 'bootout', domain + '/' + LABEL], capture_output=True)
        target.write_bytes(plistlib.dumps(data))
        subprocess.run(['launchctl', 'bootstrap', domain, str(target)], check=True)
        print('Automatic startup enabled. Check sync.log after switching to Spotify full-screen.')
    elif action == 'stop':
        result = subprocess.run(['launchctl', 'bootout', domain + '/' + LABEL], capture_output=True)
        print('Stopped (or was already stopped). Startup setting is unchanged.')
    elif action == 'uninstall':
        subprocess.run(['launchctl', 'bootout', domain + '/' + LABEL], capture_output=True)
        target.unlink(missing_ok=True)
        print('Automatic startup removed. Project and Keychain token retained.')
    elif action == 'status':
        result = subprocess.run(['launchctl', 'print', domain + '/' + LABEL], capture_output=True, text=True)
        print(result.stdout if result.returncode == 0 else 'Background service is not loaded.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['setup', 'doctor', 'preview', 'run', 'install', 'stop', 'uninstall', 'status'])
    parser.add_argument('--request-permissions', action='store_true', help='Ask macOS for capture/accessibility access (doctor only)')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
    handler = RotatingFileHandler(ROOT / 'sync.log', maxBytes=300_000, backupCount=2)
    handler.setFormatter(logging.Formatter('%(asctime)s %(message)s'))
    LOG.addHandler(handler)
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: STOP.set())
    config = load_config()
    if args.command == 'setup':
        setup(config)
    elif args.command == 'doctor':
        doctor(config, args.request_permissions)
    elif args.command in ('run', 'preview'):
        run(config, dry_run=args.command == 'preview')
    else:
        service(args.command)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        pass
