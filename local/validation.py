# Copyright © 2026 Alen Pepa.
"""Strict input/output boundaries shared by the local HTTP gateway.
Adapters remain responsible for device authentication and protocol acknowledgements.
"""
from datetime import datetime, timezone
import math
from urllib.parse import urlparse

REMOTE_KEYS = set('UP DOWN LEFT RIGHT OK MENU BACK EXIT INFO MUTE EPG FAV POWER VOL+ VOL- CH+ CH- RED GREEN YELLOW BLUE'.split()) | set('0123456789')
MEDIA_TYPES = {
    'image/jpeg', 'image/png', 'image/gif', 'image/webp', 'image/avif', 'image/bmp',
    'video/mp4', 'video/webm', 'video/mpeg', 'video/mp2t', 'video/quicktime', 'video/x-matroska',
    'audio/mpeg', 'audio/mp4', 'audio/ogg', 'audio/wav', 'audio/x-wav', 'audio/flac', 'audio/aac',
}


def text(value, name, limit=160):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f'Invalid {name}.')
    return value


def integer(value, name, low, high):
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ValueError(f'{name} must be a whole number from {low} to {high}.')
    return value


def settings(value):
    if not isinstance(value, dict):
        raise ValueError('Invalid settings object.')
    if 'sleep' in value and str(value['sleep']) not in ('0', '15', '30', '60', '120'):
        raise ValueError('Unsupported sleep timer.')
    for key in ('parental', 'screenLock'):
        if key in value and type(value[key]) is not bool:
            raise ValueError(f'{key} must be a boolean.')
    return value


def timer(value, future=False):
    if not isinstance(value, dict):
        raise ValueError('Invalid timer.')
    for key, limit in [('id', 160), ('title', 120), ('channelId', 160)]:
        text(value.get(key), 'timer ' + key, limit)
    start = datetime.fromisoformat(text(value.get('start'), 'timer start').replace('Z', '+00:00'))
    if start.tzinfo is None:
        raise ValueError('Timer start must include a timezone offset or Z.')
    if future and start <= datetime.now(timezone.utc):
        raise ValueError('Timer start must be in the future.')
    integer(value.get('duration'), 'Duration', 1, 1440)
    if value.get('type') not in ('Switch channel', 'Record'):
        raise ValueError('Invalid timer type.')
    return value


def command(name, body):
    if not isinstance(body, dict):
        raise ValueError('Expected a command object.')
    if name in ('channel_update', 'channel_delete', 'channel_tune', 'timer_delete', 'stream'):
        text(body.get('id'), 'ID')
    if name == 'channel_update':
        patch = body.get('patch')
        if not isinstance(patch, dict) or not patch or not set(patch) <= {'name', 'favorite', 'locked'}:
            raise ValueError('Invalid channel patch.')
        if 'name' in patch:
            text(patch['name'], 'channel name', 160)
        for key in ('favorite', 'locked'):
            if key in patch and type(patch[key]) is not bool:
                raise ValueError(f'{key} must be a boolean.')
    elif name == 'channel_order':
        ids = body.get('ids')
        if not isinstance(ids, list) or len(ids) > 30000:
            raise ValueError('Invalid channel order.')
        for value in ids:
            text(value, 'channel ID')
        if len(set(ids)) != len(ids):
            raise ValueError('Duplicate channel IDs in channel order.')
    elif name == 'remote':
        if body.get('key') not in REMOTE_KEYS:
            raise ValueError('Unsupported remote key.')
    elif name == 'timer_save':
        timer(body, future=True)
    elif name == 'settings_save':
        if not set(body) <= {'sleep', 'parental', 'screenLock'}:
            raise ValueError('Unsupported settings fields.')
        settings(body)
    elif name == 'password':
        for key in ('current', 'next'):
            value = text(body.get(key), 'PIN', 8)
            if not value.isascii() or not value.isdigit() or len(value) < 4:
                raise ValueError('PIN must contain 4–8 ASCII digits.')
    elif name == 'power':
        if body.get('mode') not in ('on', 'standby'):
            raise ValueError('Invalid power mode.')
    elif name == 'factory_reset' and body.get('confirmation') != 'RESET':
        raise ValueError('Factory reset confirmation is required.')
    return body


def status(value):
    if not isinstance(value, dict) or not isinstance(value.get('receiver'), dict):
        raise ValueError('Invalid adapter status.')
    if type(value['receiver'].get('connected')) is not bool:
        raise ValueError('Receiver connected status must be a boolean.')
    caps = value.get('capabilities')
    if not isinstance(caps, list) or not all(isinstance(c, str) for c in caps):
        raise ValueError('Invalid adapter capabilities.')
    return value


def response(name, value):
    if not isinstance(value, dict):
        raise ValueError('Invalid adapter response.')
    if name == 'channels':
        channels = value.get('channels')
        if not isinstance(channels, list) or len(channels) > 30000:
            raise ValueError('Invalid receiver channel list.')
        ids = set()
        for channel in channels:
            if not isinstance(channel, dict):
                raise ValueError('Invalid channel.')
            identifier = text(channel.get('id'), 'channel ID')
            text(channel.get('name'), 'channel name')
            if identifier in ids:
                raise ValueError('Duplicate channel IDs.')
            ids.add(identifier)
            for key in ('locked', 'favorite'):
                if key in channel and type(channel[key]) is not bool:
                    raise ValueError('Invalid channel flag.')
    elif name == 'timers':
        if not isinstance(value.get('timers'), list):
            raise ValueError('Invalid receiver timer list.')
        ids = set()
        for item in value['timers']:
            timer(item)
            if item['id'] in ids:
                raise ValueError('Duplicate timer IDs.')
            ids.add(item['id'])
    elif name == 'settings':
        settings(value.get('settings'))
    elif name == 'signal':
        for key in ('snr', 'strength', 'quality'):
            item = value.get(key)
            if item is not None and (isinstance(item, bool) or not isinstance(item, (int, float)) or not math.isfinite(item)):
                raise ValueError('Invalid signal measurement.')
        for key in ('strength', 'quality'):
            if value.get(key) is not None and not 0 <= value[key] <= 100:
                raise ValueError('Signal percentage outside 0–100.')
        if value.get('locked') is not None and type(value['locked']) is not bool:
            raise ValueError('Invalid receiver lock status.')
    elif name == 'epg':
        if not isinstance(value.get('programmes'), list):
            raise ValueError('Invalid EPG list.')
        for item in value['programmes']:
            if not isinstance(item, dict):
                raise ValueError('Invalid EPG entry.')
            text(item.get('channelId'), 'EPG channel ID')
            text(item.get('title'), 'EPG title', 512)
            start = datetime.fromisoformat(text(item.get('start'), 'EPG start').replace('Z', '+00:00'))
            if start.tzinfo is None:
                raise ValueError('EPG start must include a timezone.')
    elif name == 'stream':
        url = urlparse(text(value.get('url'), 'stream URL', 8192))
        if not ((url.scheme in ('http', 'https') and url.hostname and not url.username and not url.password) or
                (not url.scheme and not url.netloc and url.path.startswith('/'))):
            raise ValueError('A browser-compatible HTTP(S) stream URL is required.')
    return value
