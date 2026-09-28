# Alen Calls · iPhone companion source

This directory contains native SwiftUI/CallKit source and an XcodeGen project definition. It is **not a signed IPA**. It has not been compiled or tested on an iPhone in this Linux environment.

## Build on a Mac

1. Install Xcode and XcodeGen (https://github.com/yonaskolb/XcodeGen).
2. In this directory run `xcodegen generate`.
3. Open `AlenCalls.xcodeproj`, choose your Apple signing team, select your connected iPhone and run. Change the bundle identifier if your signing team requires it.
4. Grant Local Network access when iOS asks. No contacts, microphone or phone-number permission is needed.

A Windows PC cannot sign/install this iOS project by itself. Apple signing and a Mac/Xcode build are required; there is no bundled App Store/TestFlight release.

## Connect

1. On Windows, close any old bridge and open `Start-Alen-STB-LAN.cmd`. It detects the computer's private IPv4 address using the routing table, without scanning the LAN. Allow the Python bridge on the private network in Windows Firewall.
2. On macOS/Linux: `python3 local/launcher.py --lan`. With multiple interfaces/VPNs select explicitly: `python3 local/launcher.py --lan-ip 192.168.1.50` (replace with your computer IP).
3. In the local web app, open Device integrations → Pair iPhone.
4. Enter the shown address and eight-digit code in Alen Calls, then Pair iPhone. The code expires in two minutes, is single-use, and locks after eight wrong attempts.
5. In the web app click Enable alerts here. Keep both apps running on the same LAN.

Incoming call state appears in the web app, which pauses its own video. Only the call UUID and ringing/connected/ended state are sent. No caller number, contacts or audio are read. The companion token can only submit call events; it cannot control the receiver. It expires in 12 hours or when the bridge restarts. Revoke phone immediately invalidates it. Tokens are kept in memory.

## iOS limitation

`CXCallObserver` reports system call changes while the companion runs. iOS may suspend an app in the background; this app does not claim continuous background monitoring and does not misuse VoIP/audio background modes. A short background task finishes callbacks already received. Foreground activation rechecks current calls. Failed deliveries are shown in the native status field; there is no fake success or test-call button.

Alerts are displayed in Alen STB, not in the receiver firmware's TV menu. That requires a documented receiver notification command. Browser background throttling and notification support can delay desktop alerts; keep the web app visible for timely polling.

References:
- https://developer.apple.com/documentation/callkit/cxcallobserver
- https://developer.apple.com/documentation/uikit/extending-your-app-s-background-execution-time

## Languages

The in-app picker supports Shqip, English and Deutsch and remembers the choice. All app-owned labels/status text and local-network permission descriptions have localized resources. System and network diagnostics may follow the iOS language.
