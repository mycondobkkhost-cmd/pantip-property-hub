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
| `HUB_USERS_JSON` | บัญชีล็อกอิน |
| `HUB_SESSION_SECRET` | cookie session |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | เขียนชีท |
| `HUB_GOOGLE_SHEETS_ID` / `GOOGLE_SHEETS_ID` | ชีททดลอง |
| `SOURCE_GOOGLE_SHEETS_ID` / `MAIN_SHEET_CSV_URL` | ดึงเข้าแอป |
| `WAIT_POST_SHEET_CSV_URL` | แท็บรอโพสต์ |
| `HUB_STARTUP_SHEET_SYNC=1` | ซิงค์ตอนบูต |
| `HUB_AUTO_SYNC_TO_SHEET=1` | auto push หลังแก้ทรัพย์ |

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
