/**
 * Property Hub → Google Sheet sync (optional, one-time setup)
 *
 * วิธีใช้ (ครั้งเดียว):
 * 1. เปิดชีททดลอง → Extensions → Apps Script
 * 2. วางโค้ดนี้ทั้งไฟล์ → Save
 * 3. Deploy → New deployment → Type: Web app
 *    - Execute as: Me
 *    - Who has access: Anyone (หรือ Anyone with Google account)
 * 4. คัดลอก Web App URL ไปใส่ใน .env / Render env:
 *    HUB_SHEET_WEBAPP_URL=https://script.google.com/macros/s/XXXX/exec
 * 5. ในชีท: คลิกขวาแท็บ Sale (ว่าง) → Rename เป็น「ทรัพย์ Hub」
 *    หรือสคริปต์จะสร้างแท็บให้อัตโนมัติ
 *
 * หมายเหตุ: ทุกครั้งที่แอปซิงค์ จะเขียน「ทำเล」+「สถานีรถไฟฟ้า」ใหม่จาก master โครงการในแอป
 * (ไม่เก็บค่าเก่าบนชีท) — ต้อง Redeploy web app ถ้าอัปเดต HUB_HEADERS
 */

var HUB_SHEET_NAME = 'ทรัพย์ Hub';
var HUB_HEADERS = [
  'รหัสทรัพย์', 'วันที่รับเข้า', 'วันที่ว่าง', 'โครงการ', 'ประเภท',
  'ห้องนอน/ห้องน้ำ', 'ขนาด', 'ชั้น', 'ราคาเช่า', 'ราคาขาย',
  'ทำเล', 'สถานีรถไฟฟ้า',
  'Short-Term', 'PETS', 'ลิ้งค์โพส', 'ลิ้งค์โพส Pages ', 'หมายเหตุ',
  'ลิ้งค์ต้นโพสต์', 'เฟสเจ้าของ', 'แหล่ง', 'รหัสคู่/อ้างอิง', 'synced_at', 'app_id'
];

function doPost(e) {
  try {
    var body = {};
    if (e && e.postData && e.postData.contents) {
      body = JSON.parse(e.postData.contents);
    }
    var rows = body.rows || [];
    // Prefer headers from the app payload so column order stays in sync
    var headers = (body.headers && body.headers.length) ? body.headers : HUB_HEADERS;
    var ss = SpreadsheetApp.getActiveSpreadsheet();
    var ws = ss.getSheetByName(HUB_SHEET_NAME);
    if (!ws) {
      // Prefer renaming empty "Sale" tab if present
      var sale = ss.getSheetByName('Sale');
      if (sale) {
        sale.setName(HUB_SHEET_NAME);
        ws = sale;
      } else {
        ws = ss.insertSheet(HUB_SHEET_NAME);
      }
    }
    ws.clear();
    var values = [headers].concat(rows);
    if (values.length === 1) {
      ws.getRange(1, 1, 1, headers.length).setValues([headers]);
    } else {
      ws.getRange(1, 1, values.length, headers.length).setValues(values);
    }
    return ContentService
      .createTextOutput(JSON.stringify({
        ok: true,
        rows: rows.length,
        sheet: HUB_SHEET_NAME,
        cols: headers.length
      }))
      .setMimeType(ContentService.MimeType.JSON);
  } catch (err) {
    return ContentService
      .createTextOutput(JSON.stringify({ ok: false, error: String(err) }))
      .setMimeType(ContentService.MimeType.JSON);
  }
}

function doGet() {
  return ContentService
    .createTextOutput(JSON.stringify({ ok: true, service: 'property-hub-sheet-sync' }))
    .setMimeType(ContentService.MimeType.JSON);
}
