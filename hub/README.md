# Property Hub (Phase 1)

เว็บแอปจัดการทรัพย์ — แทนที่ Google Sheet (Phase 1 = หน้าตารางเปล่า + login)

## เริ่มใช้งาน

```bash
cd hub
npm install
npm run dev
```

เปิด [http://localhost:3000](http://localhost:3000)

## บัญชีทดสอบ (5 ชุด)

| ผู้ใช้ | รหัสผ่าน | ชื่อแสดง |
|--------|----------|----------|
| angkarn1996 | angkarn2539 | เจ้าของ |
| ptp2 | ptp2026b | แอดมิน 1 |
| ptp3 | ptp2026c | แอดมิน 2 |
| ptp4 | ptp2026d | ทีม 4 |
| ptp5 | ptp2026e | ทีม 5 |

> เปลี่ยนรหัสใน `lib/users.ts` ก่อน deploy จริง

## Phase 1 มีอะไรบ้าง

- Login 5 บัญชี
- ตารางทรัพย์ (ว่าง) — คอลัมน์ตาม spec
- แท็บ: ทั้งหมด / ว่าง / Focus / รอโพสต์ / โคเอเจนต์
- Legend Reminder (11 เดือน, เตือนล่วงหน้า 30 วัน, ในแอป)
- รองรับมือถือ (เลื่อนตารางแนวนอน)
- ปุ่ม/ค้นหา AI — disabled รอ Phase ถัดไป

## Phase ถัดไป

- วางลิงก์ FB / Living → scrape + วิเคราะห์
- Import จาก Google Sheet
- Generate ข้อความ TH/EN
- Reminder จริง + โมดูลผู้เช่า
