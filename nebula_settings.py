"""Validated settings shared by Nebula's interface and sync worker."""
import json
import os
from pathlib import Path
import re
import uuid

from providers import clean_url


def defaults(config):
    config = dict(config)
    if 'connections' not in config and config.get('home_assistant_url'):
        cid = 'home-assistant'
        entity = config.get('entity_id', '')
        config['connections'] = [{'id': cid, 'kind': 'home_assistant', 'name': 'Home Assistant',
                                  'address': config['home_assistant_url']}]
        config['lights'] = [{'connection_id': cid, 'id': entity, 'name': entity, 'sync': True}]
    for key, value in {'theme': 'dark', 'enabled': False, 'onboarding_complete': False,
                       'connections': [], 'lights': [], 'return_mode': 'warm',
                       'return_color': '#FFCD9B', 'warm_kelvin': 3000,
                       'transition_seconds': .25, 'minimum_color_change': 12,
                       'fallback_seconds': 5, 'login': True}.items():
        config.setdefault(key, value)
    return config


def connection_from_input(incoming):
    kind = str(incoming.get('kind', '')).strip()
    if kind not in {'home_assistant', 'hue', 'nanoleaf', 'wled'}:
        raise ValueError('Choose Home Assistant, Philips Hue, Nanoleaf, or WLED.')
    names = {'home_assistant': 'Home Assistant', 'hue': 'Philips Hue',
             'nanoleaf': 'Nanoleaf', 'wled': 'WLED'}
    return {'id': str(incoming.get('id') or uuid.uuid4().hex[:12]), 'kind': kind,
            'name': str(incoming.get('name') or names[kind]).strip()[:60],
            'address': clean_url(str(incoming.get('address', '')))}


def edited(config, incoming):
    updated = defaults(config)
    if incoming.get('theme') not in ('dark', 'light'):
        raise ValueError('Choose a valid appearance.')
    if incoming.get('return_mode') not in ('warm', 'custom', 'keep'):
        raise ValueError('Choose a valid return colour.')
    color = str(incoming.get('return_color', '#FFCD9B')).strip()
    if not re.fullmatch(r'#[0-9a-fA-F]{6}', color):
        raise ValueError('Enter a six-digit colour, such as #FFCD9B.')
    try:
        kelvin, fade = int(incoming['warm_kelvin']), float(incoming['transition_seconds'])
    except (ValueError, TypeError, KeyError):
        raise ValueError('Choose a valid warmth and fade speed.') from None
    if not 2200 <= kelvin <= 4500 or not .1 <= fade <= 2:
        raise ValueError('Warmth must be 2200–4500 K and fade 0.1–2 seconds.')
    updated.update(theme=incoming['theme'], return_mode=incoming['return_mode'],
                   return_color=color.upper(), warm_kelvin=kelvin,
                   transition_seconds=fade, login=bool(incoming.get('login')))
    return updated


def save_config(path, config):
    path = Path(path)
    temporary = path.with_suffix('.pending')
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, 'w') as handle:
        json.dump(config, handle, indent=2)
        handle.write('\n')
    os.replace(temporary, path)
    path.chmod(0o600)
