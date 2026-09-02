# Property Hub — Fly.io (ออกจาก Render)

โดเมนแอดมิน: **https://hub.realxtateth.com/**  
(ไม่แตะ `realxtateth.com` / LivingBKK / LINE)

## ทำไมย้าย

Render แผนฟรีหลับ/ค้างบ่อย — ย้ายไป Fly.io (always-on, `min_machines_running = 1`)

## ไฟล์ที่เกี่ยวข้อง

- `fly.toml` — app `property-hub`, region `sin`, health `/api/health`
- `Dockerfile` — listen `PORT` (Fly ใช้ 8080)
- `scripts/deploy_fly.sh` — deploy + ตั้ง Cloudflare DNS `hub` → `property-hub.fly.dev`
- `scripts/fly_set_secrets.sh` — ดึง env จาก Render export / `.env`
- `scripts/suspend_render_hub.sh` — พัก Render หลังตัด DNS แล้ว (ไม่ลบอัตโนมัติ)

## Deploy ครั้งแรก

```bash
# 1) Login Fly (ครั้งเดียว)
curl -L https://fly.io/install.sh | sh
export PATH="$HOME/.fly/bin:$PATH"
fly auth login

# 2) Export env จาก Render (ถ้ายังมี)
# หรือใช้ไฟล์ /tmp/property-hub-migrate-env.json ที่สร้างไว้แล้ว

# 3) Deploy + DNS
chmod +x scripts/deploy_fly.sh scripts/fly_set_secrets.sh
./scripts/deploy_fly.sh
```

หลัง DNS โปรปาเกต:

- Health: https://hub.realxtateth.com/api/health
- Login: https://hub.realxtateth.com/
- Co-Agent: https://hub.realxtateth.com/co/

## Env ที่ต้องมีบน Fly

| Key | หมายเหตุ |
|-----|---------|
| `HUB_USERS_JSON` | บัญชีล็อกอิน (JSON object) — ตั้งด้วย `scripts/fly_set_secrets.sh` เท่านั้น ห้าม `fly secrets import` ตรงๆ (จะ escape `"` จนล็อกอินพัง) |
| `HUB_SESSION_SECRET` | cookie session |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | เขียนชีท |
| `HUB_GOOGLE_SHEETS_ID` / `GOOGLE_SHEETS_ID` | ชีททดลอง |
| `SOURCE_GOOGLE_SHEETS_ID` / `MAIN_SHEET_CSV_URL` | สำรอง/ฉุกเฉินเท่านั้น (ปิดดึงทับแล้ว) |
| `WAIT_POST_SHEET_CSV_URL` | แท็บรอโพสต์ |
| `HUB_STARTUP_SHEET_SYNC=0` | **ปิด**ดึงชีทตอนบูต (ค่าเริ่มต้น) |
| `HUB_ALLOW_SHEET_PULL=0` | **ปิด** API ดึงชีททับทรัพย์ (เปิด=1 เฉพาะฉุกเฉิน) |
| `HUB_AUTO_SYNC_TO_SHEET=1` | auto push หลังแก้ทรัพย์ (ทางเดียว Hub→ชีท) |

## DNS (Cloudflare)

`CNAME hub` → `property-hub.fly.dev`  
แนะนำ **DNS only** (เทา) ให้ Fly ออกใบรับรองเอง — สคริปต์ตั้งแบบนี้แล้ว

**ห้ามแก้** A/CNAME ของ `@` หรือ `www` (LivingBKK / Netlify)

## หลังย้าย — Render

แอดมินใช้ **เฉพาะ** `https://hub.realxtateth.com`  
พัก (suspend) บริการ `property-hub` บน Render ได้ด้วย `./scripts/suspend_render_hub.sh`  
**อย่าลบ** จนกว่าจะยืนยัน Fly นิ่งแล้วอย่างน้อย 1–2 วัน

## Sync timeout

UI รอผลซิงค์สูงสุด ~7 นาที (startup pull + overview push) — ไม่ควร false-timeout บนโฮสต์ใหม่

## สำคัญ: เครื่องเดียว + volume = SoT · ชีท = สำเนาทางเดียว

- Fly volume `hub_data` → `/app/data` คือ**แหล่งความจริง** (กันข้อมูลหายตอนรีสตาร์ท)
- Catalog `preview-data.js` ต้องอยู่ใต้ `/app/data` ด้วย (ไม่ใช่แค่ `hub/`) — ไม่งั้นรีสตาร์ทแล้ว UI โหลดไฟล์เก่าจาก image
- **ไม่ดึงชีททับทรัพย์** ตอนบูต/ปกติ — Google Sheet เป็น export อย่างเดียว
- หลังบันทึกบน Hub ระบบ auto-push ขึ้นชีท (~2 วินาที) + ถ้าค้างเกิน ~10 นาทีจะ flush อีกครั้ง และตอนปิดเครื่อง/deploy จะ flush คิวที่ค้าง
- ปุ่ม「ส่งขึ้นชีท」= ส่งสำเนาจากเว็บขึ้นชีท (ไม่ทับเว็บ) — **ไม่มีปุ่มดึงชีททับทรัพย์**
- คิว「รอโพสต์」· Focus · ลูกค้า ยังซิงค์ชีทแยกได้ตามเดิม
- scale = **1** เสมอ
- **Co-Agent (`/co/`, `/api/co/catalog`, `/api/co/match`) อ่านจาก Hub volume เท่านั้น** (เหมือนหน้า Hub เป๊ะ) — ไม่แตะ Google Sheet เลย ดังนั้นบันทึก/แก้ทรัพย์บน Hub แล้วสต็อก Co-Agent อัปเดตตามทันที (cache invalidate ใน `persist()` เมื่อบันทึก) ทั้งสอง response มี `"sot": "hub_volume"` ให้เช็คได้


```bash
fly volumes create hub_data --region sin --size 3 -a property-hub -y   # ครั้งแรก
fly deploy -a property-hub --ha=false
fly scale count 1 -a property-hub -y
```

## LINE Rich Menu (ไม่ต้องเปิด Mac)

Webhook อยู่บน Hub: `https://hub.realxtateth.com/line/webhook`  
ตอบเฉพาะคำทริกเกอร์จากเมนู (ไม่มี OpenAI / Ops)

```bash
chmod +x scripts/cutover_line_to_fly.sh
./scripts/cutover_line_to_fly.sh
```

ตั้ง Response mode = **Bot** ที่ manager.line.biz → Response settings  
(ถ้ายังเป็น Chat ระบบใช้ push fallback)

ตรวจ: `curl -s https://hub.realxtateth.com/line/health`