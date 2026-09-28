# Alen STB · Web client 0.8

A receiver workspace by Alen Pepa with a local Python gateway. This release has **no demo mode, fabricated channels, synthetic EPG, simulated commands or generated signal measurements**. It starts disconnected with empty receiver data. **It is not yet a complete G-MScreen replacement: the included G-MScreen ALi adapter implements device/channel reads and free-to-air stream parameters, but StarSat compatibility and physical device behavior are unverified. Undocumented control commands remain disabled.**

## Start on Windows — automatic local connection

1. Install Python 3.10+ once, if it is not already installed.
2. Extract the whole ZIP. Double-click **Start-Alen-STB.cmd**.
3. The local gateway starts and opens the app automatically. Keep its terminal window open.
4. Enter your receiver’s LAN IPv4 address, for example `192.168.1.100`, and click **Connect receiver**.

No bridge address or token needs to be copied when using the app opened by the launcher. Port 20000 is the current default, not a detected port; change it under **Advanced options** if needed. No receiver controls are enabled unless a compatible adapter establishes a real device connection.

The launcher checks the ten local bridge ports concurrently and reuses only a bridge from the same installation and software version. If that port belongs to another program, a new bridge tries the next free port, up to ten candidates, and opens the matching URL. It does not install Python silently or run as a background system service. Closing the bridge terminal stops the local app connection.

If Python is missing, the Windows launcher explains where to install it. The Windows launcher was source-reviewed; it has not been executed on a Windows machine in this environment.

For manual startup or macOS/Linux:

```sh
python3 local/launcher.py
```

A verified model-specific adapter can be installed as `local/receiver_adapter.py`; the launcher loads that trusted Python file when starting a new bridge. The built-in `local/gmscreen.py` ALi adapter loads by default; a custom adapter overrides it. Restart the bridge after adding or changing an adapter.

## What works now

| Function | This release |
| --- | --- |
| Channel search, rename, delete, move, sort, favorites, lock | Requires connected, compatible receiver adapter; writes require acknowledgement |
| Channel switching | Requires connected receiver tuning adapter |
| Video playback | HTTP(S) MP4/WebM with browser-supported codecs; HLS only with native browser HLS support |
| EPG | Only EPG returned by the receiver; no fallback guide |
| Remote buttons and keyboard | Requires connected adapter and command acknowledgement |
| Touchpad | Swipes and taps translated to remote keys |
| Gyroscope | Optional device orientation permission; supported secure mobile contexts only; requires real adapter for STB control |
| Timers | Only receiver-stored timers; requires compatible adapter |
| Sleep, parental controls, screen lock, PIN, power, factory reset | Disabled without corresponding adapter capability; hardware verification outstanding |
| Incoming call notification | Scoped pairing + web alerts/video pause + iOS CallKit companion source; requires signed native build; no guaranteed background delivery or receiver OSD |
| SAT>IP | UPnP discovery, RTSP SETUP/PLAY/keepalive/TEARDOWN, UDP RTP reception and FFmpeg conversion to live MP4; real hardware untested |
| SatFinder | Only live signal measurements; unavailable without adapter; stale readings stop audio |
| DLNA | Local SSDP discovery + AVTransport SetAVTransportURI/Play + file serving; requires LAN mode and compatible TV; hardware untested |

Signal values start empty and are displayed exactly as returned by the receiver adapter. No dB-to-percentage formula is applied.

## Use a phone or DLNA TV on the same LAN

Find the computer's private IPv4 address with `ipconfig` on Windows. Example only:

```powershell
py local/bridge.py --bind 0.0.0.0 --lan-ip 192.168.1.50
```

Replace the example with the computer's address, not the STB's. Allow inbound port 8787 on the Windows **private** network profile. Open `http://192.168.1.50:8787` from the phone. In Connection settings use that same address; `127.0.0.1` on a phone means the phone itself.

In Media & DLNA, select a file, Find TVs, select the renderer, then Send. The bridge uploads at most 100 MB per file and serves it from a random temporary URL for up to two hours. Total temporary storage is capped at approximately 500 MB; files are removed at bridge shutdown. The TV must be able to reach the computer. TVs differ in codec, DLNA metadata and playback support; sending a command does not guarantee that every format plays. Discovery may be blocked by guest Wi-Fi/client isolation or firewall rules.

Motion control often requires HTTPS on mobile browsers, so plain LAN HTTP may not expose the sensor. Use the hosted HTTPS app with a compatible securely reachable bridge, or a trusted local HTTPS reverse proxy if motion is needed. Buttons and touchpad do not require sensors.

## Hosted app and local bridge

Browsers can block local HTTP access from an HTTPS page. Local-network permission and CORS support vary. The most reliable path is opening the app served by the bridge. To authorize the hosted origin explicitly:

```powershell
py local/bridge.py --origin https://alen-stb-control.xalenpepa2.chatgpt.site
```

This configures CORS, not a tunnel and not a bypass of browser restrictions. Do not expose the bridge port to the public Internet. On trusted LANs the HTTP token is sent without TLS; use a trusted reverse proxy if transport encryption is needed.

## Connect a real receiver adapter

The receiver model and exact firmware/protocol must be verified. The research found a historical, device-specific G-MScreen/ALi reverse-engineering example; its command IDs are **not assumed valid for StarSat SR-230H4K**. Needed next: model/firmware, whether the official G-MScreen app connects successfully, and verified protocol documentation or an authorized local packet capture for ordinary control operations. Do not flash firmware to use this app.

Load a trusted adapter:

```powershell
py local/bridge.py --adapter local/my_receiver.py
```

The file must define `Adapter`. Each method returns a JSON-serializable object and must raise an error if the receiver rejects the operation. The bridge serializes adapter calls. It has no arbitrary raw-command endpoint. Device authentication, validation, timeouts and operation acknowledgements belong in the verified adapter.

`status()` returns:

```json
{"receiver":{"connected":true,"name":"Receiver model","protocol":"Verified protocol"},"capabilities":["channels.tune","channels.edit","epg","remote","timers","settings","password","power","factory-reset","signal","stream"]}
```

Only include implemented capabilities. `channels()` is required for connecting. Other functions are gated by capability.

| Method | Input / expected output |
| --- | --- |
| `channels()` | `{ "channels": [{"id":"stable-id","name":"Channel","category":"General","favorite":false,"locked":false,"quality":"HD"}] }` |
| `channel_tune(body)` | `{id}` → acknowledged `{ok:true}` |
| `channel_update(body)` | `{id,patch:{name?,favorite?,locked?}}` → ack; validate PIN/authorization for locks |
| `channel_delete(body)` | `{id}` → ack |
| `channel_order(body)` | `{ids:[...]}` complete ordered list → ack |
| `epg()` | `{programmes:[{channelId,channelName,title,start}]}` with ISO 8601 start |
| `remote(body)` | `{key}` such as UP, DOWN, LEFT, RIGHT, OK, VOL+, POWER → ack |
| `timers()` | `{timers:[{id,title,channelId,start,duration,type}]}`; start is an ISO 8601 timestamp with explicit timezone; new timers are submitted in UTC, and adapters must convert to receiver time |
| `timer_save(body)` / `timer_delete(body)` | complete timer / `{id}` → ack; type is `Switch channel` or `Record` |
| `settings()` / `settings_save(body)` | `{settings:{sleep:"0",parental:false,screenLock:false}}` / settings → ack |
| `password(body)` | `{current,next}` → ack after verifying current PIN |
| `power(body)` | `{mode:"on"}` or `{mode:"standby"}` → ack |
| `factory_reset(body)` | `{confirmation:"RESET"}` → ack |
| `signal()` | `{snr:13.2,strength:92,quality:71,locked:true}`; missing numeric values should be null |
| `stream(body)` | `{id}` → `{url:"https://.../browser-compatible-stream"}` |

`local/adapter_example.py` is a nonfunctional interface example; it intentionally reports disconnected.

## State and remaining limitations

Receiver channels, EPG, timers and settings come only from a connected adapter. No receiver data is seeded or persisted as a browser-local substitute. Old demo storage is deleted. Tokens and PINs are not persisted. Both the frontend and bridge reject unacknowledged writes; adapters must return `{ok:true}` only after a real receiver acknowledgement. Missing adapter methods or capabilities return errors, not success.

Version 0.7 includes a limited G-MScreen ALi adapter, RTSP-to-browser conversion and iOS companion source. G-MScreen editing, remote keys, EPG, timers, settings and receiver OSD notifications are not implemented for the built-in variant. The iOS source is not compiled or signed here. A reachable TCP port is not a verified control connection. Physical STB/TV playback, tuner readings, timer execution and power behavior remain untested. The software is not claimed to be 100% complete or compatible.

## Validation

JavaScript syntax and gateway Python compilation checked. Isolated client logic tests verify empty startup, disconnected views, capability gating and acknowledgement enforcement. Gateway tests also reject missing receiver acknowledgements and invalid DLNA SOAP responses. Local HTTP tests verify authentication, origin rejection, discovery status, static serving and explicit unsupported-operation errors. No physical receiver/TV was reachable in the build environment. Browser UI and proposed WebMCP integration could not be validated in a supported live browser context here.

## Research reference

Historical G-MScreen reverse engineering for an ABcom receiver (not a StarSat compatibility guarantee):
https://gist.github.com/gabonator/2c8885127cf6e0954c24e5d698ff99b6

## Version 0.2 — custom receiver ports and new design

Connection studio now separates the local bridge URL from the receiver IP and TCP port. Both the bridge listening port (`--port`) and receiver target port accept **1–65535**. This does not make closed ports accessible or provide a universal G-MScreen protocol.

1. Run the updated bridge and paste its token into Connection studio.
2. Enter the receiver's private LAN IPv4 address and its configured service port.
3. Select **Test this TCP port**. The bridge attempts exactly one TCP connection, without sending protocol commands or scanning other ports. A successful result means only that the port accepted a TCP connection.
4. Select **Connect** to save the target for this bridge session and pass it to a compatible adapter. Without an adapter, the app reports “endpoint saved” and keeps receiver controls disconnected.

Optional command line setup:

```powershell
py local/bridge.py --port 8787 --stb-ip 192.168.1.100 --stb-port 20000
```

These are example addresses and ports, not detected settings. The UI offers example shortcuts (20000, 554, 80, 8080), and accepts any valid custom number. UDP-only services are not verified by a TCP test. Browser direct access to certain ports may be restricted; receiver TCP access happens through the local bridge.

Adapters implementing custom endpoints must add `configure(target)` where `target` is `{host, port}`. Apply the configuration or raise an error. Only report `receiver.connected: true` after a verified device protocol handshake, never solely from an open TCP port. Existing adapters without `configure` are not claimed to have applied the new endpoint.

New API routes (token and origin checks required):

- `POST /api/receiver/probe` with `{host,port}` → reachability, elapsed milliseconds and `protocolVerified:false`.
- `POST /api/receiver/configure` with `{host,port}` → session target and `adapterConfigured`.

Targets must use RFC1918 IPv4 ranges. Public, loopback, multicast, unspecified and hostnames are rejected. Port boundaries and adapter handoff are covered by local tests. No physical STB compatibility has been confirmed.

## Version 0.4 — reliability and maintainability

- `dist/core.js`: shared response validation, timezone conversion, secure identifier fallback and abortable connection sessions.
- `local/validation.py`: command schema checks and receiver response validation before data reaches the UI.
- Connection changes discard late replies. A failed authorization or disconnected receiver clears active receiver state. Writes are never automatically retried.
- Channel lists reject duplicate IDs and invalid lock flags. Signal values reject non-finite data; missing values remain unavailable.
- Timers edit in the browser local timezone and are submitted in UTC, including the EPG programme start time. `crypto.getRandomValues` provides a secure identifier fallback for LAN HTTP browsers without `randomUUID`.
- Mutating forms reject duplicate submission. Remote writes reject concurrent operations rather than sending two commands at once.
- Closing or replacing the video dialog releases the media source; late playback callbacks no longer address removed elements. Empty stream URLs are rejected.
- Uploads reserve disk quota before receiving data, preventing concurrent uploads from exceeding the configured quota. SVG and other active document formats are rejected.
- Static assets use no-store headers in the local gateway. HEAD requests cannot trigger API discovery.

Run the checks from the extracted directory:

```powershell
node --test local/test_core.cjs
node local/test_client.cjs
py -m unittest discover -s local -p "test_*.py"
```

The Node checks are optional development checks; Node is not required to run the Python bridge. Tests exercise client logic and local HTTP behavior using isolated test doubles. They are not proof of physical G-MScreen compatibility or browser layout verification. No demonstrations or test fixtures are loaded into the application.

## Version 0.5 — automatic bridge pairing

`POST /api/bootstrap` provides a session token only to a loopback client, using the exact bridge origin, a custom bootstrap header and compatible Fetch Metadata headers. Cross-origin requests, including explicitly CORS-allowed hosted origins, cannot bootstrap. Local HTML cannot be framed by another page. The token remains in memory and is not saved in URLs or browser storage.

The public/hosted Site cannot silently install or start a native process, and does not probe private addresses automatically. It offers the package download and a link to an already-running local app. For phone/LAN access or hosted-to-local access, the existing explicit-token flow remains available under Advanced options. Automatic pairing does not bypass G-MScreen device authentication and does not make a receiver connected just because the bridge is running.

A computer bridge is still required. This release automates starting it and pairing the locally served browser app; it does not eliminate the native runtime.

## Version 0.6 — connection and discovery fixes

- Cancelling a connection invalidates pending automatic pairing, including delayed JSON responses. Failed re-pairing clears stale connected state.
- The launcher recognizes its own installation and version on ports 8787–8796, preventing reuse of an older or unrelated installation.
- UPnP discovery resolves relative control URLs against the device URLBase and rejects redirects to a different device address.
- Missing or malformed Host headers and non-ASCII authorization values are rejected cleanly.
- Validation: 6 core JavaScript tests, 25 Python tests, and the client regression script passed. These are isolated software and local HTTP checks; hardware, Windows execution and live browser UI remain unverified.

## Version 0.7 — protocol integrations

### G-MScreen ALi adapter

The default adapter performs the documented 108-byte ALi handshake, reads GCDH headers with exact-length TCP reads, decompresses bounded zlib responses and loads the reported channel count in batches. It requires real device information; opening a TCP port is insufficient. Channel-list mismatches fail explicitly. It periodically refreshes device information and disconnects on protocol errors.

Selecting a channel with this limited adapter selects it for local streaming; it does **not** change the receiver's HDMI channel. Only custom adapters with verified tuning commands can do that. Locked or unknown-lock channels and encrypted channels are not streamed by this adapter. It builds ALi stream parameters from channel/transponder responses. The bundled implementation does not guess remote/edit/reset command IDs and does not bypass device authentication or conditional access.

This is the documented ALi protocol variant, not a universal G-MScreen adapter. If the SR-230H4K handshake or channel list differs, the next required input is a normal-control capture from the official G-MScreen app on your own LAN or protocol documentation for that firmware. No firmware modification is needed.

Protocol research (independent implementation):
https://gist.github.com/gabonator/46666c006df7fd1b64650847e2560074

### SAT>IP viewing

1. Install an FFmpeg build with libx264 and AAC on PATH, or put its executable in `bin/` (see that directory's README).
2. Start the bridge. In Device integrations, Check setup confirms whether FFmpeg is present.
3. Tune & watch accepts the server LAN IP, any valid RTSP port, frequency in MHz, symbol rate in kSym/s, polarization, DVB-S/S2, DiSEqC source, PIDs and programme number. Values must match the actual transponder. Programme 0 selects the first service; use the real service number for a multiplex with several channels.
4. Alternatively, connect the G-MScreen ALi adapter and select Watch channel to derive parameters from the device.

The bridge requests RTSP unicast UDP, binds an even RTP port and its RTCP partner, validates MPEG-TS RTP packets from the server IP and feeds their payload into FFmpeg. It converts to H.264/AAC fragmented MP4, limited to 1280-pixel width. Playback is bounded to one stream, with expiring single-use media links, no-media/startup timeouts and RTSP keepalive/teardown. Closing the player stops the process. Live seeking is not provided. A session ends after four hours and can be restarted.

A SAT>IP server and correctly configured tuner are required. This is UDP SAT>IP, not support for every generic RTSP camera or proprietary Sat2IP firmware. RTCP quality reporting and DVB-T/C tuning are not implemented. The firewall must permit incoming RTP on the private network. Wi-Fi throughput and packet loss affect playback. FFmpeg binaries are not bundled. Encrypted transports are not decrypted by this app.

FFmpeg reference: https://ffmpeg.org/ffmpeg-protocols.html
SAT>IP server reference: https://github.com/catalinii/minisatip

### Incoming calls

Use `Start-Alen-STB-LAN.cmd` for a phone connection; it detects the PC address automatically. The ordinary launcher stays loopback-only. Open Device integrations → Pair iPhone and follow `companion/ios/README.md`. The iOS companion requires a Mac/Xcode build and Apple signing. Its source is included, not a ready-to-install IPA. iOS suspension prevents any guarantee of background call delivery. Alerts pause the web player and show in Alen STB; they do not change the receiver TV menu.

### Verification and boundaries

Tests include real loopback TCP framing, fragmented G-MScreen replies, RTSP negotiation with a local test server, actual RTP packets and an installed FFmpeg producing MP4, companion-token scope and duplicate-event handling. Test fixtures exist only in the test suite and are never served as application data. These checks do not establish SR-230H4K compatibility, iOS compilation, physical tuner behavior or browser playback on every device.

For a read-only compatibility report on your LAN, run `py local/diagnose.py --host YOUR_RECEIVER_IP --port 20000`. It writes `alen-stb-diagnostics.json` containing model, firmware, channel field names and any protocol error; it excludes IP, serial number, channel names and credentials. This report helps adapt the implementation to your actual firmware without guessing commands.

Release checks: 34 Python tests, 6 JavaScript core tests and the client regression script passed. The extracted ZIP was also started and its default adapter/bootstrap endpoints checked locally.


## Version 0.8 — English, Albanian and German

The header language selector offers Shqip, English and Deutsch. Selection is saved locally and applies immediately without reloading or rebuilding open forms and video elements. On first use, a supported browser language is selected; other languages fall back to English. Menus, dialogs, setup guidance, app-owned validation/status/error messages, placeholders and accessibility labels are localized. Dates and numbers use the selected locale. Protocol identifiers and values submitted to receivers stay unchanged.

Receiver channel names, programme titles, device names, user-entered data and technical identifiers are not translated. Browser/OS-provided media controls and third-party device/operating-system diagnostic messages can use the browser/OS/device language.

The iOS companion source also has a persistent language picker and en/sq/de resource bundles. It still requires an Xcode build and signing; its native UI has not been tested on a physical iPhone here.

Maintain translations in `local/i18n-tools/catalog.tsv`, then run `python3 local/i18n-tools/build.py`. It generates the web catalog and native iOS string resources. Run `node --test local/test_i18n.cjs` to check language coverage, saved preferences, dynamic messages, dates and unchanged protocol values. These tests use a DOM test harness, not a full browser layout engine.

Copyright © 2026 Alen Pepa. Copyright headers are included in project code, scripts and generated localization resources. Existing protocol references and attributions are retained.

The footer displays `Copyright © 2026 Alen Pepa` in every language. Packaging checks this notice before creating the ZIP and fails if it is removed or changed. Run `python3 local/package.py` before publishing. This prevents accidental removal in this workflow; it cannot prevent a source-code owner from editing the notice or the validation code.

## Version 0.8.3 — reliability fixes

Cancelled or superseded playback releases SAT>IP tickets against the originating bridge. A late playback response cannot replace a newer dialog. Phone events continue when native browser notifications or permission requests fail, and ending one of several incoming calls does not hide the other call's banner. The FFmpeg input writer preserves complete packets even when a pipe accepts partial writes. Local JavaScript, CSS and HTML have explicit UTF-8 MIME types, independent of Windows file associations.

Validation includes Python bridge/protocol tests, JavaScript client/localization tests and a loopback RTSP/RTP-to-FFmpeg test producing real fragmented MP4. Test fixtures run only under tests. These checks do not verify a physical StarSat receiver, DLNA TV or signed iPhone build. The bundled G-MScreen adapter's unsupported capabilities remain disabled; this release does not claim universal receiver compatibility.
