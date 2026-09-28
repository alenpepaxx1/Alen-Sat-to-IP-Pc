#!/usr/bin/env python3
# Copyright © 2026 Alen Pepa.
"""Alen STB local gateway. Python 3.10+, standard library only.
Provides local app hosting, UPnP discovery and DLNA media sending.
Receiver control requires a model-specific adapter; none is assumed.
"""
import argparse
import webbrowser
import validation
import satip
from calls import Calls
from runtime_identity import VERSION, INSTALLATION_ID
import hmac
import importlib.util
import ipaddress
import json
import mimetypes
import os
from pathlib import Path
import secrets
import socket
from socket import create_connection as tcp_connection
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, urljoin, parse_qs, unquote
from urllib.request import Request, build_opener, HTTPRedirectHandler, ProxyHandler
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / 'dist'
TOKEN = secrets.token_urlsafe(32)
DEVICES = {}
MEDIA = {}
MEDIA_RESERVED = 0
MEDIA_LIMIT = 500 * 1024 * 1024
LOCK = threading.Lock()
ADAPTER = None
ARGS = None
TARGET = None
STREAMS = satip.Manager()
CALLS = Calls()
TMP = tempfile.TemporaryDirectory(prefix='alen-stb-')
MAX_UPLOAD = 100 * 1024 * 1024

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('Redirects are not allowed for device requests.')

OPENER = build_opener(ProxyHandler({}), NoRedirect())

def private_url(url, host=None):
    u = urlparse(url)
    if u.scheme != 'http' or u.username or u.password:
        raise ValueError('Only local HTTP device endpoints are supported.')
    ip = ipaddress.ip_address(u.hostname or '')
    if ip.version != 4 or not ip.is_private or ip.is_loopback or ip.is_multicast or ip.is_unspecified:
        raise ValueError('Device endpoint must use a private LAN IPv4 address.')
    if host and u.hostname != host:
        raise ValueError('Device control URL must match the discovery host.')
    return u

def local_fetch(url, data=None, headers=None, limit=512*1024):
    private_url(url)
    with OPENER.open(Request(url, data=data, headers=headers or {}), timeout=4) as r:
        raw = r.read(limit + 1)
        if len(raw) > limit:
            raise ValueError('Device response is too large.')
        return raw

def parse_devices(location, raw):
    host = private_url(location).hostname
    if len(raw) > 512 * 1024:
        raise ValueError('Device description is too large.')
    root = ET.fromstring(raw)
    ns = {'d': 'urn:schemas-upnp-org:device-1-0'}
    declared_base = root.findtext('d:URLBase', '', ns).strip()
    base = declared_base or location
    private_url(base, host)
    entries = []
    for dev in root.findall('.//d:device', ns):
        entry = {'id': dev.findtext('d:UDN', '', ns) or location,
                 'name': dev.findtext('d:friendlyName', 'Unknown UPnP device', ns),
                 'type': dev.findtext('d:deviceType', '', ns), 'host': host,
                 'satip': ':SatIPServer:' in dev.findtext('d:deviceType', '', ns)}
        for service in dev.findall('d:serviceList/d:service', ns):
            service_type = service.findtext('d:serviceType', '', ns)
            if ':AVTransport:' in service_type:
                path = service.findtext('d:controlURL', '', ns).strip()
                if not path:
                    continue
                control = urljoin(base, path)
                private_url(control, host)
                entry.update(control=control, service=service_type)
        entries.append(entry)
    return entries


def discover():
    locations = set()
    msg = ('M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\n'
           'MAN: "ssdp:discover"\r\nMX: 1\r\nST: ssdp:all\r\n\r\n').encode()
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP) as sock:
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        sock.settimeout(.35)
        sock.sendto(msg, ('239.255.255.250', 1900))
        end = time.monotonic() + 2.5
        while time.monotonic() < end and len(locations) < 24:
            try:
                data, source = sock.recvfrom(8192)
            except socket.timeout:
                continue
            headers = {}
            for line in data.decode('utf-8', 'replace').split('\r\n')[1:]:
                key, sep, value = line.partition(':')
                if sep:
                    headers[key.lower()] = value.strip()
            location = headers.get('location')
            if location:
                try:
                    private_url(location, source[0])
                    locations.add(location)
                except ValueError:
                    pass
    found = {}
    # Fetch in parallel to bound discovery latency when devices fail to respond.
    from concurrent.futures import ThreadPoolExecutor, as_completed
    def inspect(location):
        try:
            for entry in parse_devices(location, local_fetch(location)):
                with LOCK:
                    previous = found.get(entry['id'], {})
                    found[entry['id']] = {**previous, **entry}
        except Exception:
            pass
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(inspect, locations))
    with LOCK:
        DEVICES.clear()
        DEVICES.update(found)
    return {'devices': [{k: v for k, v in d.items() if k not in ('control', 'service')}
                        for d in found.values()]}

def soap(device, action, fields):
    body = (f'<?xml version="1.0"?><s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
            f's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"><s:Body>'
            f'<u:{action} xmlns:u="{escape(device["service"])}">' +
            ''.join(f'<{k}>{escape(str(v))}</{k}>' for k, v in fields.items()) +
            f'</u:{action}></s:Body></s:Envelope>').encode()
    response = local_fetch(device['control'], body, {'Content-Type': 'text/xml; charset="utf-8"',
                'SOAPACTION': f'"{device["service"]}#{action}"'})
    parsed = ET.fromstring(response)
    if any(node.tag.rsplit('}', 1)[-1] == 'Fault' for node in parsed.iter()):
        raise ValueError('TV returned a SOAP fault.')
    if not any(node.tag.rsplit('}', 1)[-1] == action + 'Response' for node in parsed.iter()):
        raise ValueError('TV did not acknowledge the requested DLNA action.')

def validate_target(body):
    host = str(body.get('host', '')).strip()
    ip = ipaddress.ip_address(host)
    allowed = any(ip in ipaddress.ip_network(net) for net in ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16')) if ip.version == 4 else False
    if not allowed:
        raise ValueError('Enter the receiver private LAN IPv4 address (192.168.x.x, 10.x.x.x or 172.16–31.x.x).')
    port = body.get('port')
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError('Port must be a whole number from 1 to 65535.')
    return {'host': str(ip), 'port': port}


def probe_target(target):
    started = time.monotonic()
    try:
        with tcp_connection((target['host'], target['port']), timeout=2.5):
            pass
        return {**target, 'reachable': True, 'latencyMs': round((time.monotonic()-started)*1000),
                'protocolVerified': False, 'message': 'TCP connection accepted. This does not verify G-MScreen compatibility.'}
    except OSError:
        return {**target, 'reachable': False, 'protocolVerified': False,
                'message': 'No TCP connection. The port may be closed, filtered, offline or UDP-only.'}


GET_METHODS = {'/api/channels': 'channels', '/api/timers': 'timers', '/api/settings': 'settings',
               '/api/epg': 'epg', '/api/signal': 'signal'}
POST_METHODS = {'/api/channels/update': 'channel_update', '/api/channels/delete': 'channel_delete',
                '/api/channels/order': 'channel_order', '/api/channels/tune': 'channel_tune',
                '/api/timers/save': 'timer_save', '/api/timers/delete': 'timer_delete',
                '/api/settings': 'settings_save', '/api/remote': 'remote', '/api/stream': 'stream',
                '/api/password': 'password', '/api/power': 'power', '/api/factory-reset': 'factory_reset'}

class Handler(BaseHTTPRequestHandler):
    server_version = 'AlenSTB/' + VERSION

    def setup(self):
        super().setup()
        self.connection.settimeout(15)
    def log_message(self, fmt, *args):
        # Never print URLs, which may contain private media identifiers.
        pass

    def bootstrap(self):
        # Only a page served by this exact origin to the local computer may bootstrap.
        # Hosted pages and LAN clients must still use explicit token authentication.
        origin = self.headers.get('Origin')
        own_origin = 'http://' + self.headers.get('Host', '')
        fetch_site = self.headers.get('Sec-Fetch-Site')
        local_peer = ipaddress.ip_address(self.client_address[0]).is_loopback
        same_origin = origin == own_origin or (origin is None and fetch_site == 'same-origin')
        if (not local_peer or not self.valid_host() or not same_origin or
                fetch_site not in (None, 'same-origin') or self.headers.get('X-Alen-Bootstrap') != '1'):
            self.reply(403, {'error': 'Automatic connection is available only in the app opened locally on this computer.'})
            return
        self.reply(200, {'protocol': 'alen-stb-bridge-v1', 'token': TOKEN, 'target': TARGET,
                         'bridge': own_origin, 'automatic': True, 'version': VERSION, 'installationId': INSTALLATION_ID,
                         'lanAvailable': ARGS.bind == '0.0.0.0' and bool(ARGS.lan_ip)})

    def allowed_origin(self):
        origin = self.headers.get('Origin')
        return not origin or origin in ARGS.origins

    def valid_host(self):
        try:
            parsed = urlparse('http://' + self.headers.get('Host', ''))
            allowed = {'localhost', '127.0.0.1'} | ({ARGS.lan_ip} if ARGS.lan_ip else set())
            return (parsed.hostname in allowed and not parsed.username and not parsed.password
                    and (parsed.port or 80) == ARGS.port and not parsed.path and not parsed.query and not parsed.fragment)
        except ValueError:
            return False

    def send_response_headers(self, status, kind='application/json', length=None):
        self.send_response(status)
        self.send_header('Content-Type', kind)
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Content-Security-Policy', "frame-ancestors 'none'")
        self.send_header('Cache-Control', 'no-store')
        if length is not None:
            self.send_header('Content-Length', str(length))
        origin = self.headers.get('Origin')
        if origin and self.allowed_origin():
            self.send_header('Access-Control-Allow-Origin', origin)
            self.send_header('Vary', 'Origin')
        self.end_headers()

    def reply(self, status, obj):
        data = json.dumps(obj, allow_nan=False).encode()
        self.send_response_headers(status, length=len(data))
        self.wfile.write(data)

    def authorized(self):
        if not self.valid_host() or not self.allowed_origin():
            self.reply(403, {'error': 'Host or origin is not allowed.'})
            return False
        if not hmac.compare_digest(self.headers.get('Authorization', '').encode('utf-8'), ('Bearer ' + TOKEN).encode('utf-8')):
            self.reply(401, {'error': 'Invalid bridge token.'})
            return False
        return True

    def do_OPTIONS(self):
        if not self.valid_host() or not self.allowed_origin():
            self.reply(403, {'error': 'Origin is not allowed.'})
            return
        self.send_response(204)
        self.send_header('Access-Control-Allow-Origin', self.headers.get('Origin', ''))
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Authorization, Content-Type, X-Filename')
        self.send_header('Access-Control-Allow-Private-Network', 'true')
        self.send_header('Vary', 'Origin')
        self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path
        if path.startswith('/live/'):
            self.live_stream(path.rsplit('/', 1)[-1])
            return
        if path.startswith('/api/'):
            if not self.authorized():
                return
            try:
                if path == '/api/status':
                    with LOCK:
                        status = validation.status(ADAPTER.status()) if ADAPTER else {}
                    self.reply(200, {'protocol': 'alen-stb-bridge-v1',
                        'receiver': status.get('receiver', {'connected': False}), 'target': TARGET,
                        'capabilities': status.get('capabilities', []),
                        'message': 'No receiver adapter installed. UPnP discovery and DLNA are available; '
                                   'G-MScreen control requires a verified model-specific adapter.' if not ADAPTER else ''})
                elif path == '/api/integrations':
                    self.reply(200, {'satip': {'ffmpeg': bool(satip.ffmpeg_path())},
                        'calls': CALLS.snapshot(), 'lanAddress': f'http://{ARGS.lan_ip}:{ARGS.port}' if ARGS.lan_ip and ARGS.bind == '0.0.0.0' else None})
                elif path == '/api/calls/events':
                    after = int(parse_qs(urlparse(self.path).query).get('after', ['0'])[0])
                    self.reply(200, CALLS.snapshot(after))
                elif path == '/api/discover':
                    self.reply(200, discover())
                elif path in GET_METHODS:
                    self.adapter_call(GET_METHODS[path])
                else:
                    self.reply(404, {'error': 'Unknown API endpoint.'})
            except Exception as e:
                self.reply(502, {'error': str(e)[:250]})
            return
        if not self.valid_host():
            self.reply(403, {'error': 'Invalid host.'})
            return
        if path.startswith('/media/'):
            with LOCK:
                record = MEDIA.get(path.rsplit('/', 1)[-1])
            if not record or record['expires'] < time.time():
                self.reply(404, {'error': 'Media link has expired.'})
                return
            self.serve_file(record['path'], record['mime'])
            return
        if path == '/alen-stb-local.zip' and not (WEB / 'alen-stb-local.zip').exists():
            from package import build
            with LOCK:
                build()
        relative = unquote(path).lstrip('/') or 'index.html'
        target = (WEB / relative).resolve()
        if not target.is_relative_to(WEB.resolve()) or not target.is_file():
            self.reply(404, {'error': 'File not found.'})
            return
        # Windows file associations can override JavaScript/CSS MIME guesses.
        # Explicit types keep nosniff from blocking this app's own assets.
        web_types = {'.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8',
                     '.html': 'text/html; charset=utf-8', '.json': 'application/json; charset=utf-8'}
        mime = web_types.get(target.suffix.lower()) or mimetypes.guess_type(str(target))[0] or 'application/octet-stream'
        self.serve_file(target, mime)

    def do_HEAD(self):
        if urlparse(self.path).path.startswith(('/api/', '/live/')):
            self.send_response(405)
            self.send_header('Allow', 'GET, POST, OPTIONS')
            self.end_headers()
            return
        self.do_GET()

    def serve_file(self, path, mime):
        size = path.stat().st_size
        start, end, status = 0, size - 1, 200
        range_header = self.headers.get('Range')
        if range_header:
            try:
                if not range_header.startswith('bytes=') or ',' in range_header:
                    raise ValueError()
                a, b = range_header[6:].split('-')
                if a:
                    start = int(a)
                    end = min(int(b), end) if b else end
                else:
                    start = max(0, size - int(b))
                if start < 0 or start > end or end >= size:
                    raise ValueError()
                status = 206
            except ValueError:
                self.send_response(416)
                self.send_header('Content-Range', f'bytes */{size}')
                self.end_headers()
                return
        self.send_response(status)
        self.send_header('Content-Type', mime)
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Content-Security-Policy', "frame-ancestors 'none'")
        self.send_header('Accept-Ranges', 'bytes')
        self.send_header('Content-Length', str(max(0, end - start + 1)))
        if status == 206:
            self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
        self.end_headers()
        if self.command == 'HEAD':
            return
        try:
            with path.open('rb') as f:
                f.seek(start)
                remaining = end - start + 1
                while remaining > 0:
                    chunk = f.read(min(64*1024, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def adapter_call(self, name, body=None):
        if name == 'stream' and ADAPTER and callable(getattr(ADAPTER, 'satip_source', None)):
            validation.command(name, body)
            with LOCK:
                if not ADAPTER.status()['receiver']['connected']:
                    raise ValueError('G-MScreen receiver disconnected.')
                config = ADAPTER.satip_source(body['id'], body.get('port', 554))
                satip.private_host(config['host'])
                satip.number(config['port'], 'RTSP port', 1, 65535)
            key = STREAMS.ticket(config)
            self.reply(200, {'url': '/live/' + key, 'streamId': key})
            return
        if not ADAPTER or not callable(getattr(ADAPTER, name, None)):
            self.reply(501, {'error': 'A verified receiver adapter is required for this function. '
                                    'No command was sent to your STB.'})
            return
        with LOCK:
            status = validation.status(ADAPTER.status())
            if status.get('receiver', {}).get('connected') is not True:
                self.reply(409, {'error': 'Receiver is not connected. No command was sent.'})
                return
            capability = {'channel_update': 'channels.edit', 'channel_delete': 'channels.edit',
                'channel_order': 'channels.edit', 'channel_tune': 'channels.tune',
                'timer_save': 'timers', 'timer_delete': 'timers', 'timers': 'timers',
                'settings_save': 'settings', 'settings': 'settings', 'factory_reset': 'factory-reset'}.get(name, name)
            if name != 'channels' and capability not in status.get('capabilities', []):
                self.reply(501, {'error': 'Receiver adapter does not support this operation.'})
                return
            if body is not None:
                validation.command(name, body)
            result = getattr(ADAPTER, name)(body) if body is not None else getattr(ADAPTER, name)()
            validation.response(name, result)
            if not isinstance(result, dict):
                raise ValueError('Receiver adapter returned an invalid response.')
            if body is not None and name != 'stream' and result.get('ok') is not True:
                raise ValueError('Receiver did not acknowledge this operation.')
            if name == 'stream' and not isinstance(result.get('url'), str):
                raise ValueError('Receiver did not return a stream URL.')
        self.reply(200, result)

    def do_POST(self):
        global TARGET
        if urlparse(self.path).path == '/api/bootstrap':
            self.bootstrap()
            return
        if urlparse(self.path).path in ('/api/calls/claim', '/api/calls/event'):
            self.companion_post()
            return
        if not self.authorized():
            return
        self.connection.settimeout(60)
        path = urlparse(self.path).path
        try:
            length = int(self.headers.get('Content-Length', '0'))
            limit = MAX_UPLOAD if path == '/api/media/upload' else 64 * 1024
            if not 0 < length <= limit:
                self.reply(413, {'error': 'Invalid body size. Maximum media upload: 100 MB.'})
                return
            if path == '/api/media/upload':
                self.upload(length)
                return
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict):
                raise ValueError('Expected a JSON object.')
            if path == '/api/satip/start':
                key = STREAMS.ticket(satip.source(body))
                self.reply(200, {'url': '/live/' + key, 'streamId': key})
                return
            if path == '/api/satip/stop':
                STREAMS.stop(body.get('streamId'))
                self.reply(200, {'ok': True})
                return
            if path == '/api/calls/pair':
                if not ARGS.lan_ip or ARGS.bind != '0.0.0.0':
                    raise ValueError('Start the bridge in LAN mode before pairing a phone. See the setup instructions.')
                self.reply(200, {**CALLS.pair(), 'address': f'http://{ARGS.lan_ip}:{ARGS.port}'})
                return
            if path == '/api/calls/revoke':
                CALLS.revoke()
                self.reply(200, {'ok': True})
                return
            if path in ('/api/receiver/probe', '/api/receiver/configure'):
                target = validate_target(body)
                if path.endswith('/probe'):
                    self.reply(200, probe_target(target))
                else:
                    configured = False
                    with LOCK:
                        if ADAPTER and callable(getattr(ADAPTER, 'configure', None)):
                            ADAPTER.configure(dict(target))
                            configured = True
                        TARGET = target
                    self.reply(200, {'target': target, 'adapterConfigured': configured,
                        'message': 'Target saved for this bridge session.' if configured else
                                   'Target saved. A compatible adapter implementing configure(target) is still required.'})
                return
            if path == '/api/factory-reset' and body.get('confirmation') != 'RESET':
                raise ValueError('Factory reset confirmation is required.')
            if path in POST_METHODS:
                self.adapter_call(POST_METHODS[path], body)
            else:
                self.reply(404, {'error': 'Unknown API endpoint.'})
        except (ValueError, json.JSONDecodeError) as e:
            self.reply(400, {'error': str(e)[:250]})
        except Exception as e:
            self.reply(502, {'error': str(e)[:250]})

    def companion_post(self):
        if not self.valid_host() or not self.allowed_origin():
            self.reply(403, {'error': 'Host or origin is not allowed.'})
            return
        try:
            length = int(self.headers.get('Content-Length', 0))
            if not 0 < length <= 2048:
                raise ValueError('Invalid phone event size.')
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict):
                raise ValueError('Expected a JSON object.')
            if urlparse(self.path).path == '/api/calls/claim':
                value = CALLS.claim(body.get('code'))
            else:
                authorization = self.headers.get('Authorization', '')
                secret = authorization[7:] if authorization.startswith('Bearer ') else ''
                value = CALLS.event(secret, body)
            self.reply(200, value)
        except PermissionError as error:
            self.reply(401, {'error': str(error)})
        except (ValueError, TypeError) as error:
            self.reply(400, {'error': str(error)[:250]})

    def live_stream(self, key):
        if not self.valid_host() or not self.allowed_origin():
            self.reply(403, {'error': 'Host or origin is not allowed.'})
            return
        stream = None
        sent = False
        timer = None
        try:
            stream = STREAMS.start(key)
            timer = threading.Timer(20, stream.close)
            timer.start()
            first = stream.proc.stdout.read(32768)
            timer.cancel()
            if not first:
                raise ValueError(stream.error or 'SAT>IP did not produce playable video. Check tuning, codecs and UDP firewall rules.')
            self.send_response_headers(200, 'video/mp4')
            sent = True
            self.wfile.write(first)
            self.wfile.flush()
            while not stream.stopped.is_set():
                chunk = stream.proc.stdout.read(32768)
                if not chunk:
                    break
                self.wfile.write(chunk)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            pass
        except Exception as error:
            if not sent:
                self.reply(502, {'error': str(error)[:250]})
        finally:
            if timer:
                timer.cancel()
            if stream:
                stream.close()

    def upload(self, length):
        global MEDIA_RESERVED
        if not ARGS.lan_ip or ARGS.bind == '127.0.0.1':
            self.reply(409, {'error': 'For DLNA, start with --bind 0.0.0.0 --lan-ip YOUR_COMPUTER_LAN_IP '
                                    'and allow this port on your private network.'})
            return
        renderer = parse_qs(urlparse(self.path).query).get('renderer', [''])[0]
        with LOCK:
            device = DEVICES.get(renderer)
        if not device or not device.get('control'):
            raise ValueError('Discover and select an AVTransport MediaRenderer first.')
        mime = self.headers.get('Content-Type', '').split(';')[0]
        if mime not in validation.MEDIA_TYPES:
            raise ValueError('Unsupported media format. Active document formats such as SVG are not accepted.')
        with LOCK:
            for key, record in list(MEDIA.items()):
                if record['expires'] < time.time():
                    try:
                        record['path'].unlink(missing_ok=True)
                    except OSError:
                        continue
                    del MEDIA[key]
            if sum(r['size'] for r in MEDIA.values()) + MEDIA_RESERVED + length > MEDIA_LIMIT:
                self.reply(413, {'error': 'Temporary media storage is full. Restart the bridge to clear it.'})
                return
            MEDIA_RESERVED += length
        reserved = True
        ident = secrets.token_urlsafe(24)
        target = Path(TMP.name) / ident
        try:
            with target.open('wb') as f:
                remaining = length
                while remaining:
                    data = self.rfile.read(min(65536, remaining))
                    if not data:
                        raise ValueError('Upload was interrupted.')
                    f.write(data)
                    remaining -= len(data)
            with LOCK:
                MEDIA[ident] = {'path': target, 'mime': mime, 'expires': time.time()+7200, 'size': length}
                MEDIA_RESERVED -= length
                reserved = False
            uri = f'http://{ARGS.lan_ip}:{ARGS.port}/media/{ident}'
            soap(device, 'SetAVTransportURI', {'InstanceID': 0, 'CurrentURI': uri, 'CurrentURIMetaData': ''})
            soap(device, 'Play', {'InstanceID': 0, 'Speed': '1'})
            self.reply(200, {'ok': True})
        except Exception:
            with LOCK:
                MEDIA.pop(ident, None)
            target.unlink(missing_ok=True)
            raise
        finally:
            if reserved:
                with LOCK:
                    MEDIA_RESERVED -= length


def main():
    global ARGS, ADAPTER, TARGET
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bind', default='127.0.0.1', choices=['127.0.0.1', '0.0.0.0'])
    parser.add_argument('--port', type=int, default=8787)
    parser.add_argument('--lan-ip', help='Computer private IPv4 address; required for DLNA media serving')
    parser.add_argument('--origin', action='append', default=[], help='Extra allowed exact browser origin')
    parser.add_argument('--open-browser', action='store_true', help='Open the local app automatically')
    parser.add_argument('--port-auto', action='store_true', help='Choose another local port if the requested one is busy')
    parser.add_argument('--adapter', help='Path to a trusted model-specific Python adapter')
    parser.add_argument('--stb-ip', help='Receiver private LAN IPv4 address')
    parser.add_argument('--stb-port', type=int, default=20000, help='Receiver TCP port, 1–65535')
    ARGS = parser.parse_args()
    if not 1 <= ARGS.port <= 65535 or not 1 <= ARGS.stb_port <= 65535:
        parser.error('Ports must be between 1 and 65535.')
    if ARGS.stb_ip:
        try:
            TARGET = validate_target({'host': ARGS.stb_ip, 'port': ARGS.stb_port})
        except ValueError as error:
            parser.error(str(error))
    if ARGS.lan_ip:
        ip = ipaddress.ip_address(ARGS.lan_ip)
        if ip.version != 4 or not ip.is_private or ip.is_loopback or ip.is_unspecified:
            parser.error('--lan-ip must be the computer private LAN IPv4 address')
    ARGS.origins = set(ARGS.origin) | {f'http://127.0.0.1:{ARGS.port}', f'http://localhost:{ARGS.port}'}
    if ARGS.lan_ip:
        ARGS.origins.add(f'http://{ARGS.lan_ip}:{ARGS.port}')
    if ARGS.adapter:
        spec = importlib.util.spec_from_file_location('alen_adapter', Path(ARGS.adapter).resolve())
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        ADAPTER = module.Adapter()
        if TARGET and callable(getattr(ADAPTER, 'configure', None)):
            ADAPTER.configure(dict(TARGET))
    else:
        from gmscreen import Adapter
        ADAPTER = Adapter()
        if TARGET:
            ADAPTER.configure(dict(TARGET))
    server = None
    requested_port = ARGS.port
    ports = range(requested_port, min(requested_port + 10, 65536)) if ARGS.port_auto else [requested_port]
    for port in ports:
        try:
            server = ThreadingHTTPServer((ARGS.bind, port), Handler)
            ARGS.port = port
            break
        except OSError:
            if not ARGS.port_auto:
                raise
    if server is None:
        raise OSError('No local port available. Close another bridge or choose --port.')
    ARGS.origins.update({f'http://127.0.0.1:{ARGS.port}', f'http://localhost:{ARGS.port}'})
    if ARGS.lan_ip:
        ARGS.origins.add(f'http://{ARGS.lan_ip}:{ARGS.port}')
    if ARGS.open_browser:
        threading.Timer(0.4, lambda: webbrowser.open(f'http://127.0.0.1:{ARGS.port}/#connect')).start()
    print(f'\nAlen STB — open http://127.0.0.1:{ARGS.port}\nBridge token: {TOKEN}\n', flush=True)
    print('Receiver control: ' + ('adapter loaded; verify capabilities in the app' if ADAPTER else 'NOT CONNECTED — model-specific adapter required'), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        STREAMS.close()
        if ADAPTER and callable(getattr(ADAPTER, 'close', None)):
            ADAPTER.close()
        server.server_close()
        TMP.cleanup()

if __name__ == '__main__':
    main()
