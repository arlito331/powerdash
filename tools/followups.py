#!/usr/bin/env python3
"""PowerDash follow-up notifier.

Reads data/leads.json, works out what is due using the same rule as the web
app (an explicit due date wins; otherwise the 15/30/45-day cadence counts from
the last contact), and emails it. Run by GitHub Actions on a schedule, or by
hand:

    python3 tools/followups.py due        # print the follow-up email
    python3 tools/followups.py factory    # print the factory report
    python3 tools/followups.py standing   # print the internal standing
    python3 tools/followups.py due --send # send it by email

Email needs these environment variables (GitHub repo secrets in CI):
    SMTP_HOST (default smtp.gmail.com), SMTP_PORT (default 587),
    SMTP_USER, SMTP_PASS, MAIL_TO (comma-separated), MAIL_FROM (optional)
"""
import json, os, smtplib, sys, urllib.error
from datetime import date, datetime, timedelta
from email.message import EmailMessage
from pathlib import Path

MILESTONES = [15, 30, 45]
ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "leads.json"      # only on a dev machine
ENC = ROOT / "data" / "leads.enc"       # what the repo actually holds

STAGES = {
    "prospect":  ("Not contacted", "none"),
    "contacted": ("Contacted", "us"),
    "sample":    ("Sample / demo", "us"),
    "trial":     ("Trial in progress", "them"),
    "results":   ("Waiting for results", "them"),
    "quote":     ("Quote sent", "them"),
    "contract":  ("Contract sent", "them"),
    "signed":    ("Signed", "us"),
    "payment":   ("Payment pending", "them"),
    "active":    ("Delivered / active", "us"),
    "parked":    ("Parked / cold", "none"),
}
QUIET = ("parked", "prospect")      # nothing is expected of us there
TODAY = date.today()


def d(iso):
    return datetime.strptime(iso, "%Y-%m-%d").date() if iso else None


def stage_label(lead):
    return STAGES.get(lead.get("stage", "contacted"), ("Contacted", "us"))[0]


def waiting_on(lead):
    return lead.get("waiting_on") or STAGES.get(lead.get("stage", "contacted"), ("", "us"))[1]


def due_info(lead):
    """-> (state, days, label). Mirrors dueInfo() in index.html."""
    if lead.get("stage") in QUIET:
        return "calm", 0, "Parked" if lead.get("stage") == "parked" else "Not approached yet"
    nd = d(lead.get("next_date"))
    if nd:
        u = (nd - TODAY).days
        act = lead.get("next_action") or "Next step not written down"
        if u < 0:
            return "overdue", -u, act
        if u == 0:
            return "today", 0, act
        return ("soon" if u <= 7 else "calm"), u, act
    lc = d(lead.get("last_contact"))
    if lc:
        n = (TODAY - lc).days
        passed = max([m for m in MILESTONES if n >= m], default=None)
        if passed == 45:
            return "overdue", n - 45, f"Quiet {n} days — push it or park it"
        if passed:
            return "overdue", n - passed, f"{passed}-day follow-up (quiet {n} days)"
        u = MILESTONES[0] - n
        return ("soon" if u <= 7 else "calm"), u, lead.get("next_action") or f"15-day follow-up in {u} days"
    return "overdue", 0, "No next action and no last contact — decide something"


def decrypt(blob):
    """The repo holds AES-256-GCM ciphertext (iv || ct). The key is the same
    master key the browser gets from your password; here it comes from the
    POWERDASH_KEY secret, base64, so the job can read the leads without one."""
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError:
        fail("needs the cryptography package: pip install cryptography")
    import base64, binascii
    key = clean(cfg("powerdash_key"))
    if not key:
        fail("POWERDASH_KEY is not set. Add the repo secret — its value is the "
             "single line inside APPS/KEYS/powerdash-master-key.txt")
    key = key.split()[-1]          # tolerate a pasted label or stray words
    try:
        raw = base64.b64decode(key, validate=True)
    except (binascii.Error, ValueError):
        fail(f"POWERDASH_KEY does not look like the key ({len(key)} characters read). "
             "Copy the one line from powerdash-master-key.txt, nothing else.")
    if len(raw) != 32:
        fail(f"POWERDASH_KEY decodes to {len(raw)} bytes, expected 32 — "
             "it is probably a different value than the key file.")
    try:
        return json.loads(AESGCM(raw).decrypt(blob[:12], blob[12:], None))
    except Exception:
        fail("POWERDASH_KEY does not open data/leads.enc — right shape, wrong key.")


def load():
    if ENC.exists():
        return decrypt(ENC.read_bytes())
    with open(DATA, encoding="utf-8") as f:
        return json.load(f)


def place(lead):
    bits = [b for b in (lead.get("city"), lead.get("country")) if b]
    return ", ".join(bits)


def nice(lead):
    city = lead.get("city")
    return f"{lead.get('name') or '(no name)'}" + (f" ({city})" if city else "")


def boxes_in(leads, stages):
    return round(sum(float(l.get("boxes") or 0) for l in leads if l.get("stage") in stages))


def report_due(leads):
    rank = {"overdue": 0, "today": 1, "soon": 2}
    items = []
    for l in leads:
        state, days, label = due_info(l)
        if state in rank:
            # late: most overdue first; upcoming: soonest first
            items.append((rank[state], -days if state == "overdue" else days,
                          state, days, label, l))
    items.sort(key=lambda x: (x[0], x[1]))
    if not items:
        return f"Follow-ups — {TODAY:%d %b}\n\nNothing due. Every lead has a date in the future."
    out = [f"Follow-ups due — {TODAY:%d %b %Y}", ""]
    late = sum(1 for i in items if i[2] == "overdue")
    out.append(f"{late} late, {sum(1 for i in items if i[2] == 'today')} today, "
               f"{sum(1 for i in items if i[2] == 'soon')} this week.")
    out.append("")
    for _, _, state, days, label, l in items:
        mark = "LATE" if state == "overdue" else "TODAY" if state == "today" else f"in {days}d"
        if state == "overdue" and days:
            mark = f"LATE {days}d"
        out.append(f"[{mark}] {nice(l)} · {stage_label(l)} · {l.get('owner') or '?'}")
        out.append(f"    {label}")
        if l.get("phone"):
            out.append(f"    {l['phone']}")
        out.append("")
    out.append("Open PowerDash to log what you did: https://powerdash.powerfixinc.com")
    return "\n".join(out)


def report_standing(leads):
    live = [l for l in leads if l.get("stage") not in QUIET]
    groups = {"overdue": [], "today": [], "soon": []}
    for l in leads:
        state, days, label = due_info(l)
        if state in groups:
            groups[state].append((days, label, l))
    out = [f"PowerFix — standing {TODAY:%d %b}", ""]
    titles = {"overdue": "LATE", "today": "TODAY", "soon": "THIS WEEK"}
    for key in ("overdue", "today", "soon"):
        rows = sorted(groups[key], key=lambda x: -x[0])
        if not rows:
            continue
        out.append(f"{titles[key]} ({len(rows)})")
        for days, label, l in rows:
            tail = f" · {days}d late" if key == "overdue" and days else ""
            out.append(f"• {nice(l)} — {label}{tail} [{l.get('owner') or '?'}]")
        out.append("")
    counts = []
    for sid, (label, _) in STAGES.items():
        if sid in QUIET:
            continue
        n = sum(1 for l in leads if l.get("stage") == sid)
        if n:
            counts.append(f"{label}: {n}")
    out.append("PIPELINE")
    out.append(" · ".join(counts))
    boxes = round(sum(float(l.get("boxes") or 0) for l in live))
    usd = sum(float(l.get("usd") or 0) for l in live)
    out.append(f"{len(live)} live leads · {boxes} boxes · ${usd:,.0f}")
    return "\n".join(out)


def report_factory(leads):
    out = [f"PowerFix pipeline — {TODAY:%d %b %Y}", ""]
    out.append(f"Signed / delivered: {boxes_in(leads, ('signed', 'active', 'payment'))} boxes")
    out.append(f"Contract out:       {boxes_in(leads, ('contract',))} boxes")
    out.append(f"Quoted:             {boxes_in(leads, ('quote',))} boxes")
    out.append(f"Trials running:     {boxes_in(leads, ('trial', 'results'))} boxes")
    out.append(f"Early stage:        {boxes_in(leads, ('contacted', 'sample'))} boxes")
    out.append("")
    fac = [l for l in leads if waiting_on(l) == "factory" and l.get("stage") not in QUIET]
    if fac:
        out.append(f"WAITING ON FACTORY ({len(fac)})")
        for l in fac:
            when = f" · {d(l['next_date']):%d %b}" if l.get("next_date") else ""
            out.append(f"• {nice(l)} — {l.get('next_action') or 'pending'}{when}")
    else:
        out.append("Nothing waiting on the factory.")
    soon = [l for l in leads if l.get("stage") in ("contract", "signed", "payment")]
    out.append("")
    out.append(f"Close to order: {len(soon)} deals · "
               f"{round(sum(float(l.get('boxes') or 0) for l in soon))} boxes")
    return "\n".join(out)


REPORTS = {"due": report_due, "standing": report_standing, "factory": report_factory}
SUBJECTS = {
    "due": "PowerFix follow-ups — {late} late",
    "standing": "PowerFix standing — {today:%d %b}",
    "factory": "PowerFix pipeline for the factory — {today:%d %b}",
}
APP_URL = "https://powerdash.powerfixinc.com"


# --------------------------------------------------------------------------
# short forms — WhatsApp template parameters cannot contain line breaks, so
# the WhatsApp nag is one line; iMessage takes the trimmed list.
# --------------------------------------------------------------------------
def summary_line(leads):
    late = today = week = 0
    worst = None
    for l in leads:
        state, days, label = due_info(l)
        if state == "overdue":
            late += 1
            if worst is None or days > worst[0]:
                worst = (days, l)
        elif state == "today":
            today += 1
        elif state == "soon":
            week += 1
    if not (late or today):
        return f"Nothing late. {week} due this week."
    bits = []
    if late:
        bits.append(f"{late} late")
    if today:
        bits.append(f"{today} due today")
    if week:
        bits.append(f"{week} this week")
    head = ", ".join(bits)
    if worst:
        days, l = worst
        tail = f" Worst: {nice(l)}, {days}d late ({l.get('owner') or '?'})."
    else:
        tail = ""
    return f"{head}.{tail}"


def short_due(leads, limit=6):
    rank = {"overdue": 0, "today": 1}
    items = []
    for l in leads:
        state, days, label = due_info(l)
        if state in rank:
            items.append((rank[state], -days, state, days, label, l))
    items.sort(key=lambda x: (x[0], x[1]))
    if not items:
        return f"PowerDash {TODAY:%d %b} — nothing late today."
    out = [f"PowerDash — {TODAY:%d %b}"]
    for _, _, state, days, label, l in items[:limit]:
        mark = f"{days}d late" if state == "overdue" and days else "due now" if state == "overdue" else "today"
        out.append(f"• {nice(l)} — {label} ({mark}, {l.get('owner') or '?'})")
    if len(items) > limit:
        out.append(f"…and {len(items) - limit} more")
    out.append(APP_URL)
    return "\n".join(out)


def short_standing(leads):
    live = [l for l in leads if l.get("stage") not in QUIET]
    boxes = round(sum(float(l.get("boxes") or 0) for l in live))
    counts = {}
    for l in live:
        counts[l.get("stage")] = counts.get(l.get("stage"), 0) + 1
    order = ("contract", "payment", "quote", "results", "trial", "sample", "contacted", "signed", "active")
    bits = [f"{STAGES[s][0]} {counts[s]}" for s in order if counts.get(s)]
    return (f"PowerDash week — {TODAY:%d %b}\n{summary_line(leads)}\n"
            f"{len(live)} live · {boxes} boxes\n" + " · ".join(bits) + f"\n{APP_URL}")


SHORT = {"due": short_due, "standing": short_standing,
         "factory": lambda leads: report_factory(leads)}


# --------------------------------------------------------------------------
# config — environment wins, then tools/config.local.json (never committed)
# --------------------------------------------------------------------------
def cfg(key, default=None):
    env = os.environ.get(key.upper())
    if env not in (None, ""):
        return env
    return _local().get(key, default)


_LOCAL = None


def _local():
    global _LOCAL
    if _LOCAL is None:
        f = ROOT / "tools" / "config.local.json"
        try:
            _LOCAL = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            _LOCAL = {}
    return _LOCAL


def fail(msg):
    """GitHub shows ::error:: lines in the run's Annotations box, which is the
    part anyone actually sees. Without it the reason hides in the log."""
    if os.environ.get("GITHUB_ACTIONS"):
        print(f"::error::{msg}")
    sys.exit(msg)


def clean(v):
    """Credentials copied out of a web page carry invisible characters —
    Google shows app passwords in four groups separated by non-breaking
    spaces, which smtplib then refuses to encode."""
    if not isinstance(v, str):
        return v
    for ch in ("\u00a0", "\u200b", "\u2060", "\ufeff"):
        v = v.replace(ch, " " if ch == "\u00a0" else "")
    return v.strip()


def recipients(key):
    v = cfg(key) or ""
    if isinstance(v, list):
        return [clean(str(x)) for x in v if clean(str(x))]
    return [clean(a) for a in str(v).replace(";", ",").split(",") if clean(a)]


# --------------------------------------------------------------------------
# channels
# --------------------------------------------------------------------------
def send_email(subject, body, to=None):
    to = to or recipients("mail_to")
    if not to:
        raise RuntimeError("no mail_to configured")
    user = clean(cfg("smtp_user"))
    pw = clean(cfg("smtp_pass"))
    host = clean(cfg("smtp_host", "smtp.gmail.com"))
    if "gmail" in host:
        pw = pw.replace(" ", "")   # a Gmail app password is 16 characters, shown in four groups
    if not (user and pw):
        raise RuntimeError("no smtp_user / smtp_pass configured")
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = clean(cfg("mail_from")) or user
    msg["To"] = ", ".join(to)
    msg.set_content(body)
    with smtplib.SMTP(host, int(clean(str(cfg("smtp_port", 587)))), timeout=30) as s:
        s.starttls()
        s.login(user, pw)
        s.send_message(msg)
    return f"email → {shown(to)}"


def _gmail_access_token():
    """Swap the long-lived refresh token for an hour-long access token."""
    import urllib.parse, urllib.request
    data = urllib.parse.urlencode({
        "client_id": clean(cfg("gmail_client_id")),
        "client_secret": clean(cfg("gmail_client_secret")),
        "refresh_token": clean(cfg("gmail_refresh_token")),
        "grant_type": "refresh_token",
    }).encode()
    with urllib.request.urlopen("https://oauth2.googleapis.com/token", data=data, timeout=30) as r:
        return json.loads(r.read())["access_token"]


def send_gmail(subject, body, to=None):
    """Gmail API with the same OAuth credentials PotholeRadar uses — no app
    password, no SMTP. Needs gmail_client_id / _secret / _refresh_token."""
    import base64, urllib.request
    to = to or recipients("mail_to")
    if not to:
        raise RuntimeError("no mail_to configured")
    if not all(cfg(k) for k in ("gmail_client_id", "gmail_client_secret", "gmail_refresh_token")):
        raise RuntimeError("Gmail API not configured (gmail_client_id / _secret / _refresh_token)")
    msg = EmailMessage()
    msg["Subject"] = subject
    sender = clean(cfg("gmail_sender")) or clean(cfg("mail_from"))
    if sender:                      # left out, Gmail fills in the signed-in address
        msg["From"] = sender
    msg["To"] = ", ".join(to)
    msg.set_content(body)
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    req = urllib.request.Request(
        "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
        data=json.dumps({"raw": raw}).encode(),
        headers={"Authorization": f"Bearer {_gmail_access_token()}",
                 "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        r.read()
    return f"gmail → {shown(to)}"


def send_whatsapp(short_text, to=None):
    """WhatsApp Cloud API. A message we start needs an approved template, and
    template variables cannot hold line breaks — so this sends one line."""
    import urllib.request, urllib.error
    token = clean(cfg("wa_token"))
    phone_id = clean(cfg("wa_phone_id"))
    template = cfg("wa_template", "powerdash_followups")
    lang = cfg("wa_lang", "en")
    to = to or recipients("wa_to")
    if not (token and phone_id and to):
        raise RuntimeError("WhatsApp not configured (wa_token / wa_phone_id / wa_to)")
    one_line = " ".join(short_text.split())[:900]
    sent = []
    for number in to:
        payload = {
            "messaging_product": "whatsapp",
            "to": number.lstrip("+").replace(" ", ""),
            "type": "template",
            "template": {
                "name": template,
                "language": {"code": lang},
                "components": [{"type": "body",
                                "parameters": [{"type": "text", "text": one_line}]}],
            },
        }
        req = urllib.request.Request(
            f"https://graph.facebook.com/v21.0/{phone_id}/messages",
            data=json.dumps(payload).encode(),
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                r.read()
            sent.append(number)
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"WhatsApp refused {number}: {e.code} {e.read().decode()[:200]}")
    return f"whatsapp → {shown(sent)}"


def send_imessage(body, to=None):
    """Only works on a Mac signed in to Messages — GitHub cannot do this."""
    import subprocess
    if sys.platform != "darwin":
        raise RuntimeError("iMessage only runs on the Mac")
    to = to or recipients("imessage_to")
    if not to:
        raise RuntimeError("no imessage_to configured")
    sent = []
    for handle in to:
        script = (
            'on run {targetBuddyPhone, targetMessage}\n'
            '  tell application "Messages"\n'
            '    set targetService to 1st account whose service type = iMessage\n'
            '    set targetBuddy to participant targetBuddyPhone of targetService\n'
            '    send targetMessage to targetBuddy\n'
            '  end tell\n'
            'end run'
        )
        r = subprocess.run(["osascript", "-", handle, body],
                           input=script, text=True, capture_output=True, timeout=60)
        if r.returncode != 0:
            raise RuntimeError(f"iMessage failed for {handle}: {r.stderr.strip()[:200]}")
        sent.append(handle)
    return f"imessage → {shown(sent)}"


CHANNELS = ("whatsapp", "imessage", "gmail", "email")


def shown(to):
    """On GitHub the run log is public once the repo is, so addresses and
    phone numbers are counted there rather than named. Locally, say who."""
    if os.environ.get("GITHUB_ACTIONS"):
        return f"{len(to)} recipient{'' if len(to) == 1 else 's'}"
    return ", ".join(to)


def channel_text(ch, body, short, wa_line):
    """Each channel gets the length it is good at: WhatsApp one line, iMessage
    the trimmed list, email the whole thing."""
    return {"whatsapp": wa_line, "imessage": short}.get(ch, body)


def dispatch(kind, leads, body, short, subject, via, dry=False):
    """via: 'auto' tries WhatsApp, then iMessage, then email, and stops at the
    first one that works. 'all' sends every configured channel. Or name them."""
    if via == "all":
        order, stop_at_first = list(CHANNELS), False
    elif via == "auto":
        order, stop_at_first = list(CHANNELS), True
    else:
        order, stop_at_first = [c.strip() for c in via.split(",") if c.strip()], False
    # the daily nag leads with the count; the weekly one is the short report
    raw = f"{summary_line(leads)} {APP_URL}" if kind == "due" else short.replace("\n", " · ")
    wa_line = " ".join(raw.split())
    results, problems = [], []
    for ch in order:
        try:
            if dry:
                results.append(f"[dry run] {ch} would send:\n"
                               f"{channel_text(ch, body, short, wa_line)}\n")
                continue
            if ch == "whatsapp":
                results.append(send_whatsapp(wa_line))
            elif ch == "imessage":
                results.append(send_imessage(short))
            elif ch == "gmail":
                results.append(send_gmail(subject, body))
            elif ch == "email":
                results.append(send_email(subject, body))
            else:
                problems.append(f"{ch}: unknown channel")
                continue
            if stop_at_first:
                break
        except Exception as e:
            problems.append(f"{ch}: {e}")
    return results, problems


def fetch_remote():
    """Pull the live leads file from GitHub so a Mac-side run is never stale."""
    import urllib.request
    repo = cfg("repo", "arlito331/powerdash")
    base = f"https://raw.githubusercontent.com/{repo}/main/data/"
    try:
        with urllib.request.urlopen(base + "leads.enc", timeout=30) as r:
            return decrypt(r.read())
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise
    with urllib.request.urlopen(base + "leads.json", timeout=30) as r:
        return json.loads(r.read().decode())


def main():
    args = sys.argv[1:]
    kind = args[0] if args and not args[0].startswith("-") else "due"
    if kind not in REPORTS:
        sys.exit(f"unknown report '{kind}' — use one of {', '.join(REPORTS)}")
    via = "auto"
    for i, a in enumerate(args):
        if a == "--via" and i + 1 < len(args):
            via = args[i + 1]
        elif a.startswith("--via="):
            via = a.split("=", 1)[1]

    leads = fetch_remote() if "--remote" in args else load()
    body = REPORTS[kind](leads)
    short = SHORT[kind](leads)
    late = sum(1 for l in leads if due_info(l)[0] == "overdue")
    subject = SUBJECTS[kind].format(late=late, today=TODAY)

    if "--send" not in args and "--dry-run" not in args:
        print(subject, "\n")
        print(body)
        return

    if kind == "due" and late == 0 and "--always" not in args:
        print("nothing late — nothing sent (pass --always to send anyway)")
        return

    results, problems = dispatch(kind, leads, body, short, subject, via,
                                 dry="--dry-run" in args)
    for r in results:
        print(r)
    for p in problems:
        print("skipped —", p, file=sys.stderr)
    if not results and not problems:
        fail("no channel configured")
    if not results and problems:
        fail("nothing could be sent — " + "; ".join(problems))


if __name__ == "__main__":
    main()
