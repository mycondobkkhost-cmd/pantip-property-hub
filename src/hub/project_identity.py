#!/usr/bin/env python3
"""Project identity: stronger normalization + persistent alias map."""

from __future__ import annotations

import json
import re
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
ALIASES_PATH = BASE_DIR / "data" / "project_aliases.json"

# Never collapse these families into each other
PROTECTED_PREFIXES = (
    "life_asoke",
    "thru_thonglor",
)

# High-confidence typo / spelling redirects (source soft-key → target soft-key)
KNOWN_TYPO_MAP: dict[str, str] = {
    "xthuaikwang": "xthuaikhwang",
    "ideorama9asok": "ideorama9asoke",
    "28chidrom": "28chidlom",
    "rhythmasokell": "rhythmasoke2",
    "rhythmasokeii": "rhythmasoke2",
}


def soft_norm(name: str) -> str:
    """Stronger identity key used for duplicate detection + alias resolve."""
    n = (name or "").lower().strip()
    # close unclosed parentheses so Thai aliases inside still strip
    if n.count("(") > n.count(")"):
        n = n + (")" * (n.count("(") - n.count(")")))
    # drop parenthetical aliases
    n = re.sub(r"\(.*?\)", " ", n)
    # bilingual after colon / dash often Thai display name
    n = re.split(r"\s*[:：]\s*", n, maxsplit=1)[0]
    # roman numerals / doubled L typos for phase numbers
    n = re.sub(r"\biii\b", "3", n)
    n = re.sub(r"\bii\b", "2", n)
    n = re.sub(r"\bi\b", "1", n)
    n = re.sub(r"ll\b", "2", n)
    n = re.sub(r"[()（）]", " ", n)
    n = re.sub(r"[^a-z0-9ก-๙]", "", n)
    # common spelling variants (avoid turning khwang → khkhwang)
    n = re.sub(r"(?<![a-z])kwang|(?<!h)kwang", "khwang", n)
    n = n.replace("petchaburi", "phetchaburi").replace("petchburi", "phetchaburi")
    if n.endswith("thonglo"):
        n = n + "r"
    return n


def special_bucket(soft: str) -> str | None:
    if len(soft) < 3:
        return None
    if "thru" in soft and "thonglor" in soft:
        return "thru_thonglor"
    if "lifeasoke" in soft or soft.startswith("lifeasoke"):
        if "hype" in soft:
            return "life_asoke_hype"
        if "rama9" in soft:
            return "life_asoke_rama9"
        return "life_asoke"
    return None


def project_bucket(name: str) -> str | None:
    soft = soft_norm(name)
    if len(soft) < 3:
        return None
    special = special_bucket(soft)
    if special:
        return special
    # apply known typo map onto soft key
    soft = KNOWN_TYPO_MAP.get(soft, soft)
    return soft


def load_aliases() -> dict:
    if not ALIASES_PATH.exists():
        return {"version": 1, "variant_to_canonical": {}, "decisions": []}
    try:
        return json.loads(ALIASES_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"version": 1, "variant_to_canonical": {}, "decisions": []}


def save_aliases(data: dict) -> None:
    ALIASES_PATH.parent.mkdir(parents=True, exist_ok=True)
    ALIASES_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def resolve_bucket(name: str, aliases: dict | None = None) -> str | None:
    """Map a display/sheet name → canonical bucket_key (aliases win)."""
    soft = soft_norm(name)
    if len(soft) < 3:
        return None
    data = aliases if aliases is not None else load_aliases()
    vmap = data.get("variant_to_canonical") or {}
    # allow mapping by soft key or raw bucket
    if soft in vmap:
        return vmap[soft]
    base = project_bucket(name)
    if base and base in vmap:
        return vmap[base]
    return base


def levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            ins = cur[j - 1] + 1
            delete = prev[j] + 1
            sub = prev[j - 1] + (ca != cb)
            cur.append(min(ins, delete, sub))
        prev = cur
    return prev[-1]


def is_protected_pair(a: str, b: str) -> bool:
    """True if these buckets must never auto-merge."""
    for pref in PROTECTED_PREFIXES:
        a_hit = a == pref or a.startswith(pref + "_")
        b_hit = b == pref or b.startswith(pref + "_")
        if a_hit or b_hit:
            # allow merge only if identical protected bucket
            return a != b
    # Park 24 vs Park Origin style
    if ("park24" in a and "parkorigin" in b) or ("park24" in b and "parkorigin" in a):
        return True
    if ("park24" in a and "parkorigin" in a) or ("park24" in b and "parkorigin" in b):
        # combined junk names — treat carefully as medium, not hard protect
        return False
    return False


def _phase_suffix(soft: str) -> str:
    m = re.search(r"(\d+)$", soft)
    return m.group(1) if m else ""


def classify_duplicate_pair(
    bucket_a: str,
    bucket_b: str,
    name_a: str,
    name_b: str,
    count_a: int,
    count_b: int,
) -> str:
    """Return high | medium | low."""
    if bucket_a == bucket_b:
        return "high"
    if is_protected_pair(bucket_a, bucket_b):
        return "low"

    sa, sb = soft_norm(name_a), soft_norm(name_b)
    if not sa or not sb:
        return "low"
    if sa == sb:
        return "high"
    if KNOWN_TYPO_MAP.get(sa) == sb or KNOWN_TYPO_MAP.get(sb) == sa:
        return "high"
    if KNOWN_TYPO_MAP.get(sa, sa) == KNOWN_TYPO_MAP.get(sb, sb):
        return "high"

    # Different building phases / soi numbers must never auto-merge
    pa, pb = _phase_suffix(sa), _phase_suffix(sb)
    if pa != pb:
        # strip trailing digits and compare stems
        stem_a = re.sub(r"\d+$", "", sa)
        stem_b = re.sub(r"\d+$", "", sb)
        if stem_a == stem_b or stem_a.startswith(stem_b) or stem_b.startswith(stem_a):
            return "low"

    # latin-only keys: small edit distance
    if re.fullmatch(r"[a-z0-9]+", sa) and re.fullmatch(r"[a-z0-9]+", sb):
        dist = levenshtein(sa, sb)
        maxlen = max(len(sa), len(sb))
        if maxlen >= 8 and dist == 1 and pa == pb:
            return "high"
        if maxlen >= 8 and dist == 2:
            return "medium"
        if sa.startswith(sb) or sb.startswith(sa):
            longer, shorter = (sa, sb) if len(sa) > len(sb) else (sb, sa)
            suffix = longer[len(shorter) :]
            if suffix.isdigit() or suffix in {"2", "3"}:
                return "low"

    stem = 0
    for i in range(min(len(sa), len(sb))):
        if sa[i] == sb[i]:
            stem += 1
        else:
            break
    if stem >= 12 and abs(len(sa) - len(sb)) <= 3 and pa == pb:
        return "medium"

    return "low"
