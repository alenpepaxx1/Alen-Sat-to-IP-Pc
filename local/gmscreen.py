# Copyright © 2026 Alen Pepa.
"""G-MScreen ALi variant. Protocol facts: gabonator/alifeng.js (2017).
Independent implementation; no guessed write IDs or universal compatibility claim.
"""
import json
import socket
import time
import zlib
from urllib.parse import urlencode

LIMIT = 1024 * 1024


def frame(value):
    data = value.encode('utf-8') if isinstance(value, str) else json.dumps(value, separators=(',', ':')).encode('utf-8')
    if len(data) > LIMIT:
        raise ValueError('G-MScreen request is too large.')
    return b'Start' + f'{len(data):07d}'.encode() + b'End' + data


def exact(sock, size):
    chunks = bytearray()
    while len(chunks) < size:
        part = sock.recv(size - len(chunks))
        if not part:
            raise ConnectionError('Receiver closed the G-MScreen connection.')
        chunks.extend(part)
    return bytes(chunks)


def decode_payload(data):
    decompressor = zlib.decompressobj()
    raw = decompressor.decompress(data, LIMIT + 1)
    if len(raw) > LIMIT or not decompressor.eof or decompressor.unused_data:
        raise ValueError('Invalid or oversized G-MScreen response.')
    return json.loads(raw.decode('utf-8'))


class Adapter:
    def __init__(self):
        self.sock = None
        self.info = {}
        self.target = None
        self.models = {}
        self.last_checked = 0

    def close(self):
        if self.sock:
            self.sock.close()
        self.sock = None
        self.info = {}
        self.models = {}

    def request(self, value):
        if not self.sock:
            raise ConnectionError('G-MScreen is disconnected.')
        try:
            self.sock.sendall(frame(value))
            header = exact(self.sock, 16)
            if header[:4] != b'GCDH':
                raise ValueError('Unsupported G-MScreen response framing.')
            size = int.from_bytes(header[4:6], 'little')
            if not size:
                return None  # transport acknowledgement is NOT an operation acknowledgement
            return decode_payload(exact(self.sock, size))
        except Exception:
            self.close()
            raise

    def configure(self, target):
        self.close()
        self.target = dict(target)
        try:
            self.sock = socket.create_connection((target['host'], target['port']), timeout=3)
            self.sock.settimeout(3)
            self.sock.sendall(frame('<?xml version="1.0" encoding="UTF-8" standalone="yes" ?><Command request="998" />'))
            hello = exact(self.sock, 108)
            if hello[:2] != b'[[':
                raise ValueError('This receiver does not use the supported G-MScreen ALi handshake.')
            self.refresh_info()
        except Exception:
            self.close()
            raise

    def refresh_info(self):
        result = self.request({'request': '15'})
        if not isinstance(result, list) or not result or not isinstance(result[0], dict):
            self.close()
            raise ValueError('Receiver did not return G-MScreen device information.')
        info = result[0]
        try:
            count = int(info['ChannelNum'])
            if not 0 <= count <= 30000 or not isinstance(info['ProductName'], str) or not info['ProductName']:
                raise ValueError()
        except (KeyError, TypeError, ValueError):
            self.close()
            raise ValueError('Unsupported G-MScreen device information.')
        self.info = info
        self.last_checked = time.monotonic()

    def status(self):
        if self.sock and time.monotonic() - self.last_checked > 5:
            try:
                self.refresh_info()
            except Exception:
                pass
        return {'receiver': {'connected': self.sock is not None, 'name': self.info.get('ProductName', 'G-MScreen'),
                'protocol': 'G-MScreen ALi (device compatibility unverified)', 'firmware': str(self.info.get('SoftwareVersion', ''))},
                'capabilities': ['stream'] if self.sock else []}

    def channels(self):
        self.refresh_info()
        models = {}
        self.models = {}
        deadline = time.monotonic() + 45
        for start in range(0, int(self.info['ChannelNum']), 100):
            if time.monotonic() > deadline:
                raise TimeoutError('Channel loading exceeded 45 seconds.')
            rows = self.request({'request': '0', 'FromIndex': str(start), 'ToIndex': str(min(start + 99, int(self.info['ChannelNum']) - 1))})
            if not isinstance(rows, list):
                raise ValueError('Receiver channel-list format is unsupported.')
            for row in rows:
                if not isinstance(row, dict) or not isinstance(row.get('ServiceName'), str) or not str(row.get('ServiceID', '')).isdigit():
                    raise ValueError('Receiver returned an unsupported channel entry.')
                key = str(row['ServiceID'])
                if key in models:
                    raise ValueError('Receiver returned duplicate channel identifiers.')
                models[key] = row
        if len(models) != int(self.info['ChannelNum']):
            raise ValueError('Receiver returned an incomplete channel list; this firmware may use another protocol variant.')
        self.models = models
        # Unknown lock flags fail closed for streaming. They are not silently treated as unlocked.
        return {'channels': [{'id': key, 'name': row['ServiceName'], 'category': 'Radio' if str(row.get('Radio')) == '1' else 'TV',
                'favorite': False, 'locked': str(row.get('Lock', row.get('Locked', 'unknown'))) != '0',
                'quality': 'HD' if str(row.get('HD')) == '1' else 'SD'} for key, row in models.items()]}

    def satip_source(self, channel_id, port=554):
        row = self.models.get(channel_id)
        if not row:
            raise ValueError('Load the receiver channel list first.')
        if str(row.get('Lock', row.get('Locked', 'unknown'))) != '0':
            raise ValueError('Channel lock is enabled or unverified. Unlock on the receiver first.')
        if str(row.get('Scramble', 'unknown')) != '0':
            raise ValueError('This adapter streams free-to-air channels only; encrypted streams are unsupported.')
        transponders = self.request({'request': '24'})
        if not isinstance(transponders, list):
            raise ValueError('Unsupported transponder response.')
        tp = next((t for t in transponders if isinstance(t, dict) and str(t.get('TPIndex')) == str(int(channel_id[4:9]))), None)
        if not tp:
            raise ValueError('Receiver did not return the channel transponder.')
        audio = row.get('AudioArray') or []
        apid = int(audio[0]['PID']) if audio else 8191
        pids = [0, int(row['VideoPID']), apid, int(row['TTXPID']), int(row['PMTPID'])]
        if any(not 0 <= p <= 8191 for p in pids):
            raise ValueError('Invalid receiver PID.')
        params = {'alisatid': int(tp['SatIndex']), 'freq': int(tp['Freq']), 'pol': 'v' if int(tp['POL']) else 'h',
            'msys': 'dvbs' if int(row['ModulationSystem']) == 0 else 'dvbs2',
            'mtype': 'qpsk' if int(row['ModulationType']) == 0 else '8psk', 'ro': f"{int(row['RollOff']) / 100:.2f}",
            'plts': 'off' if int(row['PilotTones']) == 0 else 'on', 'sr': int(tp['SR']), 'fec': str(tp['FEC']),
            'camode': 0, 'vpid': int(row['VideoPID']), 'apid': apid, 'ttxpid': int(row['TTXPID']), 'subtpid': 0,
            'pmt': int(row['PMTPID']), 'prognumber': int(channel_id[-4:]), 'pids': ','.join(map(str, dict.fromkeys(pids)))}
        return {'host': self.target['host'], 'port': port, 'query': urlencode(params), 'program': int(channel_id[-4:])}
