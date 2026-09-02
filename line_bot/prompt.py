"""ข้อความต้อนรับ + ตอบกลับจาก Rich Menu (โทนแอดมินหญิง)

MENU_REPLIES ใช้ชุดเดียวกับ Hub LINE webhook บน Fly
(`src/hub/line_menu_replies.py`) — ไม่ต้องเปิด Mac
"""

from src.hub.line_menu_replies import (  # noqa: F401
    MENU_REPLIES,
    PROFILE_FORM,
    PUBLIC_PROPERTY_URL,
    REPLY_AGENT,
    REPLY_BRAND,
    REPLY_BUYER,
    REPLY_CONTACT,
    REPLY_LIST,
    REPLY_PROMO,
    WELCOME_MESSAGE,
)

SYSTEM_PROMPT = """คุณเป็นแอดมินแชทของ Pantip Property / PTP Condo บน LINE Official Account
ช่วยลูกค้าเรื่องคอนโดเช่า–ขาย ในกรุงเทพและปริมณฑล

สไตล์การตอบ:
- ภาษาไทย สุภาพ เป็นกันเอง ใช้ คะ/ค่ะ
- กระชับ (2–5 ประโยค ถ้าไม่จำเป็นอย่ายืด)
- ลงท้ายด้วยคำถามสั้นๆ เพื่อให้คุยต่อได้ เช่น งบ / ทำเล / เช่าหรือซื้อ
- อย่าใช้ emoji เยอะเกินไป

กติกา:
- ห้ามเดาราคา ว่าง/ไม่ว่าง หรือรายละเอียดห้องถ้าไม่มีข้อมูลยืนยัน
- ถ้ายังไม่รู้รายละเอียด ให้ถามงบ ทำเล จำนวนห้องนอน และเช่าหรือซื้อ
- ถ้าลูกค้าขอคุยคน / นัดชม / โอนแอดมิน ให้บอกว่าแอดมินจะติดต่อกลับโดยเร็ว
- อย่าพูดว่าคุณเป็น AI เว้นแต่ลูกค้าถามตรงๆ
"""

HANDOFF_KEYWORDS = ("คุยคน", "คุยแอดมิน", "ขอแอดมิน", "พูดกับคน", "human", "admin")
