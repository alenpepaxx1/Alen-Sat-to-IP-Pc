# Copyright © 2026 Alen Pepa.
import unittest
from datetime import datetime, timedelta, timezone
import validation

class ValidationTest(unittest.TestCase):
    def test_invalid_commands_never_reach_adapter(self):
        cases = [('remote', {'key': 'RAW_CODE'}), ('power', {'mode': 'anything'}),
                 ('channel_order', {'ids': ['a', 'a']}),
                 ('channel_update', {'id': 'a', 'patch': {'locked': 'false'}}),
                 ('channel_update', {'id': 'a', 'patch': {'unexpected': True}}),
                 ('settings_save', {'parental': 'false'}), ('password', {'current':'1234','next':'abcd'})]
        for name, body in cases:
            with self.subTest(name=name, body=body), self.assertRaises(ValueError):
                validation.command(name, body)

    def test_timer_requires_explicit_timezone(self):
        value = {'id':'one','title':'Programme','channelId':'a','start':(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat(), 'duration':60,'type':'Record'}
        validation.command('timer_save', value)
        value['start'] = '2099-01-01T12:00'
        with self.assertRaises(ValueError): validation.command('timer_save', value)

    def test_bad_receiver_data_rejected(self):
        for name, value in [('signal', {'snr': float('nan')}), ('signal', {'quality':101}),
                            ('channels', {'channels':[{'id':'a','name':'A'},{'id':'a','name':'B'}]}),
                            ('stream', {'url':'rtsp://192.168.1.1/live'}), ('epg', {'programmes':{}})]:
            with self.subTest(name=name), self.assertRaises(ValueError): validation.response(name, value)
        validation.response('signal', {'snr':None,'quality':None,'strength':None,'locked':None})

    def test_active_media_formats_not_allowed(self):
        self.assertNotIn('image/svg+xml', validation.MEDIA_TYPES)
        self.assertNotIn('text/html', validation.MEDIA_TYPES)
        self.assertIn('video/mp4', validation.MEDIA_TYPES)

if __name__ == '__main__': unittest.main()
