"""
Enrich project master forms (ทำเล / BTS-MRT) from names + known Bangkok corridors.

Zone tags = neighbourhood / landmarks (ทองหล่อ, RCA, รพ.กรุงเทพ, …)
Transit tags = rail stations only (BTS / MRT / ARL)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from src.hub.project_store import (
    dedupe_transit,
    load_projects,
    load_properties,
    persist,
    project_bucket,
    project_location_label,
    sync_project_listings_location_ref,
)


def _norm(s: str) -> str:
    n = (s or "").lower()
    n = re.sub(r"\(.*?\)", " ", n)
    n = re.sub(r"[()（）\-–—_/|,]", " ", n)
    n = re.sub(r"\s+", " ", n).strip()
    # collapse for contains checks
    return re.sub(r"[^a-z0-9ก-๙]", "", n)


# Canonical station labels
STATION_ALIASES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(bts\s*)?(สถานี\s*)?ทองหล่อ|thong\s*lo[rn]?|thonglor", re.I), "BTS ทองหล่อ"),
    (re.compile(r"(bts\s*)?(สถานี\s*)?เอกมัย|ekkamai|ekamai", re.I), "BTS เอกมัย"),
    (re.compile(r"(bts\s*)?(สถานี\s*)?พร้อมพงษ์|phrom\s*phong|phromphong", re.I), "BTS พร้อมพงษ์"),
    (re.compile(r"(bts\s*)?(สถานี\s*)?อโศก|asok[e]?", re.I), "BTS อโศก"),
    (re.compile(r"(bts\s*)?(สถานี\s*)?นานา|nana", re.I), "BTS นานา"),
    (re.compile(r"(bts\s*)?(สถานี\s*)?ชิดลม|chidlom|chitlom", re.I), "BTS ชิดลม"),
    (re.compile(r"(bts\s*)?(สถานี\s*)?เพลินจิต|ploenchit", re.I), "BTS เพลินจิต"),
    (re.compile(r"(bts\s*)?(สถานี\s*)?อ่อนนุช|on\s*nut|onnut", re.I), "BTS อ่อนนุช"),
    (re.compile(r"(bts\s*)?(สถานี\s*)?พระโขนง|phra\s*khanong", re.I), "BTS พระโขนง"),
    (re.compile(r"(bts\s*)?(สถานี\s*)?บางจาก|bangchak|bang\s*chak", re.I), "BTS บางจาก"),
    (re.compile(r"(bts\s*)?(สถานี\s*)?ปุณณวิถี|punnawithi", re.I), "BTS ปุณณวิถี"),
    (re.compile(r"(bts\s*)?(สถานี\s*)?อุดมสุข|udom\s*suk|udomsuk", re.I), "BTS อุดมสุข"),
    (re.compile(r"(bts\s*)?(สถานี\s*)?บางนา|bang\s*na|bangna", re.I), "BTS บางนา"),
    (re.compile(r"(bts\s*)?(สถานี\s*)?แบริ่ง|bearing", re.I), "BTS แบริ่ง"),
    (re.compile(r"(bts\s*)?(สถานี\s*)?สำโรง|samrong", re.I), "BTS สำโรง"),
    (re.compile(r"(bts\s*)?(สถานี\s*)?อารีย์|ari(?![a-z])", re.I), "BTS อารีย์"),
    (re.compile(r"(bts\s*)?(สถานี\s*)?สะพานควาย|saphan\s*khwai", re.I), "BTS สะพานควาย"),
    (re.compile(r"(bts\s*)?(สถานี\s*)?ห้าแยกลาดพร้าว|ha\s*yaek\s*lat\s*phrao", re.I), "BTS ห้าแยกลาดพร้าว"),
    (re.compile(r"(bts\s*)?(สถานี\s*)?พญาไท|phaya\s*thai", re.I), "BTS พญาไท"),
    (re.compile(r"(bts\s*)?(สถานี\s*)?ราชเทวี|ratchathewi", re.I), "BTS ราชเทวี"),
    (re.compile(r"(bts\s*)?(สถานี\s*)?ศาลาแดง|sala\s*daeng", re.I), "BTS ศาลาแดง"),
    (re.compile(r"(bts\s*)?(สถานี\s*)?ช่องนนทรี|chong\s*nonsi", re.I), "BTS ช่องนนทรี"),
    (re.compile(r"(bts\s*)?(สถานี\s*)?สุรศักดิ์|surasak", re.I), "BTS สุรศักดิ์"),
    (re.compile(r"(bts\s*)?(สถานี\s*)?กรุงธนบุรี|krung\s*thon\s*buri", re.I), "BTS กรุงธนบุรี"),
    (re.compile(r"(bts\s*)?(สถานี\s*)?เจริญนคร|charoen\s*nakhon", re.I), "BTS เจริญนคร"),
    (re.compile(r"(bts\s*)?(สถานี\s*)?ตลาดพลู|talat\s*phlu", re.I), "BTS ตลาดพลู"),
    (re.compile(r"(bts\s*)?(สถานี\s*)?วุฒากาศ|wutthakat", re.I), "BTS วุฒากาศ"),
    (re.compile(r"(bts\s*)?(สถานี\s*)?สายหยุด|sai\s*yud", re.I), "BTS สายหยุด"),
    (re.compile(r"(bts\s*)?(สถานี\s*)?สะพานตากสิน|saphan\s*taksin", re.I), "BTS สะพานตากสิน"),
    (re.compile(r"(bts\s*)?(สถานี\s*)?วงเวียนใหญ่|wongwian\s*yai|wong\s*wian\s*yai", re.I), "BTS วงเวียนใหญ่"),
    (re.compile(r"(bts\s*)?(สถานี\s*)?สนามกีฬาแห่งชาติ|national\s*stadium", re.I), "BTS สนามกีฬาแห่งชาติ"),
    (re.compile(r"(bts\s*)?(สถานี\s*)?สยาม|siam(?![a-z])", re.I), "BTS สยาม"),
    (re.compile(r"(bts\s*)?(สถานี\s*)?หมอชิต|mo\s*chit", re.I), "BTS หมอชิต"),
    (re.compile(r"(bts\s*)?(สถานี\s*)?รัชโยธิน|ratchayothin", re.I), "BTS รัชโยธิน"),
    (re.compile(r"(?:mrt\s*)?(สถานี\s*)?รามอินทรา|ramintra", re.I), "MRT รามอินทรา"),
    (re.compile(r"(?:mrt\s*)?(สถานี\s*)?ไฟฉาย|faichai", re.I), "MRT ไฟฉาย"),
    (re.compile(r"(?:mrt\s*)?(สถานี\s*)?อิสรภาพ|itsaraphap", re.I), "MRT อิสรภาพ"),
    (re.compile(r"mrt\s*(สถานี\s*)?สีลม|si\s*lom", re.I), "MRT สีลม"),
    (re.compile(r"mrt\s*(สถานี\s*)?สามย่าน|sam\s*yan", re.I), "MRT สามย่าน"),
    (re.compile(r"mrt\s*(สถานี\s*)?หัวลำโพง|hua\s*lamphong", re.I), "MRT หัวลำโพง"),
    (re.compile(r"mrt\s*(สถานี\s*)?เพชรบุรี|phetch?aburi|petchaburi|phetburi", re.I), "MRT เพชรบุรี"),
    # Require MRT prefix — bare "sukhumvit" is a road name, not MRT สุขุมวิท
    (re.compile(r"mrt\s*(สถานี\s*)?สุขุมวิท|mrt\s*sukhumvit", re.I), "MRT สุขุมวิท"),
    (re.compile(r"mrt\s*(สถานี\s*)?พระราม\s*9|rama\s*9", re.I), "MRT พระราม 9"),
    (re.compile(r"mrt\s*(สถานี\s*)?ห้วยขวาง|huai\s*khwang", re.I), "MRT ห้วยขวาง"),
    (re.compile(r"mrt\s*(สถานี\s*)?สุทธิสาร|sutthisan", re.I), "MRT สุทธิสาร"),
    (re.compile(r"mrt\s*(สถานี\s*)?รัชดา|ratchada", re.I), "MRT รัชดาภิเษก"),
    (re.compile(r"mrt\s*(สถานี\s*)?ลาดพร้าว|lat\s*phrao|ladprao", re.I), "MRT ลาดพร้าว"),
    (re.compile(r"mrt\s*(สถานี\s*)?พหลโยธิน|phahon", re.I), "MRT พหลโยธิน"),
    (re.compile(r"mrt\s*(สถานี\s*)?ลุมพินี|lumpini|lumphini", re.I), "MRT ลุมพินี"),
    (re.compile(r"mrt\s*(สถานี\s*)?ศูนย์วัฒนธรรม|thailand\s*cultural", re.I), "MRT ศูนย์วัฒนธรรมแห่งประเทศไทย"),
    (re.compile(r"mrt\s*(สถานี\s*)?ศูนย์(การ)?ประชุม|sirikit", re.I), "MRT ศูนย์ประชุมแห่งชาติสิริกิติ์"),
    (re.compile(r"mrt\s*(สถานี\s*)?เตาปูน|tao\s*poon", re.I), "MRT เตาปูน"),
    (re.compile(r"mrt\s*(สถานี\s*)?บางซื่อ|bang\s*sue", re.I), "MRT บางซื่อ"),
    (re.compile(r"mrt\s*(สถานี\s*)?ศรีเอี่ยม|si\s*iam", re.I), "MRT ศรีเอี่ยม"),
    (re.compile(r"mrt\s*(สถานี\s*)?ศรีนุช|si\s*nuch", re.I), "MRT ศรีนุช"),
    (re.compile(r"mrt\s*(สถานี\s*)?รามคำแหง|ramkhamhaeng", re.I), "MRT รามคำแหง"),
    (re.compile(r"mrt\s*(สถานี\s*)?บางกะปิ|bang\s*kapi", re.I), "MRT บางกะปิ"),
    (re.compile(r"(arl|alr|airport\s*(rail\s*)?link|airport\s*link)\s*(สถานี\s*)?มักกะสัน|makkasan", re.I), "ARL มักกะสัน"),
    (re.compile(r"(arl|alr|airport\s*(rail\s*)?link|airport\s*link)\s*(สถานี\s*)?รามคำแหง", re.I), "ARL รามคำแหง"),
    (re.compile(r"(arl|alr|airport\s*(rail\s*)?link|airport\s*link)\s*(สถานี\s*)?หัวหมาก|hua\s*mak", re.I), "ARL หัวหมาก"),
    (re.compile(r"(arl|alr|airport\s*(rail\s*)?link|airport\s*link)\s*(สถานี\s*)?พญาไท", re.I), "ARL พญาไท"),
]

# Landmark / area phrases that belong in zone (not transit)
ZONE_ALIASES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"ทองหล่อ|thong\s*lo[rn]?|thonglor", re.I), "ทองหล่อ"),
    (re.compile(r"เอกมัย|ekkamai|ekamai", re.I), "เอกมัย"),
    (re.compile(r"พร้อมพงษ์|phrom\s*phong", re.I), "พร้อมพงษ์"),
    (re.compile(r"อโศก|asok[e]?", re.I), "อโศก"),
    (re.compile(r"นานา|nana", re.I), "นานา"),
    (re.compile(r"เพชรบุรีตัดใหม่|new\s*phetch?aburi|เพชรบุรี", re.I), "เพชรบุรีตัดใหม่"),
    (re.compile(r"\brca\b|อาร์ซีเอ", re.I), "RCA"),
    (re.compile(r"โรงพยาบาลกรุงเทพ|bangkok\s*hospital", re.I), "โรงพยาบาลกรุงเทพ"),
    (re.compile(r"มศว|ศรีนครินทรวิโรฒ|ประสานมิตร|swu", re.I), "มศว ประสานมิตร"),
    (re.compile(r"พระราม\s*9|rama\s*9", re.I), "พระราม 9"),
    (re.compile(r"รัชดา|ratchada", re.I), "รัชดา"),
    (re.compile(r"ลาดพร้าว|ladprao|lat\s*phrao", re.I), "ลาดพร้าว"),
    (re.compile(r"บางนา|bangna|bang\s*na", re.I), "บางนา"),
    (re.compile(r"อ่อนนุช|onnut|on\s*nut", re.I), "อ่อนนุช"),
    (re.compile(r"สาทร|sathorn|sathon", re.I), "สาทร"),
    (re.compile(r"สีลม|silom", re.I), "สีลม"),
    (re.compile(r"อารีย์|ari(?![a-z])", re.I), "อารีย์"),
    (re.compile(r"วิทยุ|wireless", re.I), "วิทยุ"),
    (re.compile(r"หลังสวน|langsuan", re.I), "หลังสวน"),
    (re.compile(r"จุฬา|chula|samyan|สามย่าน", re.I), "สามย่าน"),
    (re.compile(r"รามคำแหง|ramkhamhaeng", re.I), "รามคำแหง"),
    (re.compile(r"ห้วยขวาง|huai\s*khwang", re.I), "ห้วยขวาง"),
    (re.compile(r"สุขุมวิท|sukhumvit", re.I), "สุขุมวิท"),
]

STATION_TO_ZONE = {
    "BTS ทองหล่อ": "ทองหล่อ",
    "BTS เอกมัย": "เอกมัย",
    "BTS พร้อมพงษ์": "พร้อมพงษ์",
    "BTS อโศก": "อโศก",
    "BTS นานา": "นานา",
    "BTS อ่อนนุช": "อ่อนนุช",
    "BTS พระโขนง": "พระโขนง",
    "BTS บางจาก": "บางจาก",
    "BTS ปุณณวิถี": "ปุณณวิถี",
    "BTS อุดมสุข": "อุดมสุข",
    "BTS บางนา": "บางนา",
    "BTS แบริ่ง": "แบริ่ง",
    "BTS อารีย์": "อารีย์",
    "BTS ชิดลม": "ชิดลม",
    "BTS เพลินจิต": "เพลินจิต",
    "BTS ศาลาแดง": "สีลม",
    "BTS ช่องนนทรี": "สาทร",
    "MRT เพชรบุรี": "เพชรบุรีตัดใหม่",
    "MRT พระราม 9": "พระราม 9",
    "MRT สุขุมวิท": "อโศก",
    "MRT ห้วยขวาง": "ห้วยขวาง",
    "MRT รัชดาภิเษก": "รัชดา",
    "MRT ลาดพร้าว": "ลาดพร้าว",
    "MRT ลุมพินี": "ลุมพินี",
    "ARL มักกะสัน": "มักกะสัน",
    "ARL รามคำแหง": "รามคำแหง",
}

# When a corridor is authoritative, do NOT merge sheet noise.
# Sheet tags are often wrong (agents list distant stations for SEO).

# Explicit overrides researched from listing sites / maps (nearest stations only)
PROJECT_OVERRIDES: dict[str, dict] = {
    # Thonglor Tower @ Soi Thonglor 18 — ~1.4km BTS Thong Lo, ~2km BTS Ekkamai
    # Sources: PropertyScout, ThaiCozy, Condonayoo (NOT Phrom Phong / Sirikit)
    "thonglortower": {
        "zones": ["ทองหล่อ"],
        "transit": ["BTS ทองหล่อ", "BTS เอกมัย"],
        "source": "override:maps-nearest",
    },
    "thonglortowercondominium": {
        "zones": ["ทองหล่อ"],
        "transit": ["BTS ทองหล่อ", "BTS เอกมัย"],
        "source": "override:maps-nearest",
    },
    # IDEO Sukhumvit 93 — skywalk to BTS Bang Chak (~80m). Sources: FazWaz, Livinginsider, zmyhome
    "ideosukhumvit93": {
        "zones": ["บางจาก", "พระโขนง", "สุขุมวิท"],
        "transit": ["BTS บางจาก", "BTS อ่อนนุช"],
        "source": "override:livinginsider-bangchak",
    },
    # Thru Thonglor — New Phetchaburi Rd / Bangkok Hospital belt
    "thru_thonglor": {
        "zones": ["ทองหล่อ", "เพชรบุรีตัดใหม่", "RCA", "โรงพยาบาลกรุงเทพ", "มศว ประสานมิตร"],
        "transit": ["BTS ทองหล่อ", "MRT เพชรบุรี", "ARL มักกะสัน"],
        "source": "override:livinginsider-thru",
    },
}

# Landmark pack only for these corridor ids (Phetchaburi Rd / RCA belt) — NOT every Thonglor condo
PETH_LANDMARK_CORRIDORS = {
    "thru_thonglor",
    "niche_pride_thonglor_phet",
    "base_phet_thonglor",
    "cloud_thonglor_phet",
    "lloyd_soonvijai",
    "thonglor_phetchaburi",
}


@dataclass
class CorridorProfile:
    id: str
    zones: list[str]
    transit: list[str]
    # all substrings in normalized name must match one group (OR of AND-groups)
    name_groups: list[list[str]] = field(default_factory=list)
    buckets: list[str] = field(default_factory=list)
    priority: int = 100


# Specific corridors first (lower priority number = match first)
CORRIDORS: list[CorridorProfile] = [
    CorridorProfile(
        id="thru_thonglor",
        buckets=["thru_thonglor"],
        zones=["ทองหล่อ", "เพชรบุรีตัดใหม่", "RCA", "โรงพยาบาลกรุงเทพ", "มศว ประสานมิตร"],
        transit=["BTS ทองหล่อ", "MRT เพชรบุรี", "ARL มักกะสัน"],
        priority=10,
    ),
    CorridorProfile(
        id="niche_pride_thonglor_phet",
        name_groups=[
            ["nichepride", "thong"],
            ["nichepride", "ทอง"],
            ["นิชไพร", "ทอง"],
            ["นิชไพร์ด", "ทอง"],
            ["เดอะนิชไพร", "ทอง"],
        ],
        zones=["ทองหล่อ", "เพชรบุรีตัดใหม่", "RCA", "โรงพยาบาลกรุงเทพ", "มศว ประสานมิตร"],
        transit=["BTS ทองหล่อ", "MRT เพชรบุรี", "ARL มักกะสัน"],
        priority=12,
    ),
    CorridorProfile(
        id="base_phet_thonglor",
        name_groups=[
            ["thebase", "phet", "thong"],
            ["thebase", "เพชร", "ทอง"],
            ["เดอะเบส", "เพชร", "ทอง"],
            ["base", "phetchaburi", "thong"],
            ["base", "phetburi", "thong"],
        ],
        zones=["ทองหล่อ", "เพชรบุรีตัดใหม่", "RCA", "โรงพยาบาลกรุงเทพ", "มศว ประสานมิตร"],
        transit=["BTS ทองหล่อ", "MRT เพชรบุรี", "ARL มักกะสัน"],
        priority=12,
    ),
    CorridorProfile(
        id="capital_ekamai_thonglor",
        name_groups=[
            ["capital", "ekamai"],
            ["capital", "ekkamai"],
            ["capital", "thong"],
            ["แคปิตอล", "เอกมัย"],
            ["แคปปิตัล", "เอกมัย"],
            ["แคปิตอล", "ทอง"],
            ["เดอะแคป", "เอกมัย"],
        ],
        zones=["เอกมัย", "ทองหล่อ"],
        transit=["BTS เอกมัย", "BTS ทองหล่อ"],
        priority=12,
    ),
    CorridorProfile(
        id="cloud_thonglor_phet",
        name_groups=[["cloud", "thong"], ["คลาวด์", "ทอง"], ["cloud", "phet"]],
        zones=["ทองหล่อ", "เพชรบุรีตัดใหม่", "RCA", "โรงพยาบาลกรุงเทพ"],
        transit=["BTS ทองหล่อ", "MRT เพชรบุรี", "ARL มักกะสัน"],
        priority=15,
    ),
    CorridorProfile(
        id="lloyd_soonvijai",
        name_groups=[["lloyd", "thong"], ["ลอยด์", "ทอง"], ["soonvijai"], ["ศูนย์วิจัย"]],
        zones=["ทองหล่อ", "เพชรบุรีตัดใหม่", "โรงพยาบาลกรุงเทพ", "มศว ประสานมิตร"],
        transit=["BTS ทองหล่อ", "MRT เพชรบุรี", "ARL มักกะสัน"],
        priority=15,
    ),
    CorridorProfile(
        id="thonglor_phetchaburi",
        name_groups=[
            ["thong", "phet"],
            ["ทองหล่อ", "เพชร"],
            ["thonglor", "phet"],
        ],
        zones=["ทองหล่อ", "เพชรบุรีตัดใหม่", "RCA", "โรงพยาบาลกรุงเทพ", "มศว ประสานมิตร"],
        transit=["BTS ทองหล่อ", "MRT เพชรบุรี", "ARL มักกะสัน"],
        priority=20,
    ),
    CorridorProfile(
        id="ekamai_thonglor",
        name_groups=[
            ["ekamai", "thong"],
            ["ekkamai", "thong"],
            ["เอกมัย", "ทอง"],
        ],
        zones=["เอกมัย", "ทองหล่อ"],
        transit=["BTS เอกมัย", "BTS ทองหล่อ"],
        priority=25,
    ),
    CorridorProfile(
        id="thonglor",
        name_groups=[["thonglor"], ["thonglo"], ["ทองหล่อ"]],
        zones=["ทองหล่อ"],
        # Nearest only — do NOT dump whole Sukhumvit line
        transit=["BTS ทองหล่อ", "BTS เอกมัย"],
        priority=40,
    ),
    CorridorProfile(
        id="ekamai",
        name_groups=[["ekkamai"], ["ekamai"], ["เอกมัย"]],
        zones=["เอกมัย"],
        transit=["BTS เอกมัย", "BTS ทองหล่อ"],
        priority=45,
    ),
    CorridorProfile(
        id="phrom_phong",
        name_groups=[["phromphong"], ["phrom"], ["พร้อมพงษ์"]],
        zones=["พร้อมพงษ์"],
        transit=["BTS พร้อมพงษ์"],
        priority=45,
    ),
    CorridorProfile(
        id="asoke",
        name_groups=[["asoke"], ["asok"], ["อโศก"], ["lifeasoke"]],
        zones=["อโศก", "สุขุมวิท"],
        transit=["BTS อโศก", "MRT สุขุมวิท"],
        priority=45,
    ),
    CorridorProfile(
        id="rama9",
        name_groups=[["rama9"], ["พระราม9"], ["พระราม๙"]],
        zones=["พระราม 9"],
        transit=["MRT พระราม 9", "ARL มักกะสัน"],
        priority=45,
    ),
    CorridorProfile(
        id="ratchada",
        name_groups=[["ratchada"], ["รัชดา"]],
        zones=["รัชดา"],
        transit=["MRT ห้วยขวาง", "MRT รัชดาภิเษก", "MRT สุทธิสาร"],
        priority=45,
    ),
    CorridorProfile(
        id="onnut",
        name_groups=[["onnut"], ["on nut"], ["อ่อนนุช"], ["sukhumvit77"], ["sukhumvit 77"], ["สุขุมวิท77"]],
        zones=["อ่อนนุช"],
        transit=["BTS อ่อนนุช", "BTS พระโขนง", "BTS บางจาก"],
        priority=45,
    ),
    CorridorProfile(
        id="bangna",
        name_groups=[["bangna"], ["bang na"], ["บางนา"]],
        zones=["บางนา"],
        transit=["BTS บางนา", "BTS แบริ่ง", "MRT ศรีเอี่ยม"],
        priority=45,
    ),
    CorridorProfile(
        id="ladprao",
        name_groups=[["ladprao"], ["latphrao"], ["ลาดพร้าว"]],
        zones=["ลาดพร้าว"],
        transit=["MRT ลาดพร้าว", "BTS ห้าแยกลาดพร้าว"],
        priority=45,
    ),
    CorridorProfile(
        id="ari",
        name_groups=[["อารีย์"], ["btsari"], ["condoari"]],
        zones=["อารีย์"],
        transit=["BTS อารีย์", "BTS สะพานควาย"],
        priority=45,
    ),
    CorridorProfile(
        id="sathorn",
        name_groups=[["sathorn"], ["sathon"], ["สาทร"]],
        zones=["สาทร"],
        transit=["BTS ช่องนนทรี", "BTS สุรศักดิ์", "MRT ลุมพินี"],
        priority=45,
    ),
    CorridorProfile(
        id="silom",
        name_groups=[["silom"], ["สีลม"], ["saladaeng"], ["ศาลาแดง"]],
        zones=["สีลม"],
        transit=["BTS ศาลาแดง", "MRT สีลม"],
        priority=45,
    ),
    CorridorProfile(
        id="ramkhamhaeng",
        name_groups=[["ramkhamhaeng"], ["รามคำแหง"]],
        zones=["รามคำแหง"],
        transit=["ARL รามคำแหง", "MRT รามคำแหง"],
        priority=45,
    ),
    CorridorProfile(
        id="siam",
        name_groups=[["siam"], ["สยาม"], ["kasemsan"], ["เกษมสันต์"]],
        zones=["สยาม", "ปทุมวัน"],
        transit=["BTS สยาม", "BTS ราชเทวี", "BTS ชิดลม", "MRT สามย่าน"],
        priority=45,
    ),
    CorridorProfile(
        id="ratchayothin",
        name_groups=[["ratchayothin"], ["รัชโยธิน"]],
        zones=["รัชโยธิน"],
        transit=["BTS รัชโยธิน", "BTS สะพานควาย", "MRT พหลโยธิน"],
        priority=45,
    ),
    CorridorProfile(
        id="phaholyothin",
        name_groups=[["phaholyothin"], ["phahon"], ["พหลโยธิน"]],
        zones=["พหลโยธิน"],
        transit=["MRT พหลโยธิน", "BTS ห้าแยกลาดพร้าว"],
        priority=45,
    ),
    CorridorProfile(
        id="bangsue",
        name_groups=[["bangsue"], ["bang sue"], ["บางซื่อ"], ["บางซ่อน"], ["prachachuen"], ["ประชานุกูล"], ["ประชาชื่น"]],
        zones=["บางซื่อ"],
        transit=["MRT บางซื่อ", "MRT เตาปูน"],
        priority=45,
    ),
    CorridorProfile(
        id="wongwian_yai",
        name_groups=[["wongwianyai"], ["wongwian"], ["วงเวียนใหญ่"]],
        zones=["วงเวียนใหญ่"],
        transit=["BTS วงเวียนใหญ่", "BTS กรุงธนบุรี"],
        priority=45,
    ),
    CorridorProfile(
        id="charoenkrung",
        name_groups=[["charoenkrung"], ["charoen krung"], ["เจริญกรุง"]],
        zones=["เจริญกรุง"],
        transit=["BTS สะพานตากสิน", "MRT หัวลำโพง"],
        priority=50,
    ),
    CorridorProfile(
        id="ramintra",
        name_groups=[["ramintra"], ["รามอินทรา"]],
        zones=["รามอินทรา"],
        transit=["MRT รามอินทรา"],
        priority=50,
    ),
    CorridorProfile(
        id="riverside",
        name_groups=[["charoennakhon"], ["charoen nakhon"], ["เจริญนคร"], ["krungthonburi"], ["กรุงธนบุรี"], ["wanglang"], ["วังหลัง"]],
        zones=["เจริญนคร"],
        transit=["BTS เจริญนคร", "BTS กรุงธนบุรี"],
        priority=50,
    ),
    CorridorProfile(
        id="lumpini",
        name_groups=[["lumpini"], ["lumphini"], ["ลุมพินี"]],
        zones=["ลุมพินี"],
        transit=["MRT ลุมพินี", "BTS ศาลาแดง"],
        priority=50,
    ),
]


# Sukhumvit soi → primary station
SOI_STATION: list[tuple[range, list[str], list[str]]] = [
    (range(1, 11), ["BTS นานา"], ["นานา"]),
    (range(11, 25), ["BTS อโศก", "MRT สุขุมวิท"], ["อโศก"]),
    (range(25, 33), ["BTS พร้อมพงษ์"], ["พร้อมพงษ์"]),
    (range(33, 49), ["BTS พร้อมพงษ์", "BTS ทองหล่อ"], ["พร้อมพงษ์"]),
    (range(49, 57), ["BTS ทองหล่อ", "BTS เอกมัย"], ["ทองหล่อ"]),
    (range(57, 65), ["BTS เอกมัย", "BTS ทองหล่อ"], ["เอกมัย"]),
    (range(65, 73), ["BTS พระโขนง"], ["พระโขนง"]),
    (range(73, 85), ["BTS อ่อนนุช", "BTS พระโขนง"], ["อ่อนนุช"]),
    # Soi 85–100 → Bang Chak / Punnawithi (e.g. IDEO Sukhumvit 93 @ BTS บางจาก)
    (range(85, 101), ["BTS บางจาก", "BTS ปุณณวิถี"], ["บางจาก"]),
    (range(101, 120), ["BTS แบริ่ง"], ["แบริ่ง"]),
]


def canonicalize_station(text: str) -> str | None:
    t = (text or "").strip()
    if not t or len(t) > 80:
        return None
    # skip pure prose
    if re.search(r"condo near|near bts|ใกล้|นาที|นาที", t, re.I) and not re.search(
        r"\b(bts|mrt|arl|alr)\b", t, re.I
    ):
        return None
    for pat, label in STATION_ALIASES:
        if pat.search(t):
            return label
    return None


def extract_stations(texts: list[str]) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for raw in texts:
        for part in re.split(r"[/,|]| และ ", raw or ""):
            label = canonicalize_station(part.strip())
            if label and label not in seen:
                seen.add(label)
                found.append(label)
    return found


def extract_zones_from_text(text: str) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for pat, label in ZONE_ALIASES:
        if pat.search(text or ""):
            if label not in seen:
                seen.add(label)
                found.append(label)
    return found


def parse_sukhumvit_soi(name: str) -> int | None:
    m = re.search(
        r"(?:sukhumvit|สุขุมวิท|skv|soi)\s*(?:soi\s*)?(\d{1,3})",
        name or "",
        re.I,
    )
    if m:
        return int(m.group(1))
    m = re.search(r"\b(?:sukhumvit|สุขุมวิท)(\d{1,3})\b", name or "", re.I)
    if m:
        return int(m.group(1))
    return None


def match_corridor(proj: dict) -> CorridorProfile | None:
    name = proj.get("canonical_name") or ""
    n = _norm(name)
    # also search aliases
    for a in proj.get("aliases") or []:
        n += _norm(a)
    bucket = proj.get("bucket_key") or project_bucket(name) or ""
    name_blob = " ".join([name] + list(proj.get("aliases") or []))

    ranked = sorted(CORRIDORS, key=lambda c: c.priority)
    for c in ranked:
        if c.buckets and bucket in c.buckets:
            return c
        for group in c.name_groups:
            if all(g in n for g in group):
                return c
        # word-boundary English for short place names
        if c.id == "ari" and re.search(r"(^|[^a-z])ari([^a-z]|$)", name_blob, re.I):
            if re.search(r"อารีย์|\bari\b", name_blob, re.I):
                return c
    return None


def infer_from_soi(name: str) -> tuple[list[str], list[str]]:
    soi = parse_sukhumvit_soi(name)
    if soi is None:
        return [], []
    for rng, transit, zones in SOI_STATION:
        if soi in rng:
            return list(zones), list(transit)
    return [], []


def enrich_project(proj: dict, property_hints: list[str] | None = None) -> tuple[list[str], list[str], str]:
    """Return (zones, transit, source_note).

    Conservative rules:
    - Project overrides win (researched nearest stations).
    - Corridor match → use corridor pack ONLY (ignore sheet SEO noise).
    - Otherwise → at most 2 stations inferred from name / property hints.
    """
    name = proj.get("canonical_name") or ""
    aliases = list(proj.get("aliases") or [])
    bucket = proj.get("bucket_key") or project_bucket(name) or ""

    override = PROJECT_OVERRIDES.get(bucket)
    if override:
        return (
            list(override["zones"]),
            list(override["transit"]),
            str(override.get("source") or "override"),
        )

    # Do NOT feed previous verified tags back in — that re-pollutes corrections.
    hint_blobs = [name] + aliases + list(property_hints or [])
    sheet_stations = extract_stations(hint_blobs)

    corridor = match_corridor(proj)
    source = "existing"
    zones: list[str] = []
    stations: list[str] = []

    if corridor:
        source = f"corridor:{corridor.id}"
        zones = list(corridor.zones)
        stations = list(corridor.transit)
        # Never merge distant sheet stations into corridor packs
    else:
        # Max 2 nearest guesses from name/hints only
        stations = sheet_stations[:2]
        for t in stations:
            z = STATION_TO_ZONE.get(t)
            if z and z not in zones:
                zones.append(z)

    soi_zones, soi_transit = infer_from_soi(name)
    if soi_zones or soi_transit:
        if not corridor:
            source = "sukhumvit_soi"
            # Soi mapping is more reliable than free-text sheet tags
            zones = list(soi_zones) or zones
            stations = list(soi_transit) or stations
        else:
            for z in soi_zones:
                if z not in zones:
                    zones.append(z)

    # Name-based zone hints (area only — not extra stations)
    for z in extract_zones_from_text(name):
        if z not in zones:
            zones.append(z)

    # Derive zone from stations (keep zones tight: primary area first)
    for t in stations:
        z = STATION_TO_ZONE.get(t)
        if z and z not in zones:
            zones.append(z)

    # Landmark pack ONLY for Phetchaburi-belt corridors — not every Thonglor name match
    if corridor and corridor.id in PETH_LANDMARK_CORRIDORS:
        for z in ["เพชรบุรีตัดใหม่", "RCA", "โรงพยาบาลกรุงเทพ", "มศว ประสานมิตร"]:
            if z not in zones:
                zones.append(z)
        if "ARL มักกะสัน" not in stations:
            stations.append("ARL มักกะสัน")
        if "MRT เพชรบุรี" not in stations:
            stations.insert(min(1, len(stations)), "MRT เพชรบุรี")

    # Cap lists — nearest stations only; never leave stations inside zone field
    zones = [z for z in dedupe_transit(zones) if not re.match(r"^(BTS|MRT|ARL|APL)\b", z, re.I)][:5]
    stations = dedupe_transit(stations)[:3]

    if not zones and not stations:
        source = "empty"

    return zones, stations, source


def enrich_all_projects(*, dry_run: bool = False, min_listings: int = 0) -> dict:
    projects = load_projects()
    properties = load_properties()

    # Property location hints for projects missing transit in master
    hints_by_pid: dict[str, list[str]] = {}
    for prop in properties:
        pid = prop.get("project_id")
        if not pid:
            continue
        blob = " ".join(
            [
                prop.get("location_ref") or "",
                " ".join(prop.get("transit_from_sheet") or []),
            ]
        )
        if blob.strip():
            hints_by_pid.setdefault(pid, []).append(blob)

    stats = {
        "projects_total": len(projects),
        "projects_updated": 0,
        "listings_synced": 0,
        "by_source": {},
        "empty": 0,
        "samples": [],
    }

    for proj in projects:
        if int(proj.get("listing_count") or 0) < min_listings:
            continue
        zones, transit, source = enrich_project(proj, hints_by_pid.get(proj["id"]))
        stats["by_source"][source] = stats["by_source"].get(source, 0) + 1
        if source == "empty":
            stats["empty"] += 1
            continue

        proj["zone_verified"] = zones
        proj["zone_unverified"] = []
        proj["transit_verified"] = transit
        proj["transit_unverified"] = []
        proj["location_status"] = "verified"
        n = sync_project_listings_location_ref(proj, properties)
        stats["projects_updated"] += 1
        stats["listings_synced"] += n

        name = proj.get("canonical_name") or ""
        if any(
            k in name.lower()
            for k in (
                "thru thonglor",
                "niche pride",
                "the base phet",
                "capital ekamai",
                "capital ekkamai",
                "นิช",
                "แคป",
                "ทรู ทอง",
            )
        ) or ("ทองหล่อ" in name and int(proj.get("listing_count") or 0) >= 20):
            stats["samples"].append(
                {
                    "name": name,
                    "zones": zones,
                    "transit": transit,
                    "source": source,
                    "location": project_location_label(proj),
                    "listings": n,
                }
            )

    if not dry_run:
        persist(projects, properties)

    return stats
