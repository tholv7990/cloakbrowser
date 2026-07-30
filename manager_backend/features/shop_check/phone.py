"""Calling-code parser for the Shop phone-OTP hint.

A phone-OTP page shows a masked number — a leading calling code and a trailing
suffix, never the national number. This maps the calling code to geography with
an honest confidence:

- `exact`     — the code belongs to a single country.
- `ambiguous` — the code is a shared numbering plan (NANP, Russia/Kazakhstan,
  the French overseas plans). We can't pick a country without the national
  number, so we don't; `region_name` names the plan.
- `unknown`   — no `+`, an unassigned code, or no digits at all.

Proxy geography is NEVER consulted to fill phone geography — a stealth exit IP
says nothing about the account's phone country.

ponytail: the EXACT table is a curated common set, not the full ITU list;
anything not listed returns `unknown` (safe). Upgrade path: swap in an offline
`phonenumbers` table if broader single-country coverage is needed — it still
can't resolve a shared plan from a masked number, so the ambiguous cases stay.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Shared numbering plans -> plan label. These are ALWAYS ambiguous: a masked
# number can't tell the countries apart, and guessing would be wrong.
_SHARED: dict[str, str] = {
    "+1": "North American Numbering Plan (US, Canada, and NANP territories)",
    "+7": "Shared plan: Russia / Kazakhstan",
    "+262": "French Indian Ocean plan: Réunion / Mayotte",
    "+590": "French Antilles plan: Guadeloupe / Saint-Barthélemy / Saint-Martin",
    "+599": "Dutch Caribbean plan: Curaçao / Caribbean Netherlands",
}

# Single-country calling codes -> (ISO-3166 alpha-2, display name). Curated to
# the common set; unlisted codes fall through to `unknown`.
_EXACT: dict[str, tuple[str, str]] = {
    "+20": ("EG", "Egypt"), "+27": ("ZA", "South Africa"), "+30": ("GR", "Greece"),
    "+31": ("NL", "Netherlands"), "+32": ("BE", "Belgium"), "+33": ("FR", "France"),
    "+34": ("ES", "Spain"), "+36": ("HU", "Hungary"), "+39": ("IT", "Italy"),
    "+40": ("RO", "Romania"), "+41": ("CH", "Switzerland"), "+43": ("AT", "Austria"),
    "+44": ("GB", "United Kingdom"), "+45": ("DK", "Denmark"), "+46": ("SE", "Sweden"),
    "+47": ("NO", "Norway"), "+48": ("PL", "Poland"), "+49": ("DE", "Germany"),
    "+51": ("PE", "Peru"), "+52": ("MX", "Mexico"), "+53": ("CU", "Cuba"),
    "+54": ("AR", "Argentina"), "+55": ("BR", "Brazil"), "+56": ("CL", "Chile"),
    "+57": ("CO", "Colombia"), "+58": ("VE", "Venezuela"), "+60": ("MY", "Malaysia"),
    "+61": ("AU", "Australia"), "+62": ("ID", "Indonesia"), "+63": ("PH", "Philippines"),
    "+64": ("NZ", "New Zealand"), "+65": ("SG", "Singapore"), "+66": ("TH", "Thailand"),
    "+81": ("JP", "Japan"), "+82": ("KR", "South Korea"), "+84": ("VN", "Vietnam"),
    "+86": ("CN", "China"), "+90": ("TR", "Turkey"), "+91": ("IN", "India"),
    "+92": ("PK", "Pakistan"), "+93": ("AF", "Afghanistan"), "+94": ("LK", "Sri Lanka"),
    "+95": ("MM", "Myanmar"), "+98": ("IR", "Iran"), "+212": ("MA", "Morocco"),
    "+213": ("DZ", "Algeria"), "+216": ("TN", "Tunisia"), "+218": ("LY", "Libya"),
    "+220": ("GM", "Gambia"), "+221": ("SN", "Senegal"), "+233": ("GH", "Ghana"),
    "+234": ("NG", "Nigeria"), "+254": ("KE", "Kenya"), "+255": ("TZ", "Tanzania"),
    "+256": ("UG", "Uganda"), "+263": ("ZW", "Zimbabwe"), "+351": ("PT", "Portugal"),
    "+352": ("LU", "Luxembourg"), "+353": ("IE", "Ireland"), "+354": ("IS", "Iceland"),
    "+355": ("AL", "Albania"), "+356": ("MT", "Malta"), "+357": ("CY", "Cyprus"),
    "+358": ("FI", "Finland"), "+359": ("BG", "Bulgaria"), "+370": ("LT", "Lithuania"),
    "+371": ("LV", "Latvia"), "+372": ("EE", "Estonia"), "+375": ("BY", "Belarus"),
    "+380": ("UA", "Ukraine"), "+385": ("HR", "Croatia"), "+386": ("SI", "Slovenia"),
    "+387": ("BA", "Bosnia and Herzegovina"), "+420": ("CZ", "Czechia"),
    "+421": ("SK", "Slovakia"), "+886": ("TW", "Taiwan"), "+960": ("MV", "Maldives"),
    "+961": ("LB", "Lebanon"), "+962": ("JO", "Jordan"), "+963": ("SY", "Syria"),
    "+964": ("IQ", "Iraq"), "+965": ("KW", "Kuwait"), "+966": ("SA", "Saudi Arabia"),
    "+967": ("YE", "Yemen"), "+968": ("OM", "Oman"), "+971": ("AE", "United Arab Emirates"),
    "+972": ("IL", "Israel"), "+973": ("BH", "Bahrain"), "+974": ("QA", "Qatar"),
    "+975": ("BT", "Bhutan"), "+977": ("NP", "Nepal"), "+992": ("TJ", "Tajikistan"),
    "+993": ("TM", "Turkmenistan"), "+994": ("AZ", "Azerbaijan"), "+995": ("GE", "Georgia"),
    "+998": ("UZ", "Uzbekistan"), "+855": ("KH", "Cambodia"), "+856": ("LA", "Laos"),
    "+880": ("BD", "Bangladesh"),
}

_DIGITS = re.compile(r"\d+")


@dataclass(frozen=True)
class PhoneInfo:
    prefix: str | None          # observed calling code, e.g. "+84" (None if no digits)
    suffix: str | None          # trailing visible digits, e.g. "34"
    country_code: str | None    # ISO alpha-2 when exact
    country_name: str | None    # display name when exact
    region_name: str | None     # plan label when ambiguous
    confidence: str             # exact | ambiguous | unknown


def lookup_calling_code(code: str) -> PhoneInfo:
    """Map a calling code (e.g. "+84", "84", "+1876") to geography.

    Longest-prefix match over 3/2/1-digit ITU codes; a shared plan never
    resolves past the plan itself.
    """
    digits_match = _DIGITS.search(code or "")
    if digits_match is None:
        return PhoneInfo(None, None, None, None, None, "unknown")
    digits = digits_match.group()
    for length in (3, 2, 1):
        candidate = "+" + digits[:length]
        if length > len(digits):
            continue
        if candidate in _SHARED:
            return PhoneInfo(candidate, None, None, None, _SHARED[candidate], "ambiguous")
        if candidate in _EXACT:
            iso, name = _EXACT[candidate]
            return PhoneInfo(candidate, None, iso, name, None, "exact")
    # Recognisable code shape, but not in our tables.
    return PhoneInfo("+" + digits[:3], None, None, None, None, "unknown")


def parse_phone_hint(raw: str) -> PhoneInfo:
    """Parse a masked phone hint into prefix + suffix + geography.

    Geography is attempted only when the hint carries an explicit '+' calling
    code; a bare local number stays `unknown` (we never infer from proxy IP).
    The national-number middle is discarded — only the trailing suffix is kept.
    """
    text = (raw or "").strip()
    runs = _DIGITS.findall(text)
    # Keep only the last few digits: a real hint reveals 2–4, and capping means
    # even a fully-unmasked number can't leak its middle through this field.
    suffix = runs[-1][-4:] if runs else None

    if not text.startswith("+"):
        return PhoneInfo(None, suffix, None, None, None, "unknown")

    geo = lookup_calling_code(text)
    return PhoneInfo(geo.prefix, suffix, geo.country_code, geo.country_name,
                     geo.region_name, geo.confidence)
