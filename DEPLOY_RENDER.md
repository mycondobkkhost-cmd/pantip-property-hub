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
4. (แนะนำ) Environment → เพิ่ม `HUB_USERS_JSON` เป็น JSON รหัสผ่านของคุณเอง เช่น:

```json
{"angkarn1996":{"password":"รหัสใหม่","name":"เจ้าของ"},"ptp2":{"password":"รหัสแอดมิน","name":"แอดมิน 1"}}
```

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
| ข้อมูลใหม่ | บันทึกบนเซิร์ฟเวอร์ได้ตอนเครื่องตื่น — ถ้า **redeploy** อาจกลับไปชุดใน Git (ควร push ข้อมูลสำคัญขึ้น repo เป็นระยะ หรืออัปเกรด Disk ทีหลัง) |
| ความปลอดภัย | เปลี่ยนรหัสผ่านก่อนแชร์ URL สาธารณะ |

## ทดสอบบนเครื่องก่อน push

```bash
docker build -t property-hub .
docker run --rm -p 8765:8765 property-hub
# เปิด http://127.0.0.1:8765/
```
