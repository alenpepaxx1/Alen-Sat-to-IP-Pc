# Copyright © 2026 Alen Pepa.
"""Interface example ONLY. This is not a G-MScreen protocol implementation.
Implement only methods verified against the specific receiver and firmware.
Do not advertise capabilities that have not been implemented.
"""
class Adapter:
    def status(self):
        return {'receiver': {'connected': False, 'name': 'No verified adapter', 'protocol': 'Unconfigured'},
                'capabilities': []}

    def channels(self):
        raise NotImplementedError('Implement channels() using the verified receiver protocol.')
