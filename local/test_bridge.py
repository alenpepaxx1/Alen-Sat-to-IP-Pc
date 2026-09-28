# Copyright © 2026 Alen Pepa.
import json
import threading
import unittest
from unittest.mock import patch, MagicMock
import urllib.request
import urllib.error
from types import SimpleNamespace
import bridge

class GatewayTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = bridge.ThreadingHTTPServer(('127.0.0.1', 0), bridge.Handler)
        cls.port = cls.server.server_port
        cls.origin = f'http://127.0.0.1:{cls.port}'
        bridge.ARGS = SimpleNamespace(origins={cls.origin}, lan_ip=None, bind='127.0.0.1', port=cls.port)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        bridge.TMP.cleanup()

    def req(self, path, auth=True, data=None, headers=None, method=None):
        h = {'Authorization': 'Bearer ' + bridge.TOKEN} if auth else {}
        h.update(headers or {})
        try:
            request = urllib.request.Request(self.origin + path,
                data=json.dumps(data).encode() if data is not None else None, headers=h, method=method)
            with urllib.request.urlopen(request) as r:
                return r.status, r.read(), dict(r.headers)
        except urllib.error.HTTPError as e:
            return e.code, e.read(), dict(e.headers)

    def test_phone_pairing_token_is_scoped_and_live_head_is_safe(self):
        from calls import Calls
        with patch.object(bridge, 'CALLS', Calls()):
            self.assertEqual(self.req('/api/calls/pair', auth=False, data={})[0], 401)
            with patch.object(bridge.ARGS, 'bind', '0.0.0.0'), patch.object(bridge.ARGS, 'lan_ip', '192.168.1.50'):
                code = json.loads(self.req('/api/calls/pair', data={})[1])['code']
            status, raw, _ = self.req('/api/calls/claim', auth=False, data={'code':code})
            self.assertEqual(status, 200)
            phone = json.loads(raw)['token']
            headers = {'Authorization': 'Bearer ' + phone}
            self.assertEqual(self.req('/api/status', auth=False, headers=headers)[0], 401)
            event = {'sequence':1,'callId':'native-call','state':'ringing'}
            self.assertEqual(self.req('/api/calls/event', auth=False, headers=headers, data=event)[0], 200)
            self.assertEqual(json.loads(self.req('/api/calls/events?after=0')[1])['events'][0]['state'], 'ringing')
            self.assertEqual(self.req('/api/calls/revoke', data={})[0], 200)
            self.assertEqual(self.req('/api/calls/event', auth=False, headers=headers, data=event)[0], 401)
        with patch.object(bridge.STREAMS, 'start') as start:
            self.assertEqual(self.req('/live/test', auth=False, method='HEAD')[0], 405)
            start.assert_not_called()

    def test_auth_and_origins(self):
        self.assertEqual(self.req('/api/status', False)[0], 401)
        self.assertEqual(self.req('/api/status', headers={'Origin': 'https://untrusted.invalid'})[0], 403)
        self.assertEqual(self.req('/api/status', headers={'Host': 'evil.invalid'})[0], 403)
        self.assertEqual(self.req('/api/status', headers={'Origin': self.origin}, method='OPTIONS')[0], 204)

    def test_no_fake_receiver_success(self):
        status, raw, _ = self.req('/api/status')
        self.assertEqual(status, 200)
        self.assertFalse(json.loads(raw)['receiver']['connected'])
        self.assertEqual(self.req('/api/channels')[0], 501)
        self.assertEqual(self.req('/api/remote', data={'key': 'UP'})[0], 501)
        self.assertEqual(self.req('/api/factory-reset', data={'confirmation': 'WRONG'})[0], 400)
        self.assertEqual(self.req('/api/factory-reset', data={'confirmation': 'RESET'})[0], 501)
        self.assertEqual(self.req('/api/unknown')[0], 404)

    def test_static_and_range(self):
        self.assertEqual(self.req('/', False)[0], 200)
        r = self.req('/app.js', False, headers={'Range': 'bytes=0-9'})
        self.assertEqual(r[0], 206)
        self.assertEqual(len(r[1]), 10)
        self.assertEqual(self.req('/%2e%2e/local/bridge.py', False)[0], 404)
        self.assertEqual(self.req('/app.js', False, headers={'Range': 'bytes=99999999-'})[0], 416)

    def test_static_types_ignore_broken_system_file_associations(self):
        with patch.object(bridge.mimetypes, 'guess_type', return_value=('text/plain', None)):
            for path, expected in [('/app.js', 'text/javascript'), ('/style.css', 'text/css'), ('/', 'text/html')]:
                status, _, headers = self.req(path, False)
                self.assertEqual(status, 200)
                self.assertEqual(headers['Content-Type'], expected + '; charset=utf-8')
                self.assertEqual(headers['X-Content-Type-Options'], 'nosniff')

    def test_device_urls(self):
        for u in ['http://127.0.0.1/a', 'http://8.8.8.8/a', 'http://example.com/a', 'https://192.168.1.1/a']:
            with self.assertRaises(ValueError):
                bridge.private_url(u)
        self.assertEqual(bridge.private_url('http://192.168.1.1/device.xml').hostname, '192.168.1.1')
        with self.assertRaises(ValueError):
            bridge.private_url('http://192.168.1.2/a', '192.168.1.3')

    def test_target_port_boundaries(self):
        for port in [1, 80, 554, 20000, 65535]:
            target = bridge.validate_target({'host': '192.168.1.100', 'port': port})
            self.assertEqual(target['port'], port)
        for port in [0, -1, 65536, True, '554', 1.5, None]:
            with self.subTest(port=port):
                self.assertEqual(self.req('/api/receiver/configure', data={'host': '192.168.1.100', 'port': port})[0], 400)
        for host in ['127.0.0.1', '0.0.0.0', '8.8.8.8', '169.254.1.1', '192.0.0.1', 'example.com', '::1']:
            with self.subTest(host=host):
                self.assertEqual(self.req('/api/receiver/probe', data={'host': host, 'port': 554})[0], 400)
        for host in ['10.0.0.1', '172.16.0.1', '172.31.255.254', '192.168.255.254']:
            self.assertEqual(bridge.validate_target({'host': host, 'port': 65535})['host'], host)

    def test_target_save_is_not_receiver_connection(self):
        target = {'host': '192.168.1.100', 'port': 65535}
        code, data, _ = self.req('/api/receiver/configure', data=target)
        result = json.loads(data)
        self.assertEqual(code, 200)
        self.assertEqual(result['target'], target)
        self.assertFalse(result['adapterConfigured'])
        status = json.loads(self.req('/api/status')[1])
        self.assertFalse(status['receiver']['connected'])
        self.assertEqual(status['target'], target)

    def test_probe_uses_exact_endpoint_without_payload(self):
        target = {'host': '192.168.1.100', 'port': 49157}
        conn = MagicMock()
        with patch.object(bridge, 'tcp_connection', return_value=conn) as connect:
            code, raw, _ = self.req('/api/receiver/probe', data=target)
            connect.assert_called_once_with(('192.168.1.100', 49157), timeout=2.5)
            conn.__enter__.return_value.send.assert_not_called()
            conn.__enter__.return_value.sendall.assert_not_called()
            result = json.loads(raw)
            self.assertEqual(code, 200)
            self.assertTrue(result['reachable'])
            self.assertFalse(result['protocolVerified'])
        with patch.object(bridge, 'tcp_connection', side_effect=TimeoutError()):
            result = json.loads(self.req('/api/receiver/probe', data=target)[1])
            self.assertFalse(result['reachable'])

    def test_adapter_configuration_handoff(self):
        old_adapter = bridge.ADAPTER
        try:
            bridge.ADAPTER = MagicMock()
            target = {'host': '10.0.0.55', 'port': 12345}
            result = json.loads(self.req('/api/receiver/configure', data=target)[1])
            bridge.ADAPTER.configure.assert_called_once_with(target)
            self.assertTrue(result['adapterConfigured'])
        finally:
            bridge.ADAPTER = old_adapter

    def test_receiver_write_requires_connection_capability_and_ack(self):
        old_adapter = bridge.ADAPTER
        try:
            adapter = MagicMock()
            bridge.ADAPTER = adapter
            adapter.status.return_value = {'receiver': {'connected': False}, 'capabilities': ['remote']}
            self.assertEqual(self.req('/api/remote', data={'key': 'UP'})[0], 409)
            adapter.remote.assert_not_called()
            adapter.status.return_value = {'receiver': {'connected': True}, 'capabilities': []}
            self.assertEqual(self.req('/api/remote', data={'key': 'UP'})[0], 501)
            adapter.remote.assert_not_called()
            adapter.status.return_value = {'receiver': {'connected': True}, 'capabilities': ['remote']}
            adapter.remote.return_value = {}
            self.assertEqual(self.req('/api/remote', data={'key': 'UP'})[0], 400)
            adapter.remote.return_value = {'ok': True}
            self.assertEqual(self.req('/api/remote', data={'key': 'UP'})[0], 200)
        finally:
            bridge.ADAPTER = old_adapter

    def test_dlna_requires_soap_ack(self):
        device = {'control': 'http://192.168.1.22/control', 'service': 'urn:schemas-upnp-org:service:AVTransport:1'}
        with patch.object(bridge, 'local_fetch', return_value=b'<Envelope><Body/></Envelope>'):
            with self.assertRaises(ValueError):
                bridge.soap(device, 'Play', {'InstanceID': 0, 'Speed': '1'})
        with patch.object(bridge, 'local_fetch', return_value=b'<Envelope><Body><PlayResponse/></Body></Envelope>'):
            bridge.soap(device, 'Play', {'InstanceID': 0, 'Speed': '1'})

    def test_upload_reservations_and_failed_upload_cleanup(self):
        old_args, old_reserved = bridge.ARGS, bridge.MEDIA_RESERVED
        old_devices, old_media = dict(bridge.DEVICES), dict(bridge.MEDIA)
        try:
            bridge.ARGS = SimpleNamespace(origins={self.origin}, lan_ip='192.168.1.50', bind='0.0.0.0', port=self.port)
            bridge.DEVICES['tv'] = {'control':'http://192.168.1.22/control','service':'urn:schemas-upnp-org:service:AVTransport:1'}
            bridge.MEDIA.clear()
            bridge.MEDIA_RESERVED = bridge.MEDIA_LIMIT
            response = self.req('/api/media/upload?renderer=tv', data={}, headers={'Content-Type':'video/mp4'})
            self.assertEqual(response[0], 413)
            self.assertEqual(bridge.MEDIA_RESERVED, bridge.MEDIA_LIMIT)
            bridge.MEDIA_RESERVED = 0
            with patch.object(bridge, 'soap', side_effect=ValueError('TV rejected request')):
                response = self.req('/api/media/upload?renderer=tv', data={}, headers={'Content-Type':'video/mp4'})
                self.assertEqual(response[0], 400)
            self.assertEqual(bridge.MEDIA_RESERVED, 0)
            self.assertEqual(bridge.MEDIA, {})
            response = self.req('/api/media/upload?renderer=tv', data={}, headers={'Content-Type':'image/svg+xml'})
            self.assertEqual(response[0], 400)
        finally:
            bridge.ARGS, bridge.MEDIA_RESERVED = old_args, old_reserved
            bridge.DEVICES.clear();bridge.DEVICES.update(old_devices)
            bridge.MEDIA.clear();bridge.MEDIA.update(old_media)

    def test_head_cannot_trigger_discovery(self):
        with patch.object(bridge, 'discover') as discovery:
            self.assertEqual(self.req('/api/discover', method='HEAD')[0], 405)
            discovery.assert_not_called()

    def test_local_bootstrap_without_manual_token(self):
        code, raw, headers = self.req('/api/bootstrap', auth=False, data={}, headers={
            'Origin': self.origin, 'Sec-Fetch-Site': 'same-origin', 'X-Alen-Bootstrap': '1'})
        self.assertEqual(code, 200)
        value = json.loads(raw)
        self.assertEqual(value['token'], bridge.TOKEN)
        self.assertTrue(value['automatic'])
        self.assertEqual(value['bridge'], self.origin)
        self.assertEqual(headers['Cache-Control'], 'no-store')
        self.assertEqual(headers['X-Frame-Options'], 'DENY')

    def test_bootstrap_rejects_other_origins_even_if_cors_allowed(self):
        other = 'https://hosted-app.invalid'
        bridge.ARGS.origins.add(other)
        try:
            for headers in [
                {'Origin': other, 'X-Alen-Bootstrap': '1'},
                {'Origin': self.origin, 'Sec-Fetch-Site':'cross-site', 'X-Alen-Bootstrap':'1'},
                {'Origin': self.origin}, {'X-Alen-Bootstrap':'1'}]:
                with self.subTest(headers=headers):
                    code, raw, _ = self.req('/api/bootstrap', auth=False, data={}, headers=headers)
                    self.assertEqual(code, 403)
                    self.assertNotIn(bridge.TOKEN.encode(), raw)
        finally:
            bridge.ARGS.origins.discard(other)

    def test_bootstrap_rejects_non_loopback_client(self):
        handler = object.__new__(bridge.Handler)
        handler.headers = {'Host':'127.0.0.1:8787', 'Origin':'http://127.0.0.1:8787',
                           'Sec-Fetch-Site':'same-origin','X-Alen-Bootstrap':'1'}
        handler.client_address = ('192.168.1.44',12345)
        handler.reply = MagicMock()
        handler.bootstrap()
        self.assertEqual(handler.reply.call_args.args[0],403)

    def test_invalid_host_and_non_ascii_token_return_errors(self):
        code, _, _ = self.req('/api/status', headers={'Authorization':'Bearer caf\xe9'})
        self.assertEqual(code, 401)
        self.assertEqual(self.req('/api/status', headers={'Host':'127.0.0.1:1'})[0],403)
        handler = object.__new__(bridge.Handler)
        handler.headers = {}
        self.assertFalse(handler.valid_host())
        handler.headers = {'Host':'user@127.0.0.1:' + str(self.port)}
        self.assertFalse(handler.valid_host())

    def test_launcher_recognizes_real_running_bridge(self):
        import launcher
        self.assertTrue(launcher.running_bridge(self.port))

    def test_upnp_url_base_resolution_and_host_validation(self):
        xml = b'''<root xmlns="urn:schemas-upnp-org:device-1-0"><URLBase>http://192.168.1.22:1400/renderer/</URLBase><device><deviceType>urn:schemas-upnp-org:device:MediaRenderer:1</deviceType><friendlyName>TV</friendlyName><UDN>uuid:tv</UDN><serviceList><service><serviceType>urn:schemas-upnp-org:service:AVTransport:1</serviceType><controlURL>transport</controlURL></service></serviceList></device></root>'''
        entries = bridge.parse_devices('http://192.168.1.22/root.xml', xml)
        self.assertEqual(entries[0]['control'],'http://192.168.1.22:1400/renderer/transport')
        with self.assertRaises(ValueError):
            bridge.parse_devices('http://192.168.1.22/root.xml',xml.replace(b'192.168.1.22:1400',b'192.168.1.99:1400'))

if __name__ == '__main__':
    unittest.main()
