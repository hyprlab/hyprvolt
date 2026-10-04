"""Field kinds: how a value is read from a form or the API, checked, shown,
and turned into text for search and custom-field storage.

One set of rules serves the fields a module declares and the custom fields
an admin adds, so both behave the same everywhere.
"""
import ipaddress
import re
from datetime import date, datetime, timezone

from ..auth import EMAIL_RE
from ..manifest import Field

URL_SCHEMES = ("http", "https", "ftp", "sftp", "ssh", "smb", "rdp", "vnc", "nfs", "git")
URL_RE = re.compile(r"^([a-z][a-z0-9+.-]*)://\S+$", re.I)
#: An address without a scheme: a hostname or an IPv4 or [IPv6] address,
#: then a port and a path if any (192.168.1.1, router.lab:8443/admin).
HOST_RE = re.compile(r"^(?:\[[0-9a-f:.]+\]|[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)*)"
                     r"(?::\d{1,5})?(?:/(?!/)\S*)?$", re.I)
#: What a phone number can be dialed from: digits, or the letters of a
#: vanity number (1-833-VERIZON), with the usual separators.
DIALABLE_RE = re.compile(r"^\+?[0-9A-Za-z ().\-/]{3,40}$")
KEYPAD = {c: str(n) for n, letters in ((2, "abc"), (3, "def"), (4, "ghi"), (5, "jkl"), (6, "mno"),
                                       (7, "pqrs"), (8, "tuv"), (9, "wxyz")) for c in letters}
#: A speed as written: "1 Gb/s", "940 Mbps", "2.5 gbit", or a bare number of
#: megabits. Stored as whole megabits per second.
SPEED_RE = re.compile(r"^(\d+(?:[.,]\d+)?)\s*(?:(g|m|k)(?:b(?:it)?(?:ps|/s|s)?|bps|bit/s)?)?$", re.I)
TRUE = ("1", "true", "on", "yes")
FALSE = ("", "0", "false", "off", "no")
MAX_TEXT = 500
MAX_LONG = 200_000


class Invalid(ValueError):
    """A value that can't be accepted, with the reason written for a person."""


def custom_field(cf) -> Field:
    """A custom field definition, seen as a Field."""
    return Field(cf.key, cf.label, cf.kind, options=tuple((o, o) for o in cf.options))


def parse(f: Field, raw, lookup=None):
    """The stored value for ``raw``, or ``Invalid``. ``lookup(id)`` returns a
    live entity for ref fields."""
    if f.kind == "boolean":
        if isinstance(raw, bool):
            return raw
        text = str(raw if raw is not None else "").strip().lower()
        if text in TRUE:
            return True
        if text in FALSE:
            return False
        raise Invalid(f"{f.label} must be yes or no.")

    if isinstance(raw, str):
        raw = raw.strip()
    if raw is None or raw == "":
        if f.required:
            raise Invalid(f"{f.label} is required.")
        return None

    kind = f.kind
    if kind == "phone":
        # Kept as written, whatever it is: a vanity number, or "ask for Sam".
        raw = " ".join(str(raw).split())
        if len(raw) > MAX_TEXT:
            raise Invalid(f"{f.label} is limited to {MAX_TEXT} characters.")
        return raw

    if kind in ("text", "longtext", "markdown", "email", "url"):
        if not isinstance(raw, str):
            raw = str(raw)
        limit = MAX_TEXT if kind in ("text", "email", "url") else MAX_LONG
        if len(raw) > limit:
            raise Invalid(f"{f.label} is limited to {limit} characters.")
        if kind == "email" and not EMAIL_RE.match(raw):
            raise Invalid(f"{f.label} must be an email address.")
        if kind == "url" and raw and not _address(raw):
            raise Invalid(f"{f.label} must be a web address such as https://example.com, or an IP address or "
                          "hostname such as 192.168.1.1.")
        return raw

    if kind in ("integer", "number"):
        try:
            if kind == "integer":
                if isinstance(raw, float) and not raw.is_integer():
                    raise ValueError
                value = int(raw) if not isinstance(raw, str) else int(raw.replace(",", ""))
            else:
                value = float(raw.replace(",", "") if isinstance(raw, str) else raw)
        except (TypeError, ValueError):
            raise Invalid(f"{f.label} must be a {'whole ' if kind == 'integer' else ''}number.") from None
        if value != value or value in (float("inf"), float("-inf")):
            raise Invalid(f"{f.label} must be a number.")
        low, high = f.min, f.max
        if (low is not None and value < low) or (high is not None and value > high):
            if low is not None and high is not None:
                raise Invalid(f"{f.label} must be between {_num(low)} and {_num(high)}.")
            raise Invalid(f"{f.label} must be at least {_num(low)}." if low is not None
                          else f"{f.label} must be at most {_num(high)}.")
        return value

    if kind == "speed":
        return _parse_speed(f, raw)

    if kind == "datetime":
        return _parse_datetime(f, raw)

    if kind == "date":
        if isinstance(raw, datetime):
            return raw.date()
        if isinstance(raw, date):
            return raw
        try:
            return date.fromisoformat(str(raw)[:10])
        except ValueError:
            raise Invalid(f"{f.label} must be a date, such as 2026-09-25.") from None

    if kind == "select":
        values = [v for v, _ in f.options]
        if str(raw) not in values:
            raise Invalid(f"{f.label} must be one of: {', '.join(label for _, label in f.options)}.")
        return str(raw)

    if kind == "ref":
        try:
            ref_id = int(raw)
        except (TypeError, ValueError):
            raise Invalid(f"{f.label} must be a record.") from None
        target = lookup(ref_id) if lookup else None
        if target is None or not ref_allows(f, target.type):
            raise Invalid(f"{f.label} must point at an existing record of the right type.")
        return ref_id

    if kind == "ip":
        try:
            return str(ipaddress.ip_address(str(raw)))
        except ValueError:
            raise Invalid(f"{f.label} must be an IP address, such as 10.0.20.11 or fd00::11.") from None

    if kind == "cidr":
        try:
            # Host bits are dropped: 10.0.20.7/24 is the subnet 10.0.20.0/24.
            return str(ipaddress.ip_network(str(raw), strict=False))
        except ValueError:
            raise Invalid(f"{f.label} must be a subnet with its prefix, such as 10.0.20.0/24.") from None

    if kind == "iprange":
        return _parse_iprange(f, raw)

    raise Invalid(f"{f.label} has a kind the app doesn't know.")


def _parse_datetime(f: Field, raw) -> datetime:
    """Stored as naive UTC. Text with an offset or a Z is taken as it says;
    without one, as a time in the instance's zone, which is what a form
    sends. A datetime object is already UTC."""
    from . import clock
    if isinstance(raw, datetime):
        return raw.astimezone(timezone.utc).replace(tzinfo=None) if raw.tzinfo else raw
    text = str(raw).strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00") if text.endswith("Z") else text)
    except ValueError:
        raise Invalid(f"{f.label} must be a date and time, such as 2026-10-03 22:00.") from None
    if parsed.tzinfo is not None:
        return parsed.astimezone(timezone.utc).replace(tzinfo=None, second=0, microsecond=0)
    return clock.to_utc(parsed.replace(second=0, microsecond=0))


def ref_allows(f: Field, type_key: str) -> bool:
    """Whether a ref field may point at a record of ``type_key``: one of its
    types, or a type with its trait."""
    if type_key in f.types:
        return True
    if f.trait:
        from ..registry import current as registry
        etype = registry().type(type_key)
        return etype is not None and f.trait in etype.traits
    return False


def _parse_iprange(f: Field, raw) -> str:
    """ "10.0.30.100-10.0.30.199" from the first and last address, joined with
    a dash (as the range control sends them), an en dash or "to"."""
    text = re.sub(r"\s+to\s+|\s*[–—]\s*", "-", str(raw).strip())
    first, sep, last = text.partition("-")
    if not sep or not first.strip() or not last.strip():
        raise Invalid(f"{f.label} needs its first and its last address.")
    try:
        a, b = ipaddress.ip_address(first.strip()), ipaddress.ip_address(last.strip())
    except ValueError:
        raise Invalid(f"{f.label} is two IP addresses: the first and the last, such as 10.0.30.100 and "
                      f"10.0.30.199.") from None
    if a.version != b.version:
        raise Invalid(f"{f.label}'s first and last addresses must both be IPv4, or both IPv6.")
    if a > b:
        raise Invalid(f"{f.label}'s first address must come before its last.")
    return f"{a}-{b}"


#: The subnet sizes the mask chooser offers: IPv4 /8 to /32, and the usual
#: IPv6 prefixes.
V4_PREFIXES = tuple(range(8, 33))
V6_PREFIXES = (48, 56, 64, 128)


def cidr_parts(value) -> tuple[str, int]:
    """(network address, prefix) as the range control shows them: /24 when
    there is none yet."""
    if not value:
        return "", 24
    address, _, prefix = str(value).partition("/")
    return address, int(prefix) if prefix.isdigit() else 24


def mask_choices(address: str = "", current: int = 24) -> list[dict]:
    """The subnet mask chooser's options, grouped: "/24 · 255.255.255.0 · 254
    hosts" for IPv4, "/64" for IPv6; the current prefix always among them."""
    v4 = []
    for n in V4_PREFIXES:
        net = ipaddress.IPv4Network(f"0.0.0.0/{n}")
        hosts = 2 ** (32 - n) - 2 if n < 31 else 2 ** (32 - n)
        v4.append((n, f"/{n} · {net.netmask} · {hosts:,} {'host' if hosts == 1 else 'hosts'}"))
    v6 = [(n, f"/{n}") for n in sorted(set(V6_PREFIXES) | ({current} if ":" in address else set()))]
    if ":" not in address and current not in V4_PREFIXES and current <= 32:
        v4 = sorted(v4 + [(current, f"/{current} · {ipaddress.IPv4Network(f'0.0.0.0/{current}').netmask}")])
    return [{"label": "IPv4", "options": v4}, {"label": "IPv6", "options": v6}]


def iprange_parts(value) -> tuple[str, str]:
    first, _, last = str(value or "").partition("-")
    return first, last


def _parse_speed(f: Field, raw) -> int:
    if isinstance(raw, bool):
        raise Invalid(f"{f.label} must be a speed, such as 940 Mb/s or 1 Gb/s.")
    if isinstance(raw, (int, float)):
        value, unit = float(raw), "m"
    else:
        m = SPEED_RE.match(str(raw).strip())
        if not m:
            raise Invalid(f"{f.label} must be a speed, such as 940 Mb/s or 1 Gb/s.")
        number = m.group(1)
        # 1,500 is fifteen hundred; 1,5 is one and a half.
        number = number.replace(",", "") if re.fullmatch(r"\d{1,3},\d{3}", number) else number.replace(",", ".")
        value, unit = float(number), (m.group(2) or "m").lower()
    mbps = value * {"g": 1000, "m": 1, "k": 0.001}[unit]
    if mbps < 0 or mbps > 10_000_000:
        raise Invalid(f"{f.label} must be between 0 and 10,000 Gb/s.")
    return max(round(mbps), 1) if mbps > 0 else 0


def speed_parts(value) -> tuple[str, str]:
    """(number, unit) as the speed control shows it: Gb/s for whole tenths
    of a gigabit, Mb/s for anything else."""
    if value in (None, ""):
        return "", "m"
    value = int(value)
    if value >= 1000 and value % 100 == 0:
        return _num(value / 1000), "g"
    return str(value), "m"


def _num(value) -> str:
    return str(int(value)) if float(value).is_integer() else str(value)


def display(f: Field, value, lookup=None) -> str:
    """How a value reads in the sheet, a card or the history."""
    if value is None or value == "":
        return ""
    if f.kind == "boolean":
        if f.switch:
            return f.switch[1] if value else f.switch[0]
        return "Yes" if value else "No"
    if f.kind == "select":
        return dict(f.options).get(value, str(value))
    if f.kind == "ref":
        target = lookup(value) if lookup else None
        return target.name if target else f"#{value}"
    if f.kind == "datetime" and isinstance(value, datetime):
        from . import clock
        return clock.shown(value)
    if f.kind == "date":
        return value.isoformat() if isinstance(value, date) else str(value)
    if f.kind == "speed":
        number, unit = speed_parts(value)
        return f"{number} {'Gb/s' if unit == 'g' else 'Mb/s'}"
    if f.kind == "number":
        text = f"{value:,.2f}".rstrip("0").rstrip(".") if isinstance(value, float) else str(value)
    elif f.kind == "integer":
        text = str(value)
    else:
        text = str(value)
    return f"{text} {f.unit}" if f.unit else text


def when_value(value) -> str:
    """A ``shown_when`` value as the page compares it: "1" or "0" for yes
    or no, the text of anything else."""
    return ("1" if value else "0") if isinstance(value, bool) else str(value)


def hidden_keys(fields, values: dict) -> set:
    """The keys of the fields not shown for these values (``shown_when``): a
    field is shown while the field it follows is shown and has the value.
    Fields come in their order, so the one followed is decided first."""
    hidden = set()
    for f in fields:
        if f.shown_when:
            key, want = f.shown_when
            have = values.get(key)
            same = bool(have) == want if isinstance(want, bool) else have == want
            if key in hidden or not same:
                hidden.add(f.key)
    return hidden


def to_text(f: Field, value) -> str:
    """Normalized text: what custom_values stores and search matches."""
    if value is None:
        return ""
    if f.kind == "boolean":
        return "1" if value else "0"
    if f.kind == "datetime" and isinstance(value, datetime):
        return value.isoformat(timespec="minutes")
    if f.kind == "date" and isinstance(value, date):
        return value.isoformat()
    if f.kind == "number" and isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def from_text(f: Field, text: str):
    """Back from ``to_text``, for custom values."""
    if text is None or text == "":
        return False if f.kind == "boolean" else None
    try:
        if f.kind == "boolean":
            return text == "1"
        if f.kind == "number":
            return float(text)
        if f.kind in ("integer", "speed"):
            return int(text)
        if f.kind == "date":
            return date.fromisoformat(text)
        if f.kind == "datetime":
            return datetime.fromisoformat(text)
    except ValueError:
        return None
    return text


def to_json(f: Field, value):
    if isinstance(value, datetime):
        return value.isoformat(timespec="minutes") + "Z"
    if isinstance(value, date):
        return value.isoformat()
    return value


def href(f: Field, value) -> str | None:
    """Where a value links to in the Overview: a web address, mailto: for an
    email, tel: for a phone number. None for anything else."""
    if not value:
        return None
    if is_link(f, value):
        return value
    if f.kind == "email":
        return "mailto:" + value
    if f.kind == "phone":
        # A tel: link only for what can be dialed; letters on the keypad's keys.
        number = re.split(r"(?i)\s*(?:ext\.?|\bx)\s*(?=\d)", value)[0]
        if not DIALABLE_RE.match(number) or sum(c.isdigit() for c in number) < 3:
            return None
        return "tel:" + "".join(c if c.isdigit() or c == "+" else KEYPAD.get(c.lower(), "") for c in number)
    return None


def _address(raw: str) -> bool:
    """A url field's value: an address with a known scheme, or a bare
    hostname or IP address (a service on a router has no web page)."""
    m = URL_RE.match(raw)
    if m:
        return m.group(1).lower() in URL_SCHEMES
    try:
        ipaddress.ip_address(raw)
        return True
    except ValueError:
        return bool(HOST_RE.match(raw))


def is_link(f: Field, value) -> bool:
    """Only web addresses become links; ssh:// and the like are shown as text."""
    return f.kind == "url" and isinstance(value, str) and value.lower().startswith(("http://", "https://"))
