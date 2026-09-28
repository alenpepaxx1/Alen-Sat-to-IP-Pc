# Copyright © 2026 Alen Pepa.
"""Open the local Alen STB app; the browser pairs automatically on loopback."""
import json
import argparse
import socket
from satip import private_host
from concurrent.futures import ThreadPoolExecutor
from runtime_identity import VERSION, INSTALLATION_ID
from pathlib import Path
import sys
import webbrowser
from urllib.request import Request, build_opener, ProxyHandler


def running_bridge(port=8787, lan=False):
    origin = f'http://127.0.0.1:{port}'
    request = Request(origin + '/api/bootstrap', method='POST', data=b'', headers={
        'Origin': origin, 'X-Alen-Bootstrap': '1'})
    try:
        with build_opener(ProxyHandler({})).open(request, timeout=1) as response:
            data = json.loads(response.read(16384))
        return (data.get('protocol') == 'alen-stb-bridge-v1' and data.get('automatic') is True
                and (not lan or data.get('lanAvailable') is True)
                and data.get('version') == VERSION and data.get('installationId') == INSTALLATION_ID)
    except Exception:
        return False


def find_running_bridge(lan=False):
    # Only the ten loopback ports this launcher can allocate; never scan the LAN.
    ports = list(range(8787, 8797))
    with ThreadPoolExecutor(max_workers=len(ports)) as pool:
        results = list(pool.map((lambda port: running_bridge(port, True)) if lan else running_bridge, ports))
    return next((port for port, found in zip(ports, results) if found), None)


def main(argv=None):
    if sys.version_info < (3, 10):
        raise SystemExit('Alen STB requires Python 3.10 or newer.')
    parser = argparse.ArgumentParser()
    parser.add_argument('--lan', action='store_true')
    parser.add_argument('--lan-ip')
    options = parser.parse_args(argv)
    lan = options.lan or bool(options.lan_ip)
    existing_port = find_running_bridge(True) if lan else find_running_bridge()
    if existing_port is not None:
        webbrowser.open(f'http://127.0.0.1:{existing_port}/#connect')
        return
    import bridge
    # Users can install their verified device adapter at this conventional path.
    adapter = Path(__file__).with_name('receiver_adapter.py')
    sys.argv = [str(Path(bridge.__file__)), '--open-browser', '--port-auto']
    if lan:
        if options.lan_ip:
            address = private_host(options.lan_ip)
        else:
            # UDP connect selects a route without sending packets.
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as route:
                route.connect(('10.255.255.255', 1))
                address = private_host(route.getsockname()[0])
        sys.argv += ['--bind', '0.0.0.0', '--lan-ip', address]
    if adapter.is_file():
        sys.argv += ['--adapter', str(adapter)]
    bridge.main()


if __name__ == '__main__':
    main()
