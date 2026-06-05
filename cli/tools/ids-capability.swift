// ids-capability — iMessage capability probe (the iPhone's blue/green check).
//
// Queries Apple's Identity Services daemon (identityservicesd) through the IDS
// framework's IDSIDQueryController for a handle's iMessage registration status
// on the `com.apple.madrid` service (iMessage). This is the SAME source the
// iPhone and Messages.app use to decide blue vs green — so it answers for
// NUMBERS WITH NO MESSAGE HISTORY, which history-based detection cannot.
//
// Read-only. No SIP changes. No injection into Messages.app (unlike the
// IMCore-bridge `imsg whois`, which needs SIP disabled). It only reads the IDS
// status cache and, for uncached handles, asks the daemon for a live lookup.
//
// Usage:   ids-capability "tel:+15551234567"
//          ids-capability "mailto:person@icloud.com"
// Output:  {"address":"tel:+15551234567","idstatus":2,"transport":"sms"}
//          idstatus 1 = iMessage-capable, 2 = not (SMS), 0 = unknown/timeout.
//
// Build:   swiftc -O ids-capability.swift -o ids-capability
//
// Private-API caveat: IDSIDQueryController is a private framework class. It
// works today but a future macOS could change it; callers MUST treat a missing
// binary / nonzero exit / "unknown" as "fall back to the SMS default", never as
// a hard failure.

import Foundation

guard dlopen("/System/Library/PrivateFrameworks/IDS.framework/IDS", RTLD_NOW) != nil else {
    print("{\"error\":\"dlopen failed\"}"); exit(2)
}
guard let cls = NSClassFromString("IDSIDQueryController") as? NSObject.Type else {
    print("{\"error\":\"no IDSIDQueryController\"}"); exit(2)
}
let shared = cls.perform(NSSelectorFromString("sharedInstance")).takeUnretainedValue() as! NSObject

let dest = CommandLine.arguments.count > 1 ? CommandLine.arguments[1] : ""
if dest.isEmpty { print("{\"error\":\"no destination\"}"); exit(2) }
let svc = "com.apple.madrid"  // iMessage

typealias RFn = @convention(c)(NSObject, Selector, NSArray, NSString, NSString) -> Void
typealias CFn = @convention(c)(NSObject, Selector, NSString, NSString, NSString) -> Int64
let rsel = NSSelectorFromString("_refreshIDStatusForDestinations:service:listenerID:")
let csel = NSSelectorFromString("_currentIDStatusForDestination:service:listenerID:")
let cfn = unsafeBitCast(shared.method(for: csel), to: CFn.self)

func cur() -> Int64 { cfn(shared, csel, dest as NSString, svc as NSString, "elevate" as NSString) }

var status = cur()
if status == 0 {  // not cached — force a live daemon lookup, then poll
    if shared.responds(to: rsel) {
        let rfn = unsafeBitCast(shared.method(for: rsel), to: RFn.self)
        rfn(shared, rsel, [dest] as NSArray, svc as NSString, "elevate" as NSString)
    }
    let deadline = Date().addingTimeInterval(10)
    while status == 0 && Date() < deadline {
        Thread.sleep(forTimeInterval: 0.4)
        status = cur()
    }
}

let transport = status == 1 ? "imessage" : (status == 2 ? "sms" : "unknown")
print("{\"address\":\"\(dest)\",\"idstatus\":\(status),\"transport\":\"\(transport)\"}")
