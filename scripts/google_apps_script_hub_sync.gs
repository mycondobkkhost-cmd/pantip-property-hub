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
 *
 * Payload จากแอป (ใหม่):
 *   { mode: "overview", rows, headers, hub_rows, hub_headers,
 *     overview_sheet, hub_sheet, synced_at }
 * เขียนแท็บ「ทรัพย์รวม」เรียงใหม่→เก่า +「ทรัพย์ Hub」สำหรับ RXT
 * ห้ามเขียน Focus
 */

var HUB_SHEET_NAME = 'ทรัพย์ Hub';
var OVERVIEW_SHEET_NAME = 'ทรัพย์รวม';
var FORBIDDEN = { 'Focus': true, 'Focus🚨': true, '_proj_loc': true };

var HUB_HEADERS = [
  'รหัสทรัพย์', 'วันที่รับเข้า', 'วันที่ว่าง', 'โครงการ', 'ประเภท',
  'ห้องนอน/ห้องน้ำ', 'ขนาด', 'ชั้น', 'ราคาเช่า', 'ราคาขาย',
  'ทำเล', 'สถานีรถไฟฟ้า',
  'Short-Term', 'PETS', 'ลิ้งค์โพส', 'ลิ้งค์โพส Pages ', 'หมายเหตุ',
  'ลิ้งค์ต้นโพสต์', 'เฟสเจ้าของ', 'แหล่ง', 'รหัสคู่/อ้างอิง', 'synced_at', 'app_id'
];

var OVERVIEW_HEADERS = [
  'รหัส', 'ที่มา', 'วันที่', 'โครงการ', 'ประเภท', 'ห้อง',
  'ตรม.', 'ชั้น', 'เช่า', 'ขาย', 'ทำเล', 'สถานี',
  'ต้นทาง', 'เจ้าของ', 'ที่โพสต์', 'เพจ'
];

function _forbidden_(name) {
  var n = String(name || '').trim();
  if (FORBIDDEN[n]) return true;
  return n.toLowerCase().indexOf('focus') === 0;
}

function _sheetByName_(ss, name, createIfMissing, cols) {
  if (_forbidden_(name)) throw new Error('ห้ามเขียนแท็บ ' + name);
  var ws = ss.getSheetByName(name);
  if (!ws && createIfMissing) {
    var sale = ss.getSheetByName('Sale');
    if (sale && !_forbidden_(sale.getName())) {
      sale.setName(name);
      ws = sale;
    } else {
      ws = ss.insertSheet(name);
    }
  }
  if (ws && _forbidden_(ws.getName())) throw new Error('ห้ามเขียนแท็บ ' + ws.getName());
  return ws;
}

function _writeTable_(ws, headers, rows) {
  ws.clear();
  var values = [headers].concat(rows || []);
  if (values.length === 1) {
    ws.getRange(1, 1, 1, headers.length).setValues([headers]);
  } else {
    ws.getRange(1, 1, values.length, headers.length).setValues(values);
  }
  return rows ? rows.length : 0;
}

function doPost(e) {
  try {
    var body = {};
    if (e && e.postData && e.postData.contents) {
      body = JSON.parse(e.postData.contents);
    }
    var ss = SpreadsheetApp.getActiveSpreadsheet();
    var mode = String(body.mode || '').toLowerCase();

    // New overview mode from Property Hub server
    if (mode === 'overview' || (body.rows && body.headers && body.headers[0] === 'รหัส')) {
      var ovName = body.overview_sheet || OVERVIEW_SHEET_NAME;
      var hubName = body.hub_sheet || HUB_SHEET_NAME;
      var ovHeaders = (body.headers && body.headers.length) ? body.headers : OVERVIEW_HEADERS;
      var ovRows = body.rows || [];
      var ov = _sheetByName_(ss, ovName, true, ovHeaders.length);
      var nOv = _writeTable_(ov, ovHeaders, ovRows);

      var nHub = 0;
      var hubTitle = '';
      try {
        var hubHeaders = (body.hub_headers && body.hub_headers.length) ? body.hub_headers : HUB_HEADERS;
        var hubRows = body.hub_rows || [];
        var hub = _sheetByName_(ss, hubName, true, hubHeaders.length);
        nHub = _writeTable_(hub, hubHeaders, hubRows);
        hubTitle = hub.getName();
      } catch (hubErr) {
        // overview success still counts
      }

      return ContentService
        .createTextOutput(JSON.stringify({
          ok: true,
          mode: 'overview',
          sheet: ov.getName(),
          overview_sheet: ov.getName(),
          rows: nOv,
          overview_rows: nOv,
          hub_sheet: hubTitle,
          hub_rows: nHub,
          synced_at: body.synced_at || ''
        }))
        .setMimeType(ContentService.MimeType.JSON);
    }

    // Legacy: Hub-owned rows only →「ทรัพย์ Hub」
    var rows = body.rows || [];
    var headers = (body.headers && body.headers.length) ? body.headers : HUB_HEADERS;
    var ws = _sheetByName_(ss, HUB_SHEET_NAME, true, headers.length);
    var n = _writeTable_(ws, headers, rows);
    return ContentService
      .createTextOutput(JSON.stringify({
        ok: true,
        rows: n,
        sheet: ws.getName(),
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
