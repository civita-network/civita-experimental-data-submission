"""Contributor-namespaced record IDs in the exact format the CIVITA database expects.

ID = <contributor_prefix>-<dataset_namespace>-<TABLE_PREFIX>-<NNNN>
  contributor_prefix = slug(email local part)-slug(first domain label)-<3-char FNV-1a hash>
  dataset_namespace  = 6 random characters [0-9a-z], minted once per dataset and kept.

The prefix depends only on the email, so the same person gets the same prefix on any
machine. The namespace keeps two datasets from the same person from colliding.
"""
import re
import secrets

_ALPHA = "0123456789abcdefghijklmnopqrstuvwxyz"

# JavaScript String.prototype.trim() removes exactly these (Python's strip() removes more,
# e.g. U+001C..U+001F and U+0085), so the IDs would differ from the database's own.
_JS_WS = ("\t\n\x0b\x0c\r \xa0            "
          "    　﻿")


def norm_email(email):
    return str("" if email is None else email).strip(_JS_WS).lower()


def _js_lower_ok(s):
    # The hash runs over UTF-16 code units in JavaScript. Non-BMP characters would differ
    # between the two implementations, so refuse them instead of minting a mismatched ID.
    if any(ord(ch) > 0xFFFF for ch in s):
        raise ValueError("email contains characters outside the Basic Multilingual Plane: %r" % s)


def hash_email(norm):
    _js_lower_ok(norm)
    h = 0x811C9DC5
    for ch in norm:
        h ^= ord(ch)
        h = (h + ((h << 1) + (h << 4) + (h << 7) + (h << 8) + (h << 24))) & 0xFFFFFFFF
    return ("000" + _base36(h))[-3:]


def _base36(n):
    if n == 0:
        return "0"
    out = ""
    while n:
        n, r = divmod(n, 36)
        out = _ALPHA[r] + out
    return out


def _slug(s):
    return re.sub(r"^-+|-+$", "", re.sub(r"[^a-z0-9]+", "-", s))


def derive_prefix(email):
    e = norm_email(email)
    at = e.find("@")
    local = e[:at] if at >= 0 else e
    domain = e[at + 1:] if at >= 0 else ""
    first_label = domain.split(".")[0] if domain else ""
    readable = "-".join(p for p in (_slug(local), _slug(first_label)) if p) or "anon"
    return readable + "-" + hash_email(e)


EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def valid_email(email):
    e = norm_email(email)
    if any(ord(ch) < 0x20 or 0x7F <= ord(ch) <= 0x9F or ord(ch) > 0xFFFF or ch in _JS_WS for ch in e):
        return False  # control, invisible or non-BMP characters: refuse rather than mint odd IDs
    return bool(EMAIL_RE.match(e))


def new_namespace():
    return "".join(_ALPHA[b % 36] for b in secrets.token_bytes(6))


def make_id(prefix, namespace, table_prefix, n):
    if not prefix or not namespace or not table_prefix:
        raise ValueError("cannot mint an ID without contributor prefix, namespace and table prefix")
    if not isinstance(n, int) or n < 1:
        raise ValueError("counter must be a positive integer, got %r" % (n,))
    return "%s-%s-%s-%s" % (prefix, namespace, table_prefix, str(n).zfill(4))
