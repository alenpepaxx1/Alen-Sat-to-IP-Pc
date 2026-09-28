# Copyright © 2026 Alen Pepa.
"""Read-only G-MScreen compatibility report. Run on the receiver's LAN."""
import argparse
import json
from pathlib import Path
import gmscreen
import satip


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', required=True)
    parser.add_argument('--port', type=int, default=20000)
    parser.add_argument('--output', default='alen-stb-diagnostics.json')
    args = parser.parse_args()
    host = satip.private_host(args.host)
    port = satip.number(args.port, 'port', 1, 65535)
    adapter = gmscreen.Adapter()
    report = {'adapter': 'G-MScreen ALi', 'handshake': False}
    try:
        adapter.configure({'host': host, 'port': port})
        report['handshake'] = True
        report['device'] = {key: adapter.info.get(key) for key in ('ProductName', 'SoftwareVersion', 'ChannelNum')}
        count = int(adapter.info['ChannelNum'])
        if count:
            response = adapter.request({'request':'0', 'FromIndex':'0', 'ToIndex':str(min(2, count-1))})
            report['channelResponseType'] = type(response).__name__
            report['channelFieldNames'] = sorted({key for row in response if isinstance(row, dict) for key in row}) if isinstance(response, list) else []
        report['ffmpegInstalled'] = bool(satip.ffmpeg_path())
    except Exception as error:
        report['error'] = str(error)[:250]
    finally:
        adapter.close()
    Path(args.output).write_text(json.dumps(report, indent=2), encoding='utf-8')
    print('Saved compatibility report to', args.output)
    print('Contains model, firmware, response field names and errors; no IP, serial, tokens or channel names.')


if __name__ == '__main__':
    main()
