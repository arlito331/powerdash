#!/usr/bin/env python3
"""One-time: mint a Gmail refresh token for PowerDash.

PotholeRadar already sends mail this way, so the client id and secret exist
already — they are in the client_secret_*.json in APPS/KEYS. Only the refresh
token is missing, because GitHub never shows a secret back to you.

Run it, approve the Google screen that opens, and it prints the three values to
paste into the repo secrets:

    python3 tools/gmail-setup.py

Nothing is written to disk and nothing leaves your Mac except the sign-in.
"""
import glob, http.server, json, os, socket, sys, threading, time
import urllib.parse, urllib.request, webbrowser

SCOPE = "https://www.googleapis.com/auth/gmail.send"
DEFAULT_KEYS = os.path.expanduser("~/Dropbox/PowerFix/APPS/KEYS")


def find_client_secret(path=None):
    if path:
        return path
    hits = sorted(glob.glob(os.path.join(DEFAULT_KEYS, "client_secret_*.json")))
    if not hits:
        sys.exit(f"No client_secret_*.json found in {DEFAULT_KEYS}.\n"
                 f"Pass the path: python3 tools/gmail-setup.py /path/to/client_secret.json")
    return hits[0]


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def main():
    args = [a for a in sys.argv[1:] if a not in ("-h", "--help")]
    if len(args) != len(sys.argv[1:]):
        print(__doc__)
        return
    path = find_client_secret(args[0] if args else None)
    conf = json.load(open(path))
    conf = conf.get("installed") or conf.get("web") or conf
    client_id, client_secret = conf["client_id"], conf["client_secret"]

    port = free_port()
    redirect = f"http://127.0.0.1:{port}"
    auth_url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode({
        "client_id": client_id, "redirect_uri": redirect, "response_type": "code",
        "scope": SCOPE, "access_type": "offline", "prompt": "consent",
    })

    box = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            box.update({k: v[0] for k, v in q.items()})
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            done = "code" in box
            self.wfile.write(
                b"<body style='font:16px -apple-system;padding:40px;background:#0D0D0D;color:#f5f5f7'>"
                + (b"<h2>Done.</h2><p>Close this tab and go back to the Terminal.</p>" if done
                   else b"<h2>Something went wrong.</h2><p>Go back to the Terminal.</p>")
                + b"</body>")

        def log_message(self, *a):
            pass

    server = http.server.HTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=server.handle_request, daemon=True).start()

    print("Opening Google in your browser…")
    print("Sign in as the address the mail should come FROM.")
    print('If it warns the app is not verified: Advanced -> Go to ... (unsafe). It is your own app.\n')
    if not webbrowser.open(auth_url):
        print("Open this link yourself:\n" + auth_url + "\n")

    for _ in range(600):          # wait up to five minutes for the approval
        if box:
            break
        time.sleep(0.5)
    if "code" not in box:
        sys.exit("No approval came back. Run it again.")

    data = urllib.parse.urlencode({
        "code": box["code"], "client_id": client_id, "client_secret": client_secret,
        "redirect_uri": redirect, "grant_type": "authorization_code",
    }).encode()
    with urllib.request.urlopen("https://oauth2.googleapis.com/token", data=data, timeout=30) as r:
        tok = json.loads(r.read())
    if "refresh_token" not in tok:
        sys.exit("Google did not return a refresh token. Remove PowerDash at "
                 "myaccount.google.com/permissions and run this again.")

    print("\n" + "=" * 66)
    print("Paste these into github.com/arlito331/powerdash -> Settings ->")
    print("Secrets and variables -> Actions -> New repository secret")
    print("=" * 66)
    for name, value in (("GMAIL_CLIENT_ID", client_id),
                        ("GMAIL_CLIENT_SECRET", client_secret),
                        ("GMAIL_REFRESH_TOKEN", tok["refresh_token"])):
        print(f"\n{name}\n{value}")
    print("\nAlso add MAIL_TO with the addresses that should receive it.")
    print("Do not paste these values into a chat window.\n")


if __name__ == "__main__":
    main()
