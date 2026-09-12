"""Nebula: a native macOS menu-bar app for music-reactive smart lights."""
from __future__ import annotations
import fcntl
import json
import logging
import os
from pathlib import Path
import plistlib
import queue
import subprocess
import sys
import threading
import time
import re
import traceback

SOURCE = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))
DATA = Path(os.environ.get('NEBULA_DATA_DIR', Path.home() / 'Library/Application Support/Nebula'))
os.environ['NEBULA_DATA_DIR'] = str(DATA)
DATA.mkdir(parents=True, exist_ok=True)


def engine():
    import sync
    from nebula_settings import save_config
    class StatusHandler(logging.Handler):
        def emit(self, record):
            try:
                message = record.getMessage()
                state = {'message': message, 'time': time.time()}
                match = re.search(r'RGB \((\d+), (\d+), (\d+)\)', message)
                if match:
                    state['color'] = [int(value) for value in match.groups()]
                save_config(DATA / 'status.json', state)
            except Exception:
                pass
    sync.LOG.addHandler(StatusHandler())
    sys.argv = [str(SOURCE / 'sync.py'), 'run']
    try:
        sync.main()
    except Exception as exc:
        message = str(exc) if isinstance(exc, (ValueError, RuntimeError)) else type(exc).__name__
        save_config(DATA / 'status.json', {'message': message, 'time': time.time(), 'error': True})
        sys.exit(1)


if '--engine' in sys.argv:
    engine()
    sys.exit(0)

import AppKit as A
import Foundation as F
import Quartz as Q
import WebKit as W
import objc
import requests
from nebula_settings import defaults, edited, save_config, connection_from_input
from providers import make_provider, _request
import sync

APP_ID = 'local.nebula.app'
LOGIN_ID = 'local.nebula.login'
SECRET_SERVICE = 'nebula-lighting'


def launch_path():
    return Path(sys.executable).parents[2] if getattr(sys, 'frozen', False) else None


def configure_login(enabled):
    target = Path.home() / 'Library/LaunchAgents' / (LOGIN_ID + '.plist')
    if not enabled:
        target.unlink(missing_ok=True)
        return
    bundle = launch_path()
    if not bundle:
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(plistlib.dumps({'Label': LOGIN_ID,
        'ProgramArguments': ['/usr/bin/open', '-gj', str(bundle)], 'RunAtLoad': True,
        'LimitLoadToSessionType': 'Aqua'}))


def public_status(message):
    if 'Applied RGB' in message: return 'Atmosphere matched', False
    if 'resting light' in message: return 'Resting glow restored', False
    if 'artwork window is closed' in message: return 'Open Spotify artwork view', False
    if 'Artwork mode detected' in message: return 'Following Spotify', False
    if 'permission' in message.lower(): return 'Allow window capture to start', True
    if 'Waiting after' in message: return 'Connection interrupted · retrying', True
    return 'Listening for your music', False


class NebulaDelegate(F.NSObject):
    def applicationDidFinishLaunching_(self, notification):
        try:
            self.setupInterface()
        except Exception:
            (DATA / 'startup-error.log').write_text(traceback.format_exc())
            alert = A.NSAlert.alloc().init()
            alert.setMessageText_('Nebula could not start')
            alert.setInformativeText_('A startup error was saved in Nebula’s Application Support folder.')
            alert.runModal()
            A.NSApp.terminate_(None)

    @objc.python_method
    def setupInterface(self):
        self.child = self.worker_log = None
        self.results = queue.Queue()
        self.last_json = ''
        self.color = [128, 96, 255]
        self.retry_at = 0
        self.ready = False
        self.config = defaults(sync.load_config())
        self.app_lock = (DATA / '.nebula.lock').open('w')
        try:
            fcntl.flock(self.app_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            A.NSApp.terminate_(None); return
        save_config(DATA / 'config.json', self.config)
        self.status_item = A.NSStatusBar.systemStatusBar().statusItemWithLength_(28)
        button = self.status_item.button()
        icon = A.NSImage.alloc().initWithContentsOfFile_(str(SOURCE / 'nebula_ui/menu.png'))
        icon.setSize_((20, 20)); icon.setTemplate_(True)
        button.setImage_(icon); button.setToolTip_('Nebula · music into atmosphere')
        button.setTarget_(self); button.setAction_('togglePanel:')
        configuration = W.WKWebViewConfiguration.alloc().init()
        configuration.userContentController().addScriptMessageHandler_name_(self, 'nebula')
        self.web = W.WKWebView.alloc().initWithFrame_configuration_(((0, 0), (420, 650)), configuration)
        self.web.setNavigationDelegate_(self); self.web.setValue_forKey_(False, 'drawsBackground')
        controller = A.NSViewController.alloc().init(); controller.setView_(self.web)
        self.popover = A.NSPopover.alloc().init(); self.popover.setContentSize_((420, 650))
        self.popover.setContentViewController_(controller); self.popover.setBehavior_(A.NSPopoverBehaviorTransient)
        self.popover.setAnimates_(True); self.popover.setDelegate_(self)
        self.web.loadHTMLString_baseURL_((SOURCE / 'nebula_ui/index.html').read_text(), None)
        self.timer = F.NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(.5, self, 'tick:', None, True)
        if os.environ.get('NEBULA_SHOW_PANEL') == '1':
            self.performSelector_withObject_afterDelay_('togglePanel:', None, .7)

    def webView_decidePolicyForNavigationAction_decisionHandler_(self, view, action, handler):
        handler(W.WKNavigationActionPolicyAllow if str(action.request().URL().absoluteString()) == 'about:blank'
                else W.WKNavigationActionPolicyCancel)

    def userContentController_didReceiveScriptMessage_(self, controller, message):
        if not message.frameInfo().isMainFrame(): return
        try: body = dict(message.body())
        except Exception: return
        action = body.get('action')
        if action == 'ready': self.ready = True; self.publish()
        elif action == 'resize': self.popover.setContentSize_((420, max(520, min(760, int(body.get('height', 650))))))
        elif action == 'toggle_sync':
            self.config['enabled'] = not self.config['enabled']; save_config(DATA / 'config.json', self.config)
            if not self.config['enabled']: self.stopEngine()
            self.retry_at = 0; self.publish()
        elif action == 'permission':
            self.popover.performClose_(None); Q.CGRequestScreenCaptureAccess()
            A.NSWorkspace.sharedWorkspace().openURL_(F.NSURL.URLWithString_(
                'x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture'))
        elif action in ('connect', 'refresh', 'light_control', 'select_light', 'remove_connection',
                        'complete_onboarding', 'save_settings'):
            self.background_(body)
        elif action == 'quit': self.stopEngine(); A.NSApp.terminate_(None)

    @objc.python_method
    def background_(self, body):
        config = json.loads(json.dumps(self.config)); results = self.results
        def work():
            import keyring
            try:
                action = body['action']
                if action == 'connect':
                    connection = connection_from_input(body.get('connection', {}))
                    secret = str(body.get('secret', '')).strip()
                    if connection['kind'] == 'hue' and not secret:
                        response = _request(requests.Session(), 'POST', connection['address'] + '/api',
                                            json={'devicetype': 'nebula#mac'})
                        if not response or 'success' not in response[0]:
                            raise ValueError('Press the round button on your Hue Bridge, then try again.')
                        secret = response[0]['success']['username']
                    provider = make_provider(connection, secret)
                    lights = provider.lights()
                    if not lights: raise ValueError('Connected, but no lights were found.')
                    config['connections'] = [c for c in config['connections'] if c['id'] != connection['id']] + [connection]
                    existing = {(l['connection_id'], l['id']): l for l in config['lights']}
                    config['lights'] = [l for l in config['lights'] if l['connection_id'] != connection['id']]
                    for light in lights:
                        old = existing.get((connection['id'], light.id), {})
                        config['lights'].append({'connection_id': connection['id'], 'id': light.id,
                                                 'name': light.name, 'sync': old.get('sync', True),
                                                 'state': light.json()})
                    if secret: keyring.set_password(SECRET_SERVICE, connection['id'], secret)
                    results.put({'config': config, 'message': f'Connected {connection["name"]} · {len(lights)} light(s) found.'})
                elif action == 'refresh':
                    for connection in config['connections']:
                        provider = make_provider(connection, keyring.get_password(SECRET_SERVICE, connection['id']) or '')
                        states = {light.id: light.json() for light in provider.lights()}
                        for light in config['lights']:
                            if light['connection_id'] == connection['id'] and light['id'] in states:
                                light['state'] = states[light['id']]
                    results.put({'config': config})
                elif action == 'light_control':
                    light = next(l for l in config['lights'] if l['connection_id'] == body['connection_id'] and l['id'] == body['light_id'])
                    connection = next(c for c in config['connections'] if c['id'] == light['connection_id'])
                    provider = make_provider(connection, keyring.get_password(SECRET_SERVICE, connection['id']) or '')
                    kwargs = {}
                    if 'on' in body: kwargs['on'] = bool(body['on'])
                    if body.get('color'): kwargs['rgb'] = tuple(int(body['color'][i:i+2], 16) for i in (1, 3, 5))
                    if 'brightness' in body: kwargs['brightness'] = int(body['brightness'])
                    provider.set_state(light['id'], **kwargs)
                    results.put({'message': f'{light["name"]} updated.', 'refresh': True})
                elif action == 'select_light':
                    for light in config['lights']:
                        if light['connection_id'] == body['connection_id'] and light['id'] == body['light_id']:
                            light['sync'] = bool(body['sync'])
                    results.put({'config': config})
                elif action == 'remove_connection':
                    cid = body['connection_id']; keyring.delete_password(SECRET_SERVICE, cid)
                    config['connections'] = [c for c in config['connections'] if c['id'] != cid]
                    config['lights'] = [l for l in config['lights'] if l['connection_id'] != cid]
                    results.put({'config': config, 'message': 'Lighting system removed.'})
                elif action == 'complete_onboarding':
                    if not config['lights']: raise ValueError('Connect at least one light before finishing setup.')
                    config['onboarding_complete'] = True; config['enabled'] = True
                    results.put({'config': config, 'message': 'Welcome to Nebula. Your atmosphere is ready.'})
                elif action == 'save_settings':
                    config = edited(config, body.get('settings', {}))
                    results.put({'config': config, 'message': 'Settings saved.'})
            except Exception as exc:
                results.put({'message': str(exc) if isinstance(exc, (ValueError, RuntimeError)) else 'Something went wrong. Check the address and try again.', 'error': True})
        threading.Thread(target=work, daemon=True).start()

    @objc.python_method
    def publish(self):
        if not self.ready: return
        permitted = bool(Q.CGPreflightScreenCaptureAccess())
        status, error = ('Sync paused', False)
        if self.config['enabled']:
            status, error = ('Allow window capture', True) if not permitted else ('Listening for your music', False)
            try:
                data = json.loads((DATA / 'status.json').read_text()); status, error = public_status(data.get('message', ''))
                if data.get('color'): self.color = data['color']
            except (OSError, ValueError): pass
        payload = json.dumps({'config': self.config, 'enabled': self.config['enabled'], 'permission': permitted,
                              'status': status, 'error': error, 'color': self.color,
                              'visible': bool(self.popover.isShown())})
        if payload != self.last_json:
            self.last_json = payload
            self.web.evaluateJavaScript_completionHandler_('window.nebulaState(' + payload + ')', None)

    def togglePanel_(self, sender):
        if self.popover.isShown(): self.popover.performClose_(sender)
        else:
            A.NSApp.activateIgnoringOtherApps_(True); button = self.status_item.button()
            self.popover.showRelativeToRect_ofView_preferredEdge_(button.bounds(), button, A.NSMinYEdge)
            self.popover.contentViewController().view().window().makeKeyWindow()
        self.publish()

    @objc.python_method
    def startEngine(self):
        if self.child and self.child.poll() is None: return
        command = [sys.executable, '--engine'] if getattr(sys, 'frozen', False) else [sys.executable, str(SOURCE/'nebula.py'), '--engine']
        path = DATA / 'worker.log'
        if path.exists() and path.stat().st_size > 400_000: path.write_text('')
        self.worker_log = path.open('a')
        self.child = subprocess.Popen(command, env=dict(os.environ, NEBULA_DATA_DIR=str(DATA)), stdout=self.worker_log,
                                      stderr=self.worker_log, start_new_session=True)

    @objc.python_method
    def stopEngine(self):
        if self.child and self.child.poll() is None:
            self.child.terminate()
            try: self.child.wait(timeout=1)
            except subprocess.TimeoutExpired: self.child.kill(); self.child.wait(timeout=1)
        self.child = None
        if self.worker_log: self.worker_log.close(); self.worker_log = None

    def tick_(self, timer):
        while not self.results.empty():
            result = self.results.get_nowait()
            if result.get('config'):
                self.stopEngine(); self.config = result['config']; save_config(DATA / 'config.json', self.config)
                configure_login(self.config.get('login', True)); self.retry_at = 0
            self.web.evaluateJavaScript_completionHandler_('window.nebulaResult(' + json.dumps(result) + ')', None)
            if result.get('refresh'): self.background_({'action': 'refresh'})
        if self.child and self.child.poll() is not None: self.stopEngine(); self.retry_at = time.monotonic() + 20
        if self.config['enabled'] and self.config['lights'] and Q.CGPreflightScreenCaptureAccess() and not self.child and time.monotonic() >= self.retry_at:
            self.startEngine()
        self.publish()

    def applicationWillTerminate_(self, notification): self.stopEngine()


def main():
    application = A.NSApplication.sharedApplication(); application.setActivationPolicy_(A.NSApplicationActivationPolicyAccessory)
    delegate = NebulaDelegate.alloc().init(); application.setDelegate_(delegate); application.run()


if __name__ == '__main__': main()
