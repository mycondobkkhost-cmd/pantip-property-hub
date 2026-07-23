# Deploy Property Hub บน Render (แผนฟรี)

ให้แอดมิน 2 คนใช้จากมือถือได้โดยไม่ต้องเปิดคอม  
แผนฟรีจะ **หลับ** ถ้าไม่มีคนเข้า ~15 นาที — เปิดครั้งแรกหลังว่างอาจรอนาน 30–60 วินาที

## สิ่งที่เตรียมไว้ในโปรเจกต์แล้ว

- `Dockerfile`
- `requirements-hub.txt`
- `render.yaml`
- เซิร์ฟเวอร์ฟัง `0.0.0.0` + `PORT` (สำหรับคลาวด์)

## ขั้นตอน (ครั้งเดียว)

### 1) สร้าง GitHub repo แล้ว push

บนเครื่อง (ในโฟลเดอร์โปรเจกต์):

```bash
cd /Users/angkarn1996/Projects/pantip-property-automation
git add -A
git status   # ต้องเห็น data/properties.json, data/projects.json, hub/preview-data.js
git commit -m "Deploy Property Hub to Render free"
```

สร้าง repo บน GitHub แล้ว:

```bash
gh repo create pantip-property-hub --private --source=. --remote=origin --push
```

หรือสร้าง repo มือแล้ว `git remote add origin ...` + `git push -u origin main`

### 2) สร้าง Web Service บน Render

1. เปิด https://dashboard.render.com แล้ว Sign up (ใช้ GitHub ได้)
2. **New** → **Web Service** → เลือก repo นี้
3. ตั้งค่า:
   - **Runtime:** Docker
   - **Instance type:** Free
   - **Health Check Path:** `/api/health`
4. (จำเป็นบน production) Environment → เพิ่ม:

- `HUB_USERS_JSON` — JSON บัญชีเข้าสู่ระบบ (รหัสผ่านตรวจฝั่งเซิร์ฟเวอร์เท่านั้น ไม่ฝังใน HTML) เช่น:

```json
{"angkarn1996":{"password":"รหัสใหม่ที่แข็งแรง","name":"เจ้าของ"},"ptp2":{"password":"รหัสแอดมิน","name":"แอดมิน 1"}}
```

- `HUB_SESSION_SECRET` — สตริงสุ่มยาวสำหรับเซ็น cookie session (ถ้าไม่ตั้ง ใช้ค่า default ชั่วคราว)

#### สำหรับปุ่ม「ซิงค์ไปชีท Hub」(จำเป็นถ้าต้องการเขียน Google Sheet)

- `HUB_GOOGLE_SHEETS_ID` (หรือ `GOOGLE_SHEETS_ID`) — ID ชีททดลอง เช่น `14U1y4dsebeuudTSK_...`
- `GOOGLE_SERVICE_ACCOUNT_JSON` — JSON ทั้งก้อนของ Service Account (บรรทัดเดียวใน Render env)
- แชร์ชีททดลองให้ email ของ SA เป็น **Editor**
- (แนะนำ) `HUB_OVERVIEW_SHEET_NAME=ทรัพย์รวม` — แท็บที่แอดมินเปิดดู (ห้ามตั้งเป็น Focus)
- (ทางเลือก) `HUB_SHEET_NAME=ทรัพย์ Hub` + `HUB_SHEET_GID` สำหรับแท็บ RXT รอง

ถ้าไม่มี credentials ปุ่มซิงค์จะขึ้น error ชัดเจน + เสนอ**ดาวน์โหลด `hub_overview_export.csv`** ให้วางในชีทเองชั่วคราว  
ดาวน์โหลดตรง: `GET /api/properties/overview-export.csv`

##### เช็คลิสต์สร้าง Service Account (ครั้งเดียว)

1. เปิด [Google Cloud Console](https://console.cloud.google.com) → สร้าง/เลือกโปรเจกต์
2. **APIs & Services → Enable APIs** → เปิด **Google Sheets API** และ **Google Drive API**
3. **IAM & Admin → Service Accounts → Create** → สร้างคีย์ประเภท **JSON** แล้วดาวน์โหลดไฟล์
4. เปิดไฟล์ JSON → คัดลอก**ทั้งก้อน** → Render → service `property-hub` → **Environment** → เพิ่ม  
   `GOOGLE_SERVICE_ACCOUNT_JSON` = วาง JSON ทั้งก้อน (บรรทัดเดียวได้)
5. ในไฟล์ JSON หาฟิลด์ `client_email` (ลงท้าย `@....iam.gserviceaccount.com`)  
   → เปิดชีทเป้าหมาย → **Share** → ใส่ email นั้นเป็น **Editor**
6. Save env (Render จะ restart) → กลับมาแอป → กด「ซิงค์ไปชีท Hub」อีกครั้ง ต้องได้ `pushed: true`

อย่า commit ไฟล์ JSON เข้า git — ใช้แค่ Render env (หรือ `credentials/service_account.json` บนเครื่อง local ที่อยู่ใน `.gitignore`)

รหัสผ่าน preset เดิมใน client ถูกลบแล้ว — ถ้าไม่ตั้ง `HUB_USERS_JSON` บน Render จะล็อกอินไม่ได้

5. Create Web Service แล้วรอ build (~5–10 นาที)

### 3) ได้ลิงก์ใช้งาน

Render จะให้ URL แบบ:

`https://property-hub-xxxx.onrender.com`

ส่งให้แอดมินทั้ง 2 คน เปิดจากมือถือได้เลย

### 4) (แนะนำ) ลดการหลับ — ping ฟรี

1. สมัคร https://cron-job.org (ฟรี)
2. สร้างจ็อบเรียก `https://YOUR-APP.onrender.com/api/health` ทุก **10 นาที**
3. ช่วยให้เครื่องตื่นบ่อยขึ้น (ยังอยู่ในโควต้าฟรีของ Render โดยประมาณ)

## ข้อควรรู้แผนฟรี

| เรื่อง | รายละเอียด |
|--------|------------|
| หลับ | ไม่มีคนใช้สักพัก → เปิดครั้งถัดไปรอนานหน่อย |
| Disk ชั่วคราว | ไฟล์ที่เขียนตอนรัน (`properties.json`, `preview-data.js`, Focus, คิวรอโพสต์) **หายเมื่อ redeploy** — แผนฟรีไม่มี Persistent Disk |
| ดึงชีทตอนบูต | ถ้าตั้ง `MAIN_SHEET_CSV_URL` (หรือ `SOURCE_GOOGLE_SHEETS_ID`) เซิร์ฟจะ **รีเฟรชจาก Google Sheet อัตโนมัติตอนสตาร์ท** หลังทุก deploy — ไม่ต้องกด「รีเฟรชชีท」เอง |
| Focus / คิว | ปักหมุด Focus และแก้คิวบนเซิร์ฟยัง ephemeral (ยังไม่ดึงกลับจากชีทตอนบูต) — ข้อมูลสำคัญให้ซิงค์ไปชีทหรือบันทึกใน Sheet เป็นหลัก |
| ความปลอดภัย | เปลี่ยนรหัสผ่านก่อนแชร์ URL สาธารณะ |

### Env สำหรับดึงชีทเข้าแอป (แนะนำบน Render)

- `MAIN_SHEET_CSV_URL` — ลิงก์ export CSV ของชีทหลัก (Anyone with the link can view)
- หรือ `SOURCE_GOOGLE_SHEETS_ID` + `MAIN_SHEET_GID`
- `WAIT_POST_SHEET_CSV_URL` — แท็บ「รอโพสต์」(optional)
- `HUB_STARTUP_SHEET_SYNC=0` — ปิด sync ตอนบูต (ค่าเริ่มต้นเปิด)

## ทดสอบบนเครื่องก่อน push

```bash
docker build -t property-hub .
docker run --rm -p 8765:8765 property-hub
# เปิด http://127.0.0.1:8765/
```
