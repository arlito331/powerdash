# PowerDash — PowerFix pipeline & follow-ups

One page that answers "what do I have to do today, and where does every deal
stand". Same look and the same habits as LogPothole: a single `index.html`, data
in a JSON file in the repo, a dark map, nothing to install.

## What it does

- **Today** — every lead sorted by how late it is. Red = late, orange = due
  today, blue = this week. One tap logs what you did and sets the next date.
- **Leads** — all of them, searchable, filtered by stage or country.
- **Map** — a pin per lead. Red = late, orange = waiting on us, blue = waiting
  on them, purple = waiting on the factory, green = signed or active.
- **Reports** — three ready-made texts with a WhatsApp button: the internal
  standing, the short factory report, and the follow-up list.
- **Reminders** — the follow-up list goes out by itself every weekday morning
  and the standing every Monday, by WhatsApp, iMessage or email. See below.

It has a tile on developers.powerfixinc.com (first one, amber radar), added in
`powerfix-hub/index.html` — that page needs pushing too for the tile to appear.

## The follow-up rule

One rule drives the dashboard, the map and the emails:

1. If a lead has a **next action date**, that date decides.
2. If it has none, the clock runs from the **last contact**: flagged at
   **15, 30 and 45 days**. Past 45 it says "push it or park it".
3. A lead with neither a date nor a last contact is itself flagged — nothing
   stays invisible.

It lives in `dueInfo()` in `index.html` and `due_info()` in
`tools/followups.py`. Change the cadence in both (`MILESTONES`).

## Going online

The repo holds **ciphertext only**, so it is safe to make public.

- `data/leads.enc` — the leads, AES-256-GCM (iv || ciphertext)
- `data/keys.json` — the master key wrapped under each person's password
  (PBKDF2-SHA256, 600,000 rounds). Public, and useless without a password.
- Passwords and a copy of the master key live in `APPS/KEYS`, never in the repo:
  `powerdash-passwords.json`, `powerdash-master-key.txt`

Signing in *is* the decryption: the password unwraps the key in the browser and
nothing readable ever reaches GitHub. A wrong password simply finds no entry it
can open.

### Turning it on, in order

1. **Add the key to the repo secrets** — `POWERDASH_KEY`, the one line inside
   `APPS/KEYS/powerdash-master-key.txt`. Without it the morning email cannot
   read the leads and the job fails.
2. **Push** (GitHub Desktop).
3. **Make it public** — Settings → General → bottom of the page → Change
   visibility → Public.
4. **Turn on Pages** — Settings → Pages → Source: Deploy from a branch,
   Branch: `main`, folder: `/ (root)`. A minute later it is live at
   https://arlito331.github.io/powerdash/ — which is what the hub tile already
   points at.
5. **Hand Joel his password** from the password file. Each person types theirs
   once per device; after that the browser remembers the key.

Optional custom domain: GoDaddy CNAME `powerdash` → `arlito331.github.io`,
then add a `CNAME` file containing `powerdash.powerfixinc.com`. **DNS first**,
or Pages breaks.

### Adding or removing a person

Edit `APPS/KEYS/powerdash-passwords.json`, then:

```
python3 tools/encrypt_data.py          # dry run
python3 tools/encrypt_data.py apply    # rewraps keys.json, leaves the data alone
```

Commit `data/keys.json`. Removing someone's entry locks them out of future
reads, though anyone who already unlocked keeps the key their browser cached —
to cut that off, generate a new master key (delete the file in KEYS, rerun,
re-encrypt) and reissue passwords.

## The reminders — WhatsApp, iMessage, email

`tools/followups.py` builds the message and sends it. Three channels, and
`--via auto` tries them in your order of preference — WhatsApp first, then
iMessage, then email — and stops at the first one that works.

```
python3 tools/followups.py due                      # just print it
python3 tools/followups.py due --dry-run --via all  # show what each channel would send
python3 tools/followups.py due --send --via auto    # really send
```

Each channel gets the length it is good at:

| Channel | What it sends | Where it can run |
| --- | --- | --- |
| WhatsApp | one line: "3 late, 1 due today… Worst: X, 6d late" + link | GitHub or the Mac |
| iMessage | the short list, up to 6 items + link | **only the Mac** |
| Gmail | the full list, through the Gmail API | GitHub or the Mac |
| Email | the same, through plain SMTP | GitHub or the Mac |

Gmail and Email are two ways to the same inbox. **Gmail is the one to use** —
PotholeRadar already sends this way, so the Google credentials exist and no
app password or 2-Step fiddling is needed. SMTP is the fallback if you would
rather use an app password.

Two schedules, both already written:

- **Daily** — weekdays 07:00 Panama, the follow-up list. Silent when nothing
  is late, so the message keeps meaning something.
- **Weekly** — Mondays 08:00 Panama, the standing for you and Joel, then the
  short pipeline report for the factory.

### Which one to turn on

**Gmail** is the one that just works, and reuses what PotholeRadar already has.
GitHub never shows a secret back, so the refresh token has to be minted once:

```
python3 tools/gmail-setup.py
```

It reads the client id and secret out of `APPS/KEYS/client_secret_*.json`,
opens Google for approval, and prints the three values to paste into the repo
secrets. Nothing is written to disk.

**Email (SMTP)** is the alternative: a Gmail **app password**
(myaccount.google.com/apppasswords, needs 2-Step Verification on) in
`SMTP_PASS`, with `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER` and `MAIL_TO`.

**iMessage** is free and instant, but only a Mac can send it, so the Mac has to
be awake at 7am:

```
./tools/install-local-schedule.sh          # on
./tools/install-local-schedule.sh off      # off again
./tools/run-local.sh daily                 # test it now
tail -20 ~/Library/Logs/powerdash.log      # see what happened
```

The first send asks macOS for permission to control Messages — say yes.
Recipients go in `tools/config.local.json` (copy the `.example` file; it is
never committed).

**WhatsApp** needs setting up at Meta once, because WhatsApp does not let a
business start a conversation with free text — only with a template they
approved. About 40 minutes:

1. business.facebook.com → create a Business account if there is none.
2. developers.facebook.com → Create App → **Business** → add the product
   **WhatsApp**.
3. WhatsApp → API Setup: it gives you a test number and a **Phone number ID**.
   For real use, add your own number (one that is *not* on the WhatsApp app).
4. WhatsApp Manager → Message templates → Create template, category
   **Utility**, name `powerdash_followups`, body exactly:
   `PowerDash: {{1}}` — one variable, nothing else. Submit; approval is
   usually minutes.
5. System user → generate a **permanent token** with `whatsapp_business_messaging`.
6. Put the token, the Phone number ID and the numbers into the repo secrets
   (below) or `tools/config.local.json`.

Until step 6 is done, `--via auto` simply falls through to the next channel.

### GitHub secrets

Settings → Secrets and variables → Actions:

| Secret | What to put |
| --- | --- |
| `GMAIL_CLIENT_ID` / `GMAIL_CLIENT_SECRET` / `GMAIL_REFRESH_TOKEN` | printed by `tools/gmail-setup.py` |
| `GMAIL_SENDER` | optional, e.g. `PowerDash <you@example.com>` |
| `SMTP_HOST` / `SMTP_PORT` | only for the SMTP fallback: `smtp.gmail.com` / `587` |
| `SMTP_USER` / `SMTP_PASS` | only for the SMTP fallback: the sending Gmail and an **app password** |
| `MAIL_TO` | the two of you, comma separated |
| `MAIL_TO_FACTORY` | optional — who gets the Monday factory report |
| `WA_TOKEN` | the permanent token from Meta |
| `WA_PHONE_ID` | the Phone number ID |
| `WA_TO` | `+50760000000, +50761111111` |
| `WA_TEMPLATE` | `powerdash_followups` |

Both workflows (`.github/workflows/followups.yml`, `weekly.yml`) can also be
run by hand from the Actions tab — useful the first time.

## Data

`data/leads.enc` holds this, encrypted — a list of leads:

```json
{
  "id": "L...", "name": "", "company": "", "contact": "", "phone": "",
  "country": "", "city": "", "lat": 0, "lng": 0,
  "stage": "contacted|sample|trial|results|quote|contract|signed|payment|active|parked",
  "waiting_on": "us|them|factory",
  "tons": 0, "usd": 0, "owner": "AA|JK",
  "next_action": "", "next_date": "YYYY-MM-DD", "last_contact": "YYYY-MM-DD",
  "notes": "", "log": [{"date": "", "note": "", "by": ""}],
  "created_at": "", "updated_at": ""
}
```

The seven leads in there now are **examples** — the banner on the dashboard
clears them in one tap. The plaintext from before encryption is backed up at
`APPS/KEYS/leads.json.pre-encryption`.

Two phones editing at once merge by `updated_at`, newest wins per lead, and the
app refuses to publish if it could not read the shared file first — the two
traps that bit LogPothole.
