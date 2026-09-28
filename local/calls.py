# Copyright © 2026 Alen Pepa.
"""Native-companion pairing and bounded, idempotent call-state delivery."""
import hmac
import secrets
import threading
import time


class Calls:
    def __init__(self):
        self.lock = threading.Lock()
        self.code = None
        self.code_expires = 0
        self.attempts = 0
        self.devices = {}
        self.events = []
        self.revision = 0

    def pair(self):
        with self.lock:
            self.code = f'{secrets.randbelow(100000000):08d}'
            self.code_expires = time.monotonic() + 120
            self.attempts = 0
            return {'code': self.code, 'expiresIn': 120}

    def claim(self, code):
        with self.lock:
            self.attempts += 1
            if (self.attempts > 8 or not self.code or time.monotonic() > self.code_expires or
                    not isinstance(code, str) or not hmac.compare_digest(code.encode(), self.code.encode())):
                raise ValueError('Pairing code invalid, expired or locked. Generate a new code in Alen STB.')
            self.code = None
            self.devices = {}  # one companion; pairing replaces and revokes the previous one
            token = secrets.token_urlsafe(32)
            self.devices[token] = {'expires': time.monotonic() + 12*3600, 'seq': 0, 'lastSeen': None}
            return {'token': token, 'expiresIn': 12*3600}

    def event(self, token, body):
        with self.lock:
            device = self.devices.get(token)
            if not device or device['expires'] < time.monotonic():
                raise PermissionError('Phone pairing expired. Pair again.')
            seq = body.get('sequence')
            if type(seq) is not int or not 1 <= seq <= 2**31:
                raise ValueError('Invalid event sequence.')
            if body.get('state') not in ('ringing', 'connected', 'ended'):
                raise ValueError('Invalid call state.')
            call_id = body.get('callId')
            if not isinstance(call_id, str) or not 1 <= len(call_id) <= 64 or not all(c.isalnum() or c == '-' for c in call_id):
                raise ValueError('Invalid call ID.')
            if seq <= device['seq']:
                return {'ok': True, 'duplicate': True}
            device['seq'] = seq
            device['lastSeen'] = time.time()
            self.revision += 1
            event = {'id': self.revision, 'callId': call_id, 'state': body['state'], 'at': time.time()}
            self.events.append(event)
            self.events = self.events[-32:]
            return {'ok': True}

    def snapshot(self, after=0):
        with self.lock:
            return {'paired': any(d['expires'] > time.monotonic() for d in self.devices.values()),
                    'revision': self.revision, 'events': [e for e in self.events if e['id'] > after and time.time() - e['at'] < 60]}

    def revoke(self):
        with self.lock:
            self.devices.clear()
            self.code = None
            self.events.clear()
