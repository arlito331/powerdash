#!/usr/bin/env python3
"""Encrypt the PowerDash leads so the repo can be public.

Same scheme as FixWatch/LogPothole, so the two apps behave alike:

  data/leads.json  ->  data/leads.enc   (AES-256-GCM, iv || ciphertext)
  data/keys.json   <-  the master key, wrapped once per person's password
                       (PBKDF2-SHA256, 600k rounds, one shared salt)

Signing in IS the decryption: the password unwraps the master key in the
browser. Without a password the repo is random bytes.

Passwords and the master key live OUTSIDE the repo, in APPS/KEYS:
  powerdash-passwords.json   [{"user": "...", "role": "...", "pass": "..."}]
  powerdash-master-key.txt   base64 of the 32-byte key

Run from the repo root:

    python3 tools/encrypt_data.py            # dry run, says what it would do
    python3 tools/encrypt_data.py apply      # writes

Idempotent — rerun it after adding or removing a person and only keys.json
changes. If data/leads.json is absent (already encrypted), it rewraps the
existing key and leaves the ciphertext alone.
"""
import base64, hashlib, json, os, secrets, shutil, sys

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KEYS_DIR = os.path.join(os.path.dirname(REPO), "KEYS")
PW_FILE = os.path.join(KEYS_DIR, "powerdash-passwords.json")
MK_FILE = os.path.join(KEYS_DIR, "powerdash-master-key.txt")
PLAIN = os.path.join(REPO, "data", "leads.json")
CIPHER = os.path.join(REPO, "data", "leads.enc")
KEYS_JSON = os.path.join(REPO, "data", "keys.json")
ITER = 600_000

b64 = lambda b: base64.b64encode(b).decode()


def master_key(apply):
    if os.path.exists(MK_FILE):
        return base64.b64decode(open(MK_FILE).read().strip())
    mk = secrets.token_bytes(32)
    if apply:
        os.makedirs(KEYS_DIR, exist_ok=True)
        with open(MK_FILE, "w") as f:
            f.write(b64(mk))
        os.chmod(MK_FILE, 0o600)
    return mk


def wrap_table(accounts, mk):
    salt = secrets.token_bytes(16)
    entries = []
    for a in accounts:
        kek = hashlib.pbkdf2_hmac("sha256", a["pass"].encode(), salt, ITER)
        payload = json.dumps({"user": a["user"], "role": a.get("role", "master"),
                              "k": b64(mk)}).encode()
        iv = secrets.token_bytes(12)
        entries.append({"iv": b64(iv), "ct": b64(AESGCM(kek).encrypt(iv, payload, None))})
    return {"v": 1,
            "kdf": {"name": "PBKDF2-SHA256", "iter": ITER, "salt": b64(salt)},
            "entries": entries}


def main():
    apply = len(sys.argv) > 1 and sys.argv[1] == "apply"
    if not os.path.exists(PW_FILE):
        sys.exit(f"No password file at {PW_FILE}\n"
                 f'Create it as: [{{"user": "ariel", "role": "master", "pass": "..."}}]')
    accounts = json.load(open(PW_FILE))
    mk = master_key(apply)

    print(f"accounts        : {len(accounts)} ({', '.join(a['user'] for a in accounts)})")
    print(f"leads.json      : {'present — will encrypt' if os.path.exists(PLAIN) else 'absent'}")
    print(f"leads.enc       : {'exists — left alone' if os.path.exists(CIPHER) else 'will be written'}")
    print(f"master key      : {'reused from KEYS' if os.path.exists(MK_FILE) else 'new'}")
    if not apply:
        print("\ndry run — pass 'apply' to write")
        return

    json.dump(wrap_table(accounts, mk), open(KEYS_JSON, "w"), indent=1)
    if os.path.exists(PLAIN):
        iv = secrets.token_bytes(12)
        with open(PLAIN, "rb") as f:
            pt = f.read()
        with open(CIPHER, "wb") as f:
            f.write(iv + AESGCM(mk).encrypt(iv, pt, None))
        shutil.copy2(PLAIN, os.path.join(KEYS_DIR, "leads.json.pre-encryption"))
        os.remove(PLAIN)
        print(f"wrote {os.path.basename(CIPHER)}, plaintext backed up to KEYS, removed from the repo")
    print(f"wrote {os.path.basename(KEYS_JSON)} with {len(accounts)} wrapped copies of the key")


if __name__ == "__main__":
    main()
