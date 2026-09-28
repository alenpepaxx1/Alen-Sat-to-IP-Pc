# Copyright © 2026 Alen Pepa.
"""SAT>IP RTSP/UDP receiver and bounded live MPEG-TS -> fragmented MP4 gateway."""
import ipaddress
import os
from pathlib import Path
import re
import secrets
import shutil
import socket
import subprocess
import threading
import time
from urllib.parse import urlencode


def private_host(host):
    ip = ipaddress.ip_address(host)
    if ip.version != 4 or not any(ip in ipaddress.ip_network(n) for n in ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16')):
        raise ValueError('Enter a private LAN IPv4 address.')
    return str(ip)


def number(value, name, low, high):
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ValueError(f'Invalid {name}: expected {low}–{high}.')
    return value


def source(body):
    host = private_host(body.get('host', ''))
    port = number(body.get('port', 554), 'RTSP port', 1, 65535)
    params = {'src': number(body.get('src', 1), 'source', 1, 255),
              'freq': number(body.get('freq'), 'frequency in MHz', 300, 13000),
              'sr': number(body.get('sr'), 'symbol rate', 1, 60000)}
    for key, allowed in [('pol', ('h', 'v', 'l', 'r')), ('msys', ('dvbs', 'dvbs2'))]:
        if body.get(key) not in allowed:
            raise ValueError('Invalid SAT>IP ' + key)
        params[key] = body[key]
    pids = str(body.get('pids', 'all'))
    if pids != 'all':
        if not re.fullmatch(r'\d{1,4}(,\d{1,4}){0,63}', pids) or any(int(p) > 8191 for p in pids.split(',')):
            raise ValueError('PIDs must be all or a comma-separated list from 0 to 8191.')
    params['pids'] = pids
    program = number(body.get('program', 0), 'programme number', 0, 65535)
    return {'host': host, 'port': port, 'query': urlencode(params), 'program': program}


def rtp_payload(packet):
    if len(packet) < 12 or packet[0] >> 6 != 2 or packet[1] & 127 != 33:
        raise ValueError('Not an MPEG-TS RTP packet.')
    offset = 12 + (packet[0] & 15) * 4
    if packet[0] & 16:
        if len(packet) < offset + 4:
            raise ValueError('Truncated RTP extension.')
        offset += 4 + int.from_bytes(packet[offset+2:offset+4], 'big') * 4
    end = len(packet)
    if packet[0] & 32:
        padding = packet[-1]
        if not padding or padding > end - offset:
            raise ValueError('Invalid RTP padding.')
        end -= padding
    payload = packet[offset:end]
    if not payload or len(payload) % 188 or any(payload[i] != 0x47 for i in range(0, len(payload), 188)):
        raise ValueError('Invalid MPEG-TS payload.')
    return payload


def ffmpeg_path():
    bundled = Path(__file__).parent.parent / 'bin' / ('ffmpeg.exe' if os.name == 'nt' else 'ffmpeg')
    return str(bundled) if bundled.is_file() else shutil.which('ffmpeg')


def ffmpeg_args(executable, program=0):
    mapping = ['-map', f'0:p:{program}:v:0?', '-map', f'0:p:{program}:a:0?'] if program else ['-map', '0:v:0?', '-map', '0:a:0?']
    return [executable, '-hide_banner', '-loglevel', 'error', '-nostdin', '-probesize', '2000000', '-analyzeduration', '2000000',
            '-f', 'mpegts', '-i', 'pipe:0', *mapping, '-sn', '-dn', '-c:v', 'libx264', '-preset', 'ultrafast',
            '-tune', 'zerolatency', '-threads', '2', '-vf', 'scale=w=min(1280\\,iw):h=-2', '-pix_fmt', 'yuv420p',
            '-g', '50', '-c:a', 'aac', '-b:a', '128k', '-ac', '2', '-f', 'mp4',
            '-movflags', 'frag_keyframe+empty_moov+default_base_moof', '-frag_duration', '500000', 'pipe:1']


def write_all(pipe, payload):
    """Raw subprocess pipes may accept only part of a transport packet."""
    remaining = memoryview(payload)
    while remaining:
        written = pipe.write(remaining)
        if not written:
            raise BrokenPipeError('FFmpeg input closed before the packet was written.')
        remaining = remaining[written:]


class RTSP:
    def __init__(self, config):
        self.host = config['host']
        self.base = f"rtsp://{self.host}:{config['port']}"
        self.sock = socket.create_connection((self.host, config['port']), timeout=4)
        self.sock.settimeout(4)
        self.buffer = b''
        self.cseq = 0
        self.session = None
        self.url = self.base + '/?' + config['query']
        self.lock = threading.Lock()
        self.timeout = 30
        self.rtp = None
        self.rtcp = None
        try:
            # SAT>IP requires an even RTP port paired with the next RTCP port.
            for _ in range(40):
                a = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                a.bind((self.sock.getsockname()[0], 0))
                port = a.getsockname()[1]
                if port % 2 or port == 65535:
                    a.close()
                    continue
                b = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                try:
                    b.bind((self.sock.getsockname()[0], port + 1))
                except OSError:
                    a.close(); b.close()
                    continue
                self.rtp, self.rtcp = a, b
                break
            if self.rtp is None:
                raise OSError('No UDP port pair is available for SAT>IP.')
            self.rtp.settimeout(1)
            headers = self.request('SETUP', self.url, {'Transport': f'RTP/AVP;unicast;client_port={port}-{port+1}'})
            session = headers.get('session', '')
            session_id = session.split(';')[0]
            stream_id = headers.get('com.ses.streamid', '')
            if not re.fullmatch(r'[A-Za-z0-9_.-]{1,128}', session_id) or not stream_id.isdigit():
                raise ValueError('SAT>IP server did not return a session and stream ID.')
            self.session = session_id
            match = re.search(r'timeout=(\d+)', session)
            self.timeout = max(2, min(120, int(match[1]))) if match else 30
            self.url = self.base + '/stream=' + stream_id
            self.request('PLAY', self.url)
        except Exception:
            self.close()
            raise

    def request(self, method, url, headers=None):
        with self.lock:
            self.cseq += 1
            fields = {'CSeq': str(self.cseq), 'User-Agent': 'AlenSTB/0.7', **(headers or {})}
            if self.session:
                fields['Session'] = self.session
            self.sock.sendall((f'{method} {url} RTSP/1.0\r\n' + ''.join(f'{k}: {v}\r\n' for k, v in fields.items()) + '\r\n').encode('ascii'))
            while b'\r\n\r\n' not in self.buffer:
                part = self.sock.recv(4096)
                if not part:
                    raise ConnectionError('SAT>IP server closed RTSP.')
                self.buffer += part
                if len(self.buffer) > 65536:
                    raise ValueError('RTSP headers are too large.')
            head, self.buffer = self.buffer.split(b'\r\n\r\n', 1)
            lines = head.decode('ascii').split('\r\n')
            if not re.match(r'^RTSP/1\.0 200(?: |$)', lines[0]):
                raise ValueError('SAT>IP rejected ' + method + ': ' + lines[0][:80])
            result = {k.lower(): v.strip() for k, v in (line.split(':', 1) for line in lines[1:] if ':' in line)}
            if result.get('cseq') != str(self.cseq):
                raise ValueError('RTSP response sequence mismatch.')
            size = int(result.get('content-length', 0))
            if not 0 <= size <= 65536:
                raise ValueError('RTSP body is too large.')
            while len(self.buffer) < size:
                part = self.sock.recv(min(4096, size - len(self.buffer)))
                if not part:
                    raise ConnectionError('Truncated RTSP response.')
                self.buffer += part
            self.buffer = self.buffer[size:]
            return result

    def close(self):
        if self.session:
            try:
                self.request('TEARDOWN', self.url)
            except Exception:
                pass
            self.session = None
        self.sock.close()
        for sock in (self.rtp, self.rtcp):
            if sock:
                sock.close()


class Stream:
    def __init__(self, config):
        executable = ffmpeg_path()
        if not executable:
            raise ValueError('FFmpeg is missing. Install it on PATH or place ffmpeg.exe in the bin folder.')
        self.rtsp = RTSP(config)
        self.stopped = threading.Event()
        self.error = ''
        self.started = time.monotonic()
        self.proc = None
        try:
            self.proc = subprocess.Popen(ffmpeg_args(executable, config.get('program', 0)), stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0)
            threading.Thread(target=self.feed, daemon=True).start()
            threading.Thread(target=self.keepalive, daemon=True).start()
            threading.Thread(target=self.read_errors, daemon=True).start()
        except Exception:
            self.close()
            raise

    def feed(self):
        last = time.monotonic()
        try:
            while not self.stopped.is_set():
                try:
                    packet, peer = self.rtsp.rtp.recvfrom(65536)
                except socket.timeout:
                    if time.monotonic() - last > 15:
                        raise TimeoutError('No MPEG-TS packets received for 15 seconds.')
                    continue
                if peer[0] != self.rtsp.host:
                    continue
                try:
                    payload = rtp_payload(packet)
                except ValueError:
                    continue
                write_all(self.proc.stdin, payload)
                last = time.monotonic()
        except Exception as error:
            if not self.stopped.is_set():
                self.error = str(error)[:250]
        finally:
            self.close()

    def keepalive(self):
        interval = max(1, self.rtsp.timeout / 2)
        try:
            while not self.stopped.wait(interval):
                if time.monotonic() - self.started > 4 * 3600:
                    raise TimeoutError('The four-hour stream session ended. Start playback again.')
                self.rtsp.request('OPTIONS', self.rtsp.url)
        except Exception as error:
            self.error = str(error)[:250]
            self.close()

    def read_errors(self):
        try:
            while True:
                chunk = self.proc.stderr.read(1024)
                if not chunk:
                    break
                self.error = (self.error + chunk.decode('utf-8', 'replace'))[-500:]
        except (ValueError, OSError):
            pass

    def close(self):
        if self.stopped.is_set():
            return
        self.stopped.set()
        if self.proc:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=2)
        self.rtsp.close()
        if self.proc:
            for pipe in (self.proc.stdin, self.proc.stdout, self.proc.stderr):
                try:
                    pipe.close()
                except (OSError, ValueError):
                    pass


class Manager:
    def __init__(self):
        self.lock = threading.Lock()
        self.tickets = {}
        self.stream = None
        self.active_key = None

    def ticket(self, config):
        if not ffmpeg_path():
            raise ValueError('Install FFmpeg on PATH, or place ffmpeg.exe in the bin folder, to watch SAT>IP.')
        with self.lock:
            self.tickets = {k: v for k, v in self.tickets.items() if v[1] > time.monotonic()}
            if len(self.tickets) >= 8:
                raise ValueError('Too many pending streams. Wait 30 seconds.')
            key = secrets.token_urlsafe(32)
            self.tickets[key] = (config, time.monotonic() + 30)
            return key

    def start(self, key):
        with self.lock:
            item = self.tickets.pop(key, None)
            if not item or item[1] < time.monotonic():
                raise ValueError('Playback link expired. Start playback again.')
            if self.stream and not self.stream.stopped.is_set():
                raise ValueError('Another stream is playing. Close it first.')
            self.stream = Stream(item[0])
            self.active_key = key
            return self.stream

    def stop(self, key):
        with self.lock:
            self.tickets.pop(key, None)
            if self.stream and key == self.active_key:
                self.stream.close()

    def close(self):
        with self.lock:
            self.tickets.clear()
            if self.stream:
                self.stream.close()
