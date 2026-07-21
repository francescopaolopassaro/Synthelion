# Synthelion — Python port of Caveman.PrivacyGuard (https://github.com/francescopaolopassaro/Caveman.PrivacyGuard)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
"""Algorithmic checksum validators for national ID/tax/bank-number formats — the
same ~30 validators Caveman.PrivacyGuard (C#) ships, direct arithmetic ports, not
just format regexes. A regex alone (`\\d{16}`) matches plenty of non-IDs; running
the real checksum is what turns a format match into an actual detection.

Each validator is a pure `str -> bool` function, registered in `PRIVACY_VALIDATORS`
under the same key names as `privacy_rules.yaml`'s `validator_name` field, so
`PrivacyAnalyzer` can look one up by name with zero hardcoded coupling to which
country/category uses which validator.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Callable

_IBAN_FORMAT_RE = re.compile(r"^[A-Z]{2}\d{2}[A-Z0-9]{4,30}$")
_NINO_GB_RE = re.compile(r"^[A-Z]{2}\d{6}[A-D]$")
_CF_IT_RE = re.compile(r"^[A-Z]{6}[0-9LMNPQRSTUV]{2}[ABCDEHLMPRST][0-9LMNPQRSTUV]{2}[A-Z][0-9LMNPQRSTUV]{3}[A-Z]$")


def validate_iban(value: str) -> bool:
    c = value.replace(" ", "").upper()
    if not _IBAN_FORMAT_RE.match(c):
        return False
    num = ""
    for ch in c[4:] + c[:4]:
        num += f"{ord(ch) - ord('A') + 10:02d}" if ch.isalpha() else ch
    rem = 0
    for ch in num:
        rem = (rem * 10 + int(ch)) % 97
    return rem == 1


def validate_luhn(value: str) -> bool:
    digits = [ch for ch in value if ch.isdigit()]
    if not (13 <= len(digits) <= 19):
        return False
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def validate_cf_it(cf: str) -> bool:
    if len(cf) != 16:
        return False
    cf = cf.upper()
    if not _CF_IT_RE.match(cf):
        return False
    odd_d = [1, 0, 5, 7, 9, 13, 15, 17, 19, 21]
    odd_l = [1, 0, 5, 7, 9, 13, 15, 17, 19, 21, 2, 4, 18, 20, 11, 3, 6, 8, 12, 14, 16, 10, 22, 25, 24, 23]
    total = 0
    for i in range(15):
        ch = cf[i]
        odd = i % 2 == 0
        if ch.isdigit():
            total += odd_d[int(ch)] if odd else int(ch)
        else:
            total += odd_l[ord(ch) - ord("A")] if odd else ord(ch) - ord("A")
    return chr(ord("A") + total % 26) == cf[15]


def validate_piva_it(piva: str) -> bool:
    c = piva.replace("IT", "")
    if len(c) != 11 or not c.isdigit():
        return False
    w = [2, 1, 2, 1, 2, 1, 2, 1, 2, 1]
    total = 0
    for i in range(10):
        v = int(c[i]) * w[i]
        total += v - 9 if v > 9 else v
    return (10 - total % 10) % 10 == int(c[10])


def validate_nir_fr(nir: str) -> bool:
    clean = nir.replace(" ", "")
    if len(clean) != 15 or not clean.isdigit():
        return False
    first13 = int(clean[:13])
    check = int(clean[13:15])
    return (97 - (first13 % 97)) == check


def validate_nif_es(nif: str) -> bool:
    clean = nif.upper().replace(" ", "")
    if len(clean) != 9 or not clean[:8].isdigit():
        return False
    n = int(clean[:8])
    return "TRWAGMYFPDXBNJZSQVHLCKE"[n % 23] == clean[8]


def validate_pesel_pl(pesel: str) -> bool:
    if len(pesel) != 11 or not pesel.isdigit():
        return False
    w = [1, 3, 7, 9, 1, 3, 7, 9, 1, 3, 1]
    total = sum(int(pesel[i]) * w[i] for i in range(11))
    return total % 10 == 0


def validate_bsn_nl(bsn: str) -> bool:
    if len(bsn) != 9 or not bsn.isdigit():
        return False
    w = [9, 8, 7, 6, 5, 4, 3, 2, -1]
    total = sum(int(bsn[i]) * w[i] for i in range(9))
    return total % 11 == 0


def validate_personnummer_se(s: str) -> bool:
    clean = s.replace("-", "")
    if len(clean) != 10 or not clean.isdigit():
        return False
    total = 0
    for i in range(9):
        n = int(clean[i]) * (2 if i % 2 == 0 else 1)
        total += n - 9 if n > 9 else n
    return (10 - total % 10) % 10 == int(clean[9])


def validate_hetu_fi(s: str) -> bool:
    if len(s) != 11 or s[6] not in "+-ABCDEF":
        return False
    num_str = s[:6] + s[7:10]
    if not num_str.isdigit():
        return False
    n = int(num_str)
    return "0123456789ABCDEFHJKLMNPRSTUVWXY"[n % 31] == s[10]


def validate_cpr_dk(s: str) -> bool:
    clean = s.replace("-", "")
    if len(clean) != 10 or not clean.isdigit():
        return False
    w = [4, 3, 2, 7, 6, 5, 4, 3, 2, 1]
    total = sum(int(clean[i]) * w[i] for i in range(10))
    return total % 11 == 0


def validate_nif_pt(s: str) -> bool:
    if len(s) != 9 or not s.isdigit():
        return False
    w = [9, 8, 7, 6, 5, 4, 3, 2]
    total = sum(int(s[i]) * w[i] for i in range(8))
    ctrl = 11 - (total % 11)
    if ctrl >= 10:
        ctrl = 0
    return ctrl == int(s[8])


def validate_ppsn_ie(s: str) -> bool:
    clean = s.upper().replace(" ", "")
    if len(clean) not in (8, 9):
        return False
    if not clean[:7].isdigit():
        return False
    w = [8, 7, 6, 5, 4, 3, 2]
    total = sum(int(clean[i]) * w[i] for i in range(7))
    expected = "ABCDEFGHIJKLMNOPQRSTUVW"[total % 23]
    if clean[7] != expected:
        return False
    return len(clean) != 9 or clean[8] == "W"


def validate_afm_gr(s: str) -> bool:
    if len(s) != 9 or not s.isdigit():
        return False
    w = [256, 128, 64, 32, 16, 8, 4, 2]
    total = sum(int(s[i]) * w[i] for i in range(8))
    return (total % 11) % 10 == int(s[8])


def validate_rc_cz(s: str) -> bool:
    clean = s.replace("/", "")
    if len(clean) not in (9, 10) or not clean.isdigit():
        return False
    y, m = int(clean[0:2]), int(clean[2:4])
    if m > 50:
        m -= 50
    try:
        datetime.strptime(f"{y:02d}-{m:02d}-{int(clean[4:6]):02d}", "%y-%m-%d")
    except ValueError:
        return False
    if len(clean) == 10:
        first9 = int(clean[:9])
        check = first9 % 11
        if check == 10:
            return False
        return check == int(clean[9])
    return True


def validate_cnp_ro(s: str) -> bool:
    if len(s) != 13 or not s.isdigit():
        return False
    w = [2, 7, 9, 1, 4, 6, 3, 5, 8, 2, 7, 9]
    total = sum(int(s[i]) * w[i] for i in range(12))
    ctrl = total % 11
    if ctrl == 10:
        ctrl = 1
    return ctrl == int(s[12])


def validate_egn_bg(s: str) -> bool:
    if len(s) != 10 or not s.isdigit():
        return False
    w = [2, 4, 8, 5, 10, 9, 7, 3, 6]
    total = sum(int(s[i]) * w[i] for i in range(9))
    return total % 11 % 10 == int(s[9])


def validate_oib_hr(s: str) -> bool:
    if len(s) != 11 or not s.isdigit():
        return False
    total = sum(int(s[i]) * (11 - i) for i in range(10))
    ctrl = 11 - (total % 11)
    if ctrl == 10:
        ctrl = 0
    return ctrl == int(s[10])


def validate_emso_si(s: str) -> bool:
    if len(s) != 13 or not s.isdigit():
        return False
    w = [7, 6, 5, 4, 3, 2, 7, 6, 5, 4, 3, 2]
    total = sum(int(s[i]) * w[i] for i in range(12))
    ctrl = 11 - (total % 11)
    if ctrl >= 10:
        ctrl = 0
    return ctrl == int(s[12])


def _validate_lt_ee_style(s: str) -> bool:
    """AK_LT and IK_EE share the exact same two-pass weighting algorithm."""
    if len(s) != 11 or not s.isdigit():
        return False
    w1 = [1, 2, 3, 4, 5, 6, 7, 8, 9, 1]
    w2 = [3, 4, 5, 6, 7, 8, 9, 1, 2, 3]
    total = sum(int(s[i]) * w1[i] for i in range(10))
    ctrl = total % 11
    if ctrl == 10:
        total = sum(int(s[i]) * w2[i] for i in range(10))
        ctrl = total % 11
        if ctrl == 10:
            ctrl = 0
    return ctrl == int(s[10])


def validate_ak_lt(s: str) -> bool:
    return _validate_lt_ee_style(s)


def validate_ik_ee(s: str) -> bool:
    return _validate_lt_ee_style(s)


def validate_pk_lv(s: str) -> bool:
    clean = s.replace("-", "")
    if len(clean) != 11 or not clean.isdigit():
        return False
    w = [1, 6, 3, 7, 9, 10, 5, 8, 4, 2]
    total = sum(int(clean[i]) * w[i] for i in range(10))
    ctrl = 11 - (total % 11)
    if ctrl == 10:
        ctrl = 0
    return ctrl == int(clean[10])


def validate_steuer_id_de(s: str) -> bool:
    if len(s) != 11 or not s.isdigit():
        return False
    w = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    total = sum(int(s[i]) * w[i] for i in range(10))
    rem = total % 11
    expected = 0 if rem == 0 else 11 - rem
    return expected != 10 and expected == int(s[10])


def validate_nn_be(s: str) -> bool:
    if len(s) != 11 or not s.isdigit():
        return False
    first9 = int(s[:9])
    check = int(s[9:11])
    return (97 - (first9 % 97)) % 100 == check


def validate_nino_gb(s: str) -> bool:
    clean = s.replace(" ", "").upper()
    if not _NINO_GB_RE.match(clean):
        return False
    prefix = clean[:2]
    if prefix in ("BG", "GB", "NK", "KN", "TN", "NT", "ZZ"):
        return False
    if clean[0] in "DFIQUV":
        return False
    if clean[1] in "DFIOQUV":
        return False
    return True


def validate_ahv_ch(s: str) -> bool:
    clean = s.replace(".", "").replace(" ", "")
    if len(clean) != 13 or not clean.isdigit() or not clean.startswith("756"):
        return False
    total = 0
    for i in range(12):
        d = int(clean[i])
        total += d if i % 2 == 0 else d * 3
    check = (10 - (total % 10)) % 10
    return check == int(clean[12])


def validate_id_cn(s: str) -> bool:
    clean = s.upper()
    if len(clean) != 18 or not clean[:17].isdigit():
        return False
    if clean[17] != "X" and not clean[17].isdigit():
        return False
    w = [7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2]
    total = sum(int(clean[i]) * w[i] for i in range(17))
    check_chars = "10X98765432"
    return check_chars[total % 11] == clean[17]


def validate_inn_ru(s: str) -> bool:
    if len(s) != 12 or not s.isdigit():
        return False
    w1 = [7, 2, 4, 10, 3, 5, 9, 4, 6, 8]
    w2 = [3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8]
    c1 = sum(int(s[i]) * w1[i] for i in range(10)) % 11 % 10
    c2 = sum(int(s[i]) * w2[i] for i in range(11)) % 11 % 10
    return c1 == int(s[10]) and c2 == int(s[11])


def validate_idcard_de(s: str) -> bool:
    c = s.upper()
    if len(c) != 9 or not c[8].isdigit():
        return False
    w = [7, 3, 1, 7, 3, 1, 7, 3]
    total = 0
    for i in range(8):
        ch = c[i]
        if ch.isdigit():
            total += int(ch) * w[i]
        elif ch.isalpha():
            total += (ord(ch) - ord("A") + 10) * w[i]
        else:
            return False
    return total % 10 == int(c[8])


def validate_rnokpp_ua(s: str) -> bool:
    if len(s) != 10 or not s.isdigit():
        return False
    w = [-1, 5, 7, 9, 4, 6, 10, 5, 7]
    total = sum(int(s[i]) * w[i] for i in range(9))
    control = ((total % 11) + 11) % 11 % 10
    return control == int(s[9])


PRIVACY_VALIDATORS: dict[str, Callable[[str], bool]] = {
    "IBAN": validate_iban,
    "LUHN": validate_luhn,
    "CF_IT": validate_cf_it,
    "PIVA_IT": validate_piva_it,
    "NIR_FR": validate_nir_fr,
    "NIF_ES": validate_nif_es,
    "PESEL_PL": validate_pesel_pl,
    "BSN_NL": validate_bsn_nl,
    "PERSONNUMMER_SE": validate_personnummer_se,
    "HETU_FI": validate_hetu_fi,
    "CPR_DK": validate_cpr_dk,
    "NIF_PT": validate_nif_pt,
    "PPSN_IE": validate_ppsn_ie,
    "AFM_GR": validate_afm_gr,
    "RC_CZ": validate_rc_cz,
    "CNP_RO": validate_cnp_ro,
    "EGN_BG": validate_egn_bg,
    "OIB_HR": validate_oib_hr,
    "EMSO_SI": validate_emso_si,
    "AK_LT": validate_ak_lt,
    "PK_LV": validate_pk_lv,
    "IK_EE": validate_ik_ee,
    "STEUER_ID_DE": validate_steuer_id_de,
    "NN_BE": validate_nn_be,
    "NINO_GB": validate_nino_gb,
    "AHV_CH": validate_ahv_ch,
    "ID_CN": validate_id_cn,
    "INN_RU": validate_inn_ru,
    "IDCARD_DE": validate_idcard_de,
    "RNOKPP_UA": validate_rnokpp_ua,
}


def get_validator(name: str) -> Callable[[str], bool] | None:
    return PRIVACY_VALIDATORS.get(name.upper())
