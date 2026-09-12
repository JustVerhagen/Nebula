"""Local smart-light providers used by Nebula.

The public surface is deliberately small so additional providers can be added
without touching the Spotify engine or the interface.
"""
from __future__ import annotations

import colorsys
from dataclasses import dataclass
from urllib.parse import urlsplit

import requests


class ProviderError(RuntimeError):
    pass


def clean_url(value: str) -> str:
    value = value.strip().rstrip('/')
    parsed = urlsplit(value)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('Enter a complete local address beginning with http:// or https://.')
    return value


def _request(session, method, url, **kwargs):
    try:
        response = session.request(method, url, timeout=(3, 6), allow_redirects=False, **kwargs)
    except requests.RequestException as exc:
        raise ProviderError('Could not reach this lighting system. Check its address and your Wi-Fi.') from exc
    if not 200 <= response.status_code < 300:
        raise ProviderError(f'The lighting system returned HTTP {response.status_code}. Check its credentials.')
    if not response.content:
        return {}
    try:
        return response.json()
    except ValueError as exc:
        raise ProviderError('The lighting system returned an unreadable response.') from exc


@dataclass
class Light:
    id: str
    name: str
    on: bool = False
    color: tuple[int, int, int] | None = None
    brightness: int | None = None

    def json(self):
        return {'id': self.id, 'name': self.name, 'on': self.on,
                'color': list(self.color) if self.color else None, 'brightness': self.brightness}


class BaseProvider:
    kind = ''

    def __init__(self, connection, secret=''):
        self.connection = connection
        self.base = clean_url(connection['address'])
        self.secret = secret
        self.session = requests.Session()

    def lights(self):
        raise NotImplementedError

    def set_state(self, light_id, *, on=None, rgb=None, brightness=None, transition=.25):
        raise NotImplementedError


class HomeAssistantProvider(BaseProvider):
    kind = 'home_assistant'

    def __init__(self, connection, secret=''):
        super().__init__(connection, secret)
        if not secret:
            raise ValueError('Enter a Home Assistant long-lived access token.')
        self.session.headers['Authorization'] = 'Bearer ' + secret

    def _api(self, method, path, **kwargs):
        return _request(self.session, method, self.base + '/api/' + path, **kwargs)

    def lights(self):
        result = []
        for state in self._api('GET', 'states'):
            if not state.get('entity_id', '').startswith('light.'):
                continue
            attrs = state.get('attributes', {})
            rgb = attrs.get('rgb_color')
            result.append(Light(state['entity_id'], attrs.get('friendly_name') or state['entity_id'],
                                state.get('state') == 'on', tuple(rgb) if rgb else None,
                                attrs.get('brightness')))
        return result

    def set_state(self, light_id, *, on=None, rgb=None, brightness=None, transition=.25):
        if on is False:
            self._api('POST', 'services/light/turn_off', json={'entity_id': light_id, 'transition': transition})
            return
        payload = {'entity_id': light_id, 'transition': transition}
        if rgb is not None:
            payload['rgb_color'] = list(rgb)
        if brightness is not None:
            payload['brightness'] = max(1, min(255, round(brightness * 2.55)))
        self._api('POST', 'services/light/turn_on', json=payload)


def rgb_to_xy(rgb):
    values = []
    for channel in rgb:
        value = channel / 255
        values.append(((value + .055) / 1.055) ** 2.4 if value > .04045 else value / 12.92)
    r, g, b = values
    x = r * .664511 + g * .154324 + b * .162028
    y = r * .283881 + g * .668433 + b * .047685
    z = r * .000088 + g * .072310 + b * .986039
    total = x + y + z
    return [round(x / total, 4), round(y / total, 4)] if total else [.3127, .329]


class HueProvider(BaseProvider):
    kind = 'hue'

    def __init__(self, connection, secret=''):
        super().__init__(connection, secret)
        if not secret:
            raise ValueError('Connect the Hue Bridge by pressing its link button.')
        self.session.headers['hue-application-key'] = secret

    def _api(self, method, path, **kwargs):
        return _request(self.session, method, self.base + '/clip/v2/resource/' + path, verify=False, **kwargs)

    def lights(self):
        rows = self._api('GET', 'light').get('data', [])
        return [Light(row['id'], row.get('metadata', {}).get('name') or 'Hue light',
                      row.get('on', {}).get('on', False), brightness=round(row.get('dimming', {}).get('brightness', 0)))
                for row in rows]

    def set_state(self, light_id, *, on=None, rgb=None, brightness=None, transition=.25):
        payload = {'dynamics': {'duration': round(transition * 1000)}}
        if on is not None:
            payload['on'] = {'on': bool(on)}
        if rgb is not None:
            payload['color'] = {'xy': rgb_to_xy(rgb)}
        if brightness is not None:
            payload['dimming'] = {'brightness': max(.1, min(100, brightness))}
        self._api('PUT', 'light/' + light_id, json=payload)


class NanoleafProvider(BaseProvider):
    kind = 'nanoleaf'

    def __init__(self, connection, secret=''):
        super().__init__(connection, secret)
        if not secret:
            raise ValueError('Enter or create a Nanoleaf access token.')
        self.api = f'{self.base}/api/v1/{secret}'

    def lights(self):
        row = _request(self.session, 'GET', self.api)
        state = row.get('state', {})
        hue = state.get('hue', {}).get('value', 0) / 360
        sat = state.get('sat', {}).get('value', 0) / 100
        val = state.get('brightness', {}).get('value', 0) / 100
        rgb = tuple(round(v * 255) for v in colorsys.hsv_to_rgb(hue, sat, val))
        return [Light('device', row.get('name') or 'Nanoleaf', state.get('on', {}).get('value', False), rgb,
                      state.get('brightness', {}).get('value'))]

    def set_state(self, light_id, *, on=None, rgb=None, brightness=None, transition=.25):
        state = {}
        if on is not None:
            state['on'] = {'value': bool(on)}
        if rgb is not None:
            h, s, _ = colorsys.rgb_to_hsv(*(v / 255 for v in rgb))
            state.update(hue={'value': round(h * 360)}, sat={'value': round(s * 100)})
        if brightness is not None:
            state['brightness'] = {'value': max(1, min(100, round(brightness))), 'duration': round(transition)}
        _request(self.session, 'PUT', self.api + '/state', json=state)


class WLEDProvider(BaseProvider):
    kind = 'wled'

    def lights(self):
        info = _request(self.session, 'GET', self.base + '/json/info')
        state = _request(self.session, 'GET', self.base + '/json/state')
        color = (state.get('seg') or [{}])[0].get('col', [[0, 0, 0]])[0][:3]
        return [Light('device', info.get('name') or 'WLED', state.get('on', False), tuple(color),
                      round(state.get('bri', 0) / 2.55))]

    def set_state(self, light_id, *, on=None, rgb=None, brightness=None, transition=.25):
        payload = {'transition': max(0, round(transition * 10))}
        if on is not None:
            payload['on'] = bool(on)
        if rgb is not None:
            payload['seg'] = {'col': [list(rgb)]}
        if brightness is not None:
            payload['bri'] = max(1, min(255, round(brightness * 2.55)))
        _request(self.session, 'POST', self.base + '/json/state', json=payload)


PROVIDERS = {provider.kind: provider for provider in
             (HomeAssistantProvider, HueProvider, NanoleafProvider, WLEDProvider)}


def make_provider(connection, secret=''):
    try:
        provider = PROVIDERS[connection['kind']]
    except KeyError as exc:
        raise ValueError('Choose a supported lighting system.') from exc
    return provider(connection, secret)
