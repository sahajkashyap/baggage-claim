// Baggage Claim's small helper app for launchd, the part of macOS that starts
// things at login and restarts them if they stop.
//
// Why it exists: macOS only shows the question "may this program read files in
// your Google Drive folder?" to a real app. A plain script or python started in
// the background by launchd is refused silently and never asked (proven on
// September 26, 2026: the same folder listing was denied from `/bin/zsh`, and
// waited for the Allow dialog from this app). So launchd starts this app, this
// app runs watch.sh as its child, and the child inherits the permission.
//
// It passes Stop signals on to the watcher and exits when the watcher exits,
// so launchd's KeepAlive sees a crash and starts it again.
//
// Build (Setup.command does this when it can, GitHub Actions does it for the
// one-click bundle):  swiftc -O mac/launcher.swift -o "Baggage Claim.app/Contents/MacOS/Baggage Claim"
import Foundation

let me = Bundle.main.executableURL ?? URL(fileURLWithPath: CommandLine.arguments[0]).standardizedFileURL
// .../Baggage Claim.app/Contents/MacOS/Baggage Claim  ->  the folder the .app sits in
let toolDir = me.deletingLastPathComponent().deletingLastPathComponent()
    .deletingLastPathComponent().deletingLastPathComponent()

var args = Array(CommandLine.arguments.dropFirst())
if args.isEmpty {
    args = ["/bin/zsh", toolDir.appendingPathComponent("watch.sh").path]
}

let child = Process()
child.executableURL = URL(fileURLWithPath: args[0])
child.arguments = Array(args.dropFirst())
child.currentDirectoryURL = toolDir
child.terminationHandler = { p in
    // a watcher killed by a signal is a crash: report it as a failure so launchd restarts us
    exit(p.terminationReason == .exit ? p.terminationStatus : 128 + p.terminationStatus)
}

var signalSources: [DispatchSourceSignal] = []
for sig in [SIGTERM, SIGINT, SIGHUP] {
    signal(sig, SIG_IGN)
    let src = DispatchSource.makeSignalSource(signal: sig, queue: DispatchQueue.global())
    src.setEventHandler {
        if child.isRunning { kill(child.processIdentifier, sig) }
    }
    src.resume()
    signalSources.append(src)
}

do {
    try child.run()
} catch {
    let msg = "Baggage Claim could not start \(args[0]): \(error.localizedDescription)\n"
    FileHandle.standardError.write(msg.data(using: .utf8)!)
    exit(1)
}
dispatchMain()
