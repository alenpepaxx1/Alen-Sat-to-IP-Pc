// Copyright © 2026 Alen Pepa.
import SwiftUI
import CallKit
import UIKit

@MainActor
final class CallRelay: NSObject, ObservableObject, CXCallObserverDelegate {
    @Published var language: String = {
        let saved = UserDefaults.standard.string(forKey: "alen-language")
        let device = String(Locale.preferredLanguages.first?.prefix(2) ?? "en")
        return ["en", "sq", "de"].contains(saved ?? device) ? (saved ?? device) : "en"
    }() {
        didSet { UserDefaults.standard.set(language, forKey: "alen-language") }
    }
    func tr(_ key: String) -> String {
        guard let path = Bundle.main.path(forResource: language, ofType: "lproj"), let bundle = Bundle(path: path) else { return key }
        return bundle.localizedString(forKey: key, value: key, table: nil)
    }
    var localizedStatus: String {
        for prefix in ["Delivered: ", "Call notification failed: "] where status.hasPrefix(prefix) {
            return tr(prefix) + tr(String(status.dropFirst(prefix.count)))
        }
        return tr(status)
    }
    @Published var address = ""
    @Published var code = ""
    @Published var status = "Enter the computer's LAN address and the pairing code shown in Alen STB."
    @Published var paired = false
    private let observer = CXCallObserver()
    private var base: URL?
    private var token = ""
    private var sequence = 0
    private var previous: [UUID: String] = [:]
    private var pending: Task<Void, Never>?
    private var generation = UUID()

    override init() {
        super.init()
        observer.setDelegate(self, queue: .main)
    }

    private func bridgeURL() throws -> URL {
        guard let url = URL(string: address.trimmingCharacters(in: .whitespacesAndNewlines)),
              url.scheme == "http", url.user == nil, url.password == nil,
              url.query == nil, url.fragment == nil, url.path.isEmpty || url.path == "/",
              let host = url.host else { throw RelayError.message("Use http://COMPUTER-LAN-IP:8787") }
        let parts = host.split(separator: ".", omittingEmptySubsequences: false)
        let octets = parts.compactMap { Int($0) }
        guard octets.count == 4, parts.count == 4, octets.allSatisfy({ (0...255).contains($0) }),
              octets[0] == 10 || (octets[0] == 192 && octets[1] == 168) || (octets[0] == 172 && (16...31).contains(octets[1])),
              (1...65535).contains(url.port ?? 80)
        else { throw RelayError.message("Use the computer's private LAN IPv4 address.") }
        return url
    }

    private func post(_ root: URL, _ path: String, _ body: [String: Any], bearer: String = "") async throws -> [String: Any] {
        var request = URLRequest(url: root.appendingPathComponent(path), timeoutInterval: 8)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        if !bearer.isEmpty { request.setValue("Bearer " + bearer, forHTTPHeaderField: "Authorization") }
        request.httpBody = try JSONSerialization.data(withJSONObject: body)
        let (data, response) = try await URLSession.shared.data(for: request)
        let value = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] ?? [:]
        guard let http = response as? HTTPURLResponse, http.statusCode == 200 else {
            throw RelayError.message(value["error"] as? String ?? "The bridge could not accept the request.")
        }
        return value
    }

    func pair() async {
        let attempt = UUID()
        generation = attempt
        paired = false
        token = ""
        do {
            let root = try bridgeURL()
            let result = try await post(root, "api/calls/claim", ["code": code])
            guard generation == attempt else { return }
            guard let received = result["token"] as? String else { throw RelayError.message("Invalid pairing response.") }
            base = root; token = received; sequence = 0; previous = [:]; paired = true; code = ""
            status = "Paired for this session. Keep Alen Calls open. iOS does not guarantee call monitoring while suspended."
            refresh()
        } catch { if generation == attempt { status = error.localizedDescription } }
    }

    func disconnect() {
        generation = UUID(); paired = false; token = ""; previous = [:]
        status = "Disconnected. Use Revoke phone in Alen STB to invalidate the phone token immediately."
    }

    func refresh() {
        for call in observer.calls { handle(call) }
    }

    nonisolated func callObserver(_ callObserver: CXCallObserver, callChanged call: CXCall) {
        Task { @MainActor in self.handle(call) }
    }

    private func handle(_ call: CXCall) {
        guard paired, !call.isOutgoing, let root = base else { return }
        let phase = call.hasEnded ? "ended" : call.hasConnected ? "connected" : "ringing"
        guard previous[call.uuid] != phase else { return }
        previous[call.uuid] = phase
        if previous.count > 64 { previous = [call.uuid: phase] }
        sequence += 1
        let body: [String: Any] = ["sequence": sequence, "callId": call.uuid.uuidString, "state": phase]
        let secret = token, epoch = generation, earlier = pending
        // Finish an already delivered callback; this does not create continuous background monitoring.
        var background = UIBackgroundTaskIdentifier.invalid
        background = UIApplication.shared.beginBackgroundTask(withName: "Relay call state") {
            if background != .invalid { UIApplication.shared.endBackgroundTask(background); background = .invalid }
        }
        pending = Task {
            defer { if background != .invalid { UIApplication.shared.endBackgroundTask(background) } }
            await earlier?.value
            guard generation == epoch else { return }
            do {
                let value = try await post(root, "api/calls/event", body, bearer: secret)
                guard value["ok"] as? Bool == true else { throw RelayError.message("Event was not acknowledged.") }
                if generation == epoch { status = "Delivered: " + phase }
            } catch {
                if generation == epoch { status = "Call notification failed: " + error.localizedDescription }
            }
        }
    }
}

enum RelayError: LocalizedError {
    case message(String)
    var errorDescription: String? { if case .message(let text) = self { return text }; return nil }
}

@main
struct AlenCallsApp: App {
    @StateObject private var relay = CallRelay()
    @Environment(\.scenePhase) private var phase
    var body: some Scene {
        WindowGroup {
            NavigationStack {
                Form {
                    Section {
                        Picker("Language", selection: $relay.language) {
                            Text(verbatim: "Shqip").tag("sq")
                            Text(verbatim: "English").tag("en")
                            Text(verbatim: "Deutsch").tag("de")
                        }
                    }
                    Section("Local bridge") {
                        TextField("http://192.168.1.50:8787", text: $relay.address)
                            .keyboardType(.URL).textInputAutocapitalization(.never).autocorrectionDisabled()
                        SecureField("8-digit pairing code", text: $relay.code).keyboardType(.numberPad)
                        Button("Pair iPhone") { Task { await relay.pair() } }.disabled(relay.paired)
                        if relay.paired { Button("Disconnect") { relay.disconnect() } }
                    }
                    Section("Status") { Text(relay.localizedStatus) }
                    Section("How it works") {
                        Text("Only call state is sent over your local Wi-Fi. No phone numbers, contacts or audio are read. Open Alen STB on your computer and enable call alerts. The bridge must run in LAN mode.")
                        Text("This companion must be running. A closed or suspended iOS app cannot guarantee delivery. This does not display an alert in the receiver's own TV menu.")
                    }
                }.navigationTitle("Alen Calls")
            }.environment(\.locale, Locale(identifier: relay.language)).onChange(of: phase) { value in if value == .active { relay.refresh() } }
        }
    }
}
