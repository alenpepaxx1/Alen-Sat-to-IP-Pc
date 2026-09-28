# Copyright © 2026 Alen Pepa.
import json
import socket
import subprocess
import tempfile
import threading
import time
import unittest
import zlib
from pathlib import Path
from unittest.mock import patch
import calls
import gmscreen
import satip


class CallTests(unittest.TestCase):
    def test_pair_scope_expiry_and_duplicate_events(self):
        relay = calls.Calls()
        code = relay.pair()['code']
        with self.assertRaises(ValueError): relay.claim('000')
        token = relay.claim(code)['token']
        with self.assertRaises(ValueError): relay.claim(code)
        event = {'sequence': 1, 'state': 'ringing', 'callId': 'phone-call-1'}
        with self.assertRaises(PermissionError): relay.event('invalid', event)
        self.assertEqual(relay.event(token, event), {'ok': True})
        self.assertTrue(relay.event(token, event)['duplicate'])
        self.assertEqual(len(relay.snapshot()['events']), 1)
        self.assertEqual(relay.snapshot(1)['events'], [])
        relay.revoke()
        with self.assertRaises(PermissionError): relay.event(token, event)

    def test_pairing_lockout(self):
        relay = calls.Calls()
        code = relay.pair()['code']
        for _ in range(9):
            with self.assertRaises(ValueError): relay.claim('bad')
        with self.assertRaises(ValueError): relay.claim(code)
        self.assertIn('token', relay.claim(relay.pair()['code']))


class WireTests(unittest.TestCase):
    def test_gmscreen_fragmented_handshake_header_payload(self):
        listener = socket.socket()
        listener.bind(('127.0.0.1', 0)); listener.listen()
        failures = []
        def server():
            try:
                with listener.accept()[0] as peer:
                    peer.settimeout(3)
                    def receive():
                        head = gmscreen.exact(peer, 15)
                        self.assertEqual(head[:5], b'Start')
                        return gmscreen.exact(peer, int(head[5:12]))
                    self.assertIn(b'998', receive())
                    peer.sendall(b'['); peer.sendall(b'[' + bytes(106))
                    for expected, value in [('15', [{'ChannelNum': 1, 'ProductName': 'Protocol fixture'}]),
                                            ('15', [{'ChannelNum': 1, 'ProductName': 'Protocol fixture'}]),
                                            ('0', [{'ServiceID': '00010000100001', 'ServiceName': 'Transport test', 'Lock': 0, 'Scramble': 0}])]:
                        self.assertEqual(json.loads(receive())['request'], expected)
                        data = zlib.compress(json.dumps(value).encode())
                        head = b'GCDH' + len(data).to_bytes(2, 'little') + bytes(10)
                        for chunk in [head[:3], head[3:] + data[:2], data[2:]]:
                            peer.sendall(chunk)
            except Exception as error:
                failures.append(error)
        thread = threading.Thread(target=server); thread.start()
        adapter = gmscreen.Adapter()
        try:
            adapter.configure({'host': '127.0.0.1', 'port': listener.getsockname()[1]})
            self.assertTrue(adapter.status()['receiver']['connected'])
            self.assertNotIn('remote', adapter.status()['capabilities'])
            self.assertEqual(adapter.channels()['channels'][0]['name'], 'Transport test')
        finally:
            adapter.close(); thread.join(4); listener.close()
        self.assertEqual(failures, [])

    def test_oversized_gmscreen_decompression_rejected(self):
        with self.assertRaises(ValueError):
            gmscreen.decode_payload(zlib.compress(b' ' * (gmscreen.LIMIT + 1)))

    def test_ffmpeg_partial_writes_preserve_transport_bytes(self):
        class PartialPipe:
            def __init__(self): self.received = bytearray()
            def write(self, data):
                length = min(17, len(data))
                self.received.extend(data[:length])
                return length
        pipe = PartialPipe()
        payload = (b'G' + bytes(187)) * 7
        satip.write_all(pipe, payload)
        self.assertEqual(bytes(pipe.received), payload)
        for result in (0, None):
            with patch.object(pipe, 'write', return_value=result):
                with self.assertRaises(BrokenPipeError): satip.write_all(pipe, payload)

    def test_satip_targets_and_parameters(self):
        value = {'host': '192.168.1.2', 'freq': 11000, 'sr': 27500, 'pol': 'h', 'msys': 'dvbs2', 'pids': '0,100,101'}
        self.assertIn('freq=11000', satip.source(value)['query'])
        for patch_value in [{'host': '127.0.0.1'}, {'port': True}, {'pids': '8192'}, {'pol': 'x'}, {'program': -1}]:
            with self.assertRaises(ValueError): satip.source({**value, **patch_value})

    def test_rtp_extensions_and_padding(self):
        ts = b'G' + bytes(187)
        self.assertEqual(satip.rtp_payload(b'\x80\x21' + bytes(10) + ts), ts)
        self.assertEqual(satip.rtp_payload(b'\xb0\x21' + bytes(10) + b'\x00\x00\x00\x01' + bytes(4) + ts + b'\x00\x02'), ts)
        for packet in [b'', b'\x80\x01' + bytes(10) + ts, b'\x80\x21' + bytes(10) + ts[:-1]]:
            with self.assertRaises(ValueError): satip.rtp_payload(packet)

    @unittest.skipUnless(satip.ffmpeg_path(), 'FFmpeg unavailable')
    def test_rtsp_rtp_to_real_mp4_and_teardown(self):
        # Test fixture only; never bundled into or loaded by the application.
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / 'input.ts'
            subprocess.run([satip.ffmpeg_path(), '-loglevel', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=160x90:rate=25',
                '-t', '1', '-c:v', 'mpeg2video', '-f', 'mpegts', str(target)], check=True, timeout=15)
            raw = target.read_bytes()
        listener = socket.socket(); listener.bind(('127.0.0.1', 0)); listener.listen()
        methods, errors = [], []
        stop = threading.Event()
        def server():
            try:
                with listener.accept()[0] as peer:
                    peer.settimeout(10)
                    data = b''
                    while not stop.is_set():
                        while b'\r\n\r\n' not in data:
                            part = peer.recv(4096)
                            if not part: return
                            data += part
                        request, data = data.split(b'\r\n\r\n', 1)
                        lines = request.decode().split('\r\n'); method = lines[0].split()[0]; methods.append(method)
                        fields = dict(line.split(': ', 1) for line in lines[1:])
                        extra = ''
                        if method == 'SETUP':
                            port = int(fields['Transport'].split('client_port=')[1].split('-')[0])
                            extra = 'Session: test123;timeout=4\r\ncom.ses.streamID: 1\r\n'
                        response = f'RTSP/1.0 200 OK\r\nCSeq: {fields["CSeq"]}\r\n{extra}Content-Length: 0\r\n\r\n'.encode()
                        peer.sendall(response[:9]); peer.sendall(response[9:])
                        if method == 'PLAY':
                            def send():
                                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp:
                                    seq = 0
                                    while not stop.is_set():
                                        for start in range(0, len(raw), 1316):
                                            if stop.is_set(): return
                                            payload = raw[start:start+1316]
                                            udp.sendto(b'\x80\x21' + (seq % 65536).to_bytes(2,'big') + bytes(8) + payload, ('127.0.0.1', port))
                                            seq += 1; time.sleep(.002)
                            threading.Thread(target=send, daemon=True).start()
                        if method == 'TEARDOWN': return
            except Exception as error: errors.append(error)
        thread = threading.Thread(target=server); thread.start()
        stream = None
        try:
            stream = satip.Stream({'host': '127.0.0.1', 'port': listener.getsockname()[1], 'query': 'src=1&freq=11000', 'program': 0})
            guard = threading.Timer(15, stream.close); guard.start()
            output = b''
            while b'moof' not in output and len(output) < 1024*1024:
                chunk = stream.proc.stdout.read(4096)
                if not chunk: break
                output += chunk
            guard.cancel()
            self.assertIn(b'ftyp', output)
            self.assertIn(b'moof', output)
            self.assertFalse(stream.stopped.is_set(), stream.error)
        finally:
            if stream: stream.close()
            stop.set(); listener.close(); thread.join(5)
        self.assertIn('SETUP', methods); self.assertIn('PLAY', methods); self.assertIn('TEARDOWN', methods)
        self.assertIsNotNone(stream.proc.poll())
        self.assertEqual(errors, [])

if __name__ == '__main__': unittest.main()
