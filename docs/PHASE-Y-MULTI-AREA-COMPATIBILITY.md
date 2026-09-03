# Phase Y — Multi-Area & Umbrella Compatibility

## สรุป

Phase Y ขยายโมเดล `proposed_value` ให้เก็บ `marketplace_area_relations[]` แทนการยุบเป็นสตริงเดียว

## โครงสร้างที่แนะนำ (canonical review/export)

```json
{
  "marketplace_area_relations": [
    {"area_id": "rxa_...", "area_name": "ทองหล่อ", "role": "PRIMARY", "confidence": "HIGH"},
    {"area_id": "rxa_...", "area_name": "พระโขนง", "role": "SECONDARY", "confidence": "MEDIUM"},
    {"area_id": "rxa_...", "area_name": "เอกมัย", "role": "EDGE", "confidence": "LOW"}
  ]
}
```

- สูงสุด **3** ทำเลตลาดต่อโครงการ (สอดคล้องนโยบาย RealXtate)
- บทบาท: `PRIMARY`, `SECONDARY`, `EDGE`
- แยกจาก `zone_dimensions[]` ของ Pantip (เขต/สถานี/ทำเลเดิม)

## Umbrella groups (อนาคต)

กลุ่มตลาดใหญ่ เช่น **พร้อมพงษ์–ทองหล่อ–เอกมัย** ควรเป็นเลเยอร์ presentation แยก:

```json
{
  "marketplace_area_relations": [...],
  "umbrella_groups": [
    {"group_id": "umb_phrom_thong_ekk", "label_th": "พร้อมพงษ์–ทองหล่อ–เอกมัย", "member_area_ids": ["..."]}
  ]
}
```

Phase Y **ไม่** สร้าง umbrella system แต่ export ไม่บล็อก — ไม่เก็บแค่ `zone = "ทองหล่อ"` แบบแบน

## สิ่งที่ห้ามปน

| มิติ | ตัวอย่าง | ห้ามเทียบกับ |
|------|----------|-------------|
| เขต/แขวง | วัฒนา | ทำเลตลาด |
| สถานี | BTS ทองหล่อ | ทำเลตลาด |
| ทำเลตลาด | ทองหล่อ (PRIMARY) | เขตปกครอง |
