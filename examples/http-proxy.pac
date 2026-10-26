// Local browser PAC example only. Requires the repository's HTTP proxy to be running.
// No DIRECT fallback for public destinations: a stopped proxy should fail visibly.
function FindProxyForURL(url, host) {
    if (host === "localhost" || host === "127.0.0.1" || host === "::1") {
        return "DIRECT";
    }
    return "PROXY 127.0.0.1:10809";
}
