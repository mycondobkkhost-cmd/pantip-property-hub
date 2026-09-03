# Phase Y — Pilot Project Selection

โครงการ Pilot 8 รายการ (ไม่ใช่ 10 แรกของคิว) เพื่อทดสอบ UI และการตัดสินใจก่อนตรวจครบ 153 รายการ

| # | โครงการ | project_id | เหตุผลที่เลือก |
|---|---------|------------|----------------|
| 1 | Life Asoke Rama 9 | `ec5214c9-c9fb-5ca5-98fb-852703044e4a` | ความมั่นใจสูง + ข้อมูลทำเลขัดแย้ง + มีห้องเยอะ + มีทำเลตลาด 3 บทบาท (PRIMARY/SECONDARY/EDGE) + legacy promotion |
| 2 | Life Asoke | `9782b822-d4db-5285-b5a7-87c89eec49a6` | โครงการใกล้เคียง Rama 9 แต่คนละโครงการ — ทดสอบการแยกตัวตน |
| 3 | THE BASE Phetchaburi-Thonglor | `03f2d9d3-b0b4-5fad-86ef-f9de7939cee2` | ความมั่นใจระดับกลาง + ข้อมูลทำเลขัดแย้ง |
| 4 | Aspire Sukhumvit 48 | `5e06d489-a116-5f78-87a4-1c3813aac70b` | มีทั้งเขตการปกครอง (วัฒนา) และทำเลตลาด — ทดสอบมิติแยกกัน |
| 5 | Life Asoke Hype | `8d70d6c6-ef51-549c-8822-507c77ab8d70` | หลายทำเลตลาดพร้อมความมั่นใจต่างกัน |
| 6 | ATMOZ BANGNA | `f2fad7e4-abc9-5b62-ae23-f2d8bb42b86f` | Pantip-only — ยังไม่มีใน Canonical Master |
| 7 | The Diplomat Sathorn | `cc3f0b19-843e-5479-a28d-bf2feb5c7ff9` | Pantip-only — ทดสอบข้อความที่ไม่ชวนรวมโครงการ |
| 8 | Townhouse Ekamai 22 - Pridi | `0944c1d9-ce53-5938-aa0d-de7f3ccb7a68` | Pantip-only ที่มีชื่อระบุทำเล |

## กรณีที่ไม่ได้อยู่ในคิว 153 แต่ควรรู้

โครงการที่มีหลักฐานไม่พอ (เช่น `REALXTATE_LOW` หรือไม่ใช่ `DIRECT_CONFLICT`) จะ **ไม่** อยู่ในคิวตรวจสอบ — นี่เป็นการออกแบบเพื่อไม่ให้เจ้าของเสียเวลากับรายการที่ระบบยังไม่มั่นใจ
