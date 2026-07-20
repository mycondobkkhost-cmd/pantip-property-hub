/**
 * Property Hub — หน้า「ทรัพย์รวม · แอป」
 * รวม PTP (ชีทหลัก) + RXT (ทรัพย์ Hub) · เรียงใหม่→เก่า · ค้นหา 2 ช่อง · ล็อกแก้
 *
 * สี: เขียว Property Hub (#188038) / slate — ไม่ใช้ม่วง
 * C2 = ค้นหาทั่วไป (รหัส + โครงการ) · C3 = ค้นหาทำเล/BTS
 * ทั้งคู่ว่าง = ทั้งหมด · กรอกทั้งคู่ = AND
 *
 * ติดตั้ง (ครั้งเดียว):
 * 1. เปิดชีททดลอง → Extensions → Apps Script
 * 2. วางไฟล์นี้ → Save
 * 3. รัน setupAppDashboard ครั้งแรก (Allow permissions)
 * 4. ช่องเหลือง C2 / C3 เท่านั้นที่แก้ได้
 */

var APP_DASH_NAME = 'ทรัพย์รวม · แอป';
var APP_SEARCH_CELL = 'C2';
var APP_LOC_SEARCH_CELL = 'C3';
var APP_HEADER_ROW = 5;
var APP_DATA_START = 6;

var MAIN_SHEET_CANDIDATES = ['ชีทสำหรับทำงาน', 'ชีตสำหรับทำงาน', 'ชีทหลัก'];
var HUB_SHEET_NAME = 'ทรัพย์ Hub';
var PROJ_LOC_SHEET = '_proj_loc';

var CLR_TITLE_BG = '#e6f4ea';
var CLR_TITLE_FG = '#137333';
var CLR_HEADER_BG = '#188038';
var CLR_HEADER_FG = '#ffffff';
var CLR_SEARCH_BG = '#fff9c4';
var CLR_SEARCH_BORDER = '#f9ab00';
var CLR_HINT = '#5f6368';
var CLR_MUTED = '#80868b';
var CLR_ZEBRA = '#f4f7f5';
var CLR_HUB_BG = '#e8f0fe';
var CLR_HUB_FG = '#1967d2';
var CLR_SHEET_BG = '#e6f4ea';
var CLR_SHEET_FG = '#137333';

var APP_HEADERS = [
  'รหัส', 'ที่มา', 'วันที่', 'โครงการ', 'ประเภท', 'ห้อง',
  'ตรม.', 'ชั้น', 'เช่า', 'ขาย', 'ทำเล', 'สถานี',
  'ต้นทาง', 'เจ้าของ', 'ที่โพสต์', 'เพจ'
];

function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('Property Hub')
    .addItem('สร้าง/จัดหน้า ทรัพย์รวม · แอป', 'setupAppDashboard')
    .addItem('รีเฟรชหน้าทรัพย์รวม', 'refreshAppDashboard')
    .addToUi();
}

function setupAppDashboard() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var sh = ss.getSheetByName(APP_DASH_NAME);
  if (!sh) {
    sh = ss.insertSheet(APP_DASH_NAME);
  }
  sh.clear();
  sh.clearNotes();
  sh.setHiddenGridlines(true);
  sh.setFrozenRows(APP_HEADER_ROW);

  var cols = APP_HEADERS.length;

  sh.getRange(1, 1, 1, cols).merge();
  sh.getRange('A1')
    .setValue('Property Hub · ทรัพย์รวม (PTP + RXT) — เรียงใหม่→เก่า · อ่านอย่างเดียว')
    .setFontWeight('bold')
    .setFontSize(14)
    .setFontColor(CLR_TITLE_FG)
    .setBackground(CLR_TITLE_BG)
    .setVerticalAlignment('middle');
  sh.setRowHeight(1, 38);

  // Row 2 — general search
  sh.getRange('A2').setValue('ค้นหาทั่วไป').setFontWeight('bold').setFontColor('#3c4043')
    .setHorizontalAlignment('center').setVerticalAlignment('middle');
  sh.getRange('B2').setValue('→').setHorizontalAlignment('center').setFontColor(CLR_MUTED);
  sh.getRange(APP_SEARCH_CELL)
    .setValue('')
    .setBackground(CLR_SEARCH_BG)
    .setBorder(true, true, true, true, false, false, CLR_SEARCH_BORDER, SpreadsheetApp.BorderStyle.SOLID_MEDIUM)
    .setFontSize(12)
    .setFontWeight('bold')
    .setNote('รหัส / ชื่อโครงการ เท่านั้น · ว่าง = ไม่กรองช่องนี้');
  sh.getRange(2, 4, 1, cols - 3).merge();
  sh.getRange('D2')
    .setValue('เช่น PTP8088 · Life Asoke · Thru / ทรู (ไม่บังคับ)')
    .setFontColor(CLR_MUTED)
    .setFontStyle('italic')
    .setVerticalAlignment('middle');
  sh.getRange(2, 1, 1, cols).setBackground('#fafcfb');
  sh.getRange(APP_SEARCH_CELL).setBackground(CLR_SEARCH_BG);
  sh.setRowHeight(2, 34);

  // Row 3 — location search
  sh.getRange('A3').setValue('ค้นหาทำเล/BTS').setFontWeight('bold').setFontColor('#3c4043')
    .setHorizontalAlignment('center').setVerticalAlignment('middle');
  sh.getRange('B3').setValue('→').setHorizontalAlignment('center').setFontColor(CLR_MUTED);
  sh.getRange(APP_LOC_SEARCH_CELL)
    .setValue('')
    .setBackground(CLR_SEARCH_BG)
    .setBorder(true, true, true, true, false, false, CLR_SEARCH_BORDER, SpreadsheetApp.BorderStyle.SOLID_MEDIUM)
    .setFontSize(12)
    .setFontWeight('bold')
    .setNote('ทำเล / สถานี BTS·MRT เท่านั้น · ว่าง = ไม่กรองช่องนี้ · กรอกคู่กับ C2 = AND');
  sh.getRange(3, 4, 1, cols - 3).merge();
  sh.getRange('D3')
    .setValue('เช่น ทองหล่อ · อโศก · BTS อ่อนนุช (ไม่บังคับ)')
    .setFontColor(CLR_MUTED)
    .setFontStyle('italic')
    .setVerticalAlignment('middle');
  sh.getRange(3, 1, 1, cols).setBackground('#fafcfb');
  sh.getRange(APP_LOC_SEARCH_CELL).setBackground(CLR_SEARCH_BG);
  sh.setRowHeight(3, 34);

  sh.getRange(4, 1, 1, cols).merge();
  sh.getRange('A4')
    .setValue('ว่างทั้ง C2+C3 = ทั้งหมด · กรอกทั้งคู่ = ต้องตรงทั้งชื่อและทำเล (AND) · อัปเดต: —')
    .setFontSize(10)
    .setFontColor(CLR_MUTED)
    .setBackground('#f8faf9');
  sh.setRowHeight(4, 22);

  var header = sh.getRange(APP_HEADER_ROW, 1, 1, cols);
  header.setValues([APP_HEADERS]);
  header
    .setBackground(CLR_HEADER_BG)
    .setFontColor(CLR_HEADER_FG)
    .setFontWeight('bold')
    .setHorizontalAlignment('center')
    .setVerticalAlignment('middle')
    .setWrap(true);
  sh.setRowHeight(APP_HEADER_ROW, 30);

  sh.setColumnWidth(1, 96);
  sh.setColumnWidth(2, 56);
  sh.setColumnWidth(3, 92);
  sh.setColumnWidth(4, 220);
  sh.setColumnWidth(5, 72);
  sh.setColumnWidth(6, 110);
  sh.setColumnWidth(7, 64);
  sh.setColumnWidth(8, 52);
  sh.setColumnWidth(9, 88);
  sh.setColumnWidth(10, 100);
  sh.setColumnWidth(11, 120);
  sh.setColumnWidth(12, 180);
  sh.setColumnWidth(13, 68);
  sh.setColumnWidth(14, 68);
  sh.setColumnWidth(15, 68);
  sh.setColumnWidth(16, 68);

  applyColumnAlignments_(sh);
  protectAppDashboard_(sh);
  refreshAppDashboard();
  SpreadsheetApp.getUi().alert(
    'สร้างแท็บ「' + APP_DASH_NAME + '」แล้ว\n' +
    'C2 = ค้นหาทั่วไป (รหัส/โครงการ) · C3 = ค้นหาทำเล/BTS\n' +
    'ว่างทั้งคู่ = แสดงทั้งหมด'
  );
}

function onEdit(e) {
  try {
    if (!e || !e.range) return;
    var sh = e.range.getSheet();
    if (sh.getName() !== APP_DASH_NAME) return;
    var a1 = e.range.getA1Notation();
    if (a1 !== APP_SEARCH_CELL && a1 !== APP_LOC_SEARCH_CELL) return;
    refreshAppDashboard();
  } catch (err) {
    // ignore
  }
}

function refreshAppDashboard() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var sh = ss.getSheetByName(APP_DASH_NAME);
  if (!sh) {
    setupAppDashboard();
    return;
  }

  var cols = APP_HEADERS.length;
  var qGen = String(sh.getRange(APP_SEARCH_CELL).getDisplayValue() || '').trim().toLowerCase();
  var qLoc = String(sh.getRange(APP_LOC_SEARCH_CELL).getDisplayValue() || '').trim().toLowerCase();
  var main = findSheet_(ss, MAIN_SHEET_CANDIDATES);
  var hub = ss.getSheetByName(HUB_SHEET_NAME);
  var projMap = loadProjectLocMap_(ss);

  var rows = [];
  if (main) rows = rows.concat(readSourceRows_(main, 'ชีท', projMap));
  if (hub) rows = rows.concat(readSourceRows_(hub, 'Hub', projMap));

  if (qGen) {
    var thruQ = /thru|ทรู/.test(qGen);
    rows = rows.filter(function (r) {
      if (r.searchGen.indexOf(qGen) >= 0) return true;
      if (thruQ && /thru|ทรู/.test(r.searchGen)) return true;
      return false;
    });
  }
  if (qLoc) {
    rows = rows.filter(function (r) {
      return r.searchLoc.indexOf(qLoc) >= 0;
    });
  }

  rows.sort(function (a, b) {
    return (b.sortTs || 0) - (a.sortTs || 0);
  });

  var lastRow = Math.max(sh.getLastRow(), APP_DATA_START);
  if (lastRow >= APP_DATA_START) {
    sh.getRange(APP_DATA_START, 1, lastRow - APP_DATA_START + 1, cols).clearContent();
    sh.getRange(APP_DATA_START, 1, lastRow - APP_DATA_START + 1, cols).clearFormat();
  }

  var out = rows.map(function (r) {
    return [
      r.code, r.source, r.dateIn, r.project, r.propType, r.beds,
      formatSizeDisplay_(r.size), r.floor,
      toSheetNumber_(r.rent, false), toSheetNumber_(r.sale, false),
      r.zone, r.transit,
      linkCellDisplay_(r.sourceLink), linkCellDisplay_(r.ownerLink),
      linkCellDisplay_(r.postLink), linkCellDisplay_(r.pageLink)
    ];
  });

  ensureAppDashboardChrome_(sh, cols);
  var filterNote = '';
  if (qGen && qLoc) filterNote = ' · ค้นหา「' + qGen + '」+ ทำเล「' + qLoc + '」';
  else if (qGen) filterNote = ' · ค้นหา「' + qGen + '」';
  else if (qLoc) filterNote = ' · ทำเล「' + qLoc + '」';
  else filterNote = ' · ทั้งหมด';

  sh.getRange('A4').setValue(
    'ว่างทั้ง C2+C3 = ทั้งหมด · กรอกทั้งคู่ = AND · อัปเดต: ' +
    Utilities.formatDate(new Date(), Session.getScriptTimeZone(), 'dd/MM/yyyy HH:mm') +
    ' · แสดง ' + out.length.toLocaleString('th-TH') + ' รายการ' + filterNote
  );

  if (!out.length) {
    sh.getRange(APP_DATA_START, 1).setValue((qGen || qLoc) ? 'ไม่พบรายการที่ตรงคำค้น' : 'ยังไม่มีข้อมูล');
    sh.getRange(APP_DATA_START, 1).setFontColor('#c5221f');
    protectAppDashboard_(sh);
    return;
  }

  var MAX = 20000;
  var truncated = out.length > MAX;
  if (truncated) out = out.slice(0, MAX);

  var dataRange = sh.getRange(APP_DATA_START, 1, out.length, cols);
  dataRange.setValues(out);
  dataRange.setFontSize(10).setVerticalAlignment('middle');

  var backgrounds = [];
  var fontColors = [];
  var fontWeights = [];
  for (var i = 0; i < out.length; i++) {
    var bgRow = [];
    var fgRow = [];
    var wtRow = [];
    var base = (i % 2 === 0) ? '#ffffff' : CLR_ZEBRA;
    var src = String(out[i][1] || '');
    var isHub = src === 'Hub';
    for (var c = 0; c < cols; c++) {
      var bg = base;
      var fg = '#202124';
      var wt = 'normal';
      if (c === 0) {
        fg = isHub ? CLR_HUB_FG : CLR_SHEET_FG;
        wt = 'bold';
      }
      if (c === 1) {
        bg = isHub ? CLR_HUB_BG : CLR_SHEET_BG;
        fg = isHub ? CLR_HUB_FG : CLR_SHEET_FG;
        wt = 'bold';
      }
      bgRow.push(bg);
      fgRow.push(fg);
      wtRow.push(wt);
    }
    backgrounds.push(bgRow);
    fontColors.push(fgRow);
    fontWeights.push(wtRow);
  }
  dataRange.setBackgrounds(backgrounds);
  dataRange.setFontColors(fontColors);
  dataRange.setFontWeights(fontWeights);

  applyColumnAlignments_(sh, out.length);
  applyNumberFormats_(sh, out.length);
  sh.getRange(APP_DATA_START, 4, out.length, 1).setWrap(true);
  sh.getRange(APP_DATA_START, 10, out.length, 3).setWrap(true);
  sh.getRange(APP_DATA_START, 13, out.length, 4).setWrap(false);

  if (truncated) {
    sh.getRange(APP_DATA_START + out.length, 1)
      .setValue('… แสดงสูงสุด ' + MAX + ' แถว — ใส่คำค้นที่ C2/C3 เพื่อแคบผล')
      .setFontColor('#b06000');
  }

  protectAppDashboard_(sh);
}

function applyColumnAlignments_(sh, dataRows) {
  var n = dataRows || Math.max(0, sh.getLastRow() - APP_HEADER_ROW);
  if (n < 1) return;
  var end = APP_DATA_START + n - 1;
  sh.getRange(APP_DATA_START, 1, end, 3).setHorizontalAlignment('center');
  sh.getRange(APP_DATA_START, 5, end, 1).setHorizontalAlignment('center');
  sh.getRange(APP_DATA_START, 6, end, 9).setHorizontalAlignment('center');
  sh.getRange(APP_DATA_START, 4, end, 4).setHorizontalAlignment('left');
  sh.getRange(APP_DATA_START, 10, end, 12).setHorizontalAlignment('left');
  sh.getRange(APP_DATA_START, 13, end, 16).setHorizontalAlignment('center');
}

function ensureAppDashboardChrome_(sh, cols) {
  cols = cols || APP_HEADERS.length;

  sh.getRange('A1')
    .setValue('Property Hub · ทรัพย์รวม (PTP + RXT) — เรียงใหม่→เก่า · อ่านอย่างเดียว')
    .setFontWeight('bold')
    .setFontSize(14)
    .setFontColor(CLR_TITLE_FG)
    .setBackground(CLR_TITLE_BG)
    .setVerticalAlignment('middle');
  sh.getRange(1, 1, 1, cols).setBackground(CLR_TITLE_BG);

  sh.getRange('A2').setValue('ค้นหาทั่วไป').setFontWeight('bold').setFontColor('#3c4043')
    .setHorizontalAlignment('center').setVerticalAlignment('middle');
  sh.getRange('B2').setValue('→').setHorizontalAlignment('center').setFontColor(CLR_MUTED);
  sh.getRange('D2')
    .setValue('เช่น PTP8088 · Life Asoke · Thru / ทรู (ไม่บังคับ)')
    .setFontColor(CLR_MUTED).setFontStyle('italic').setVerticalAlignment('middle');
  sh.getRange(2, 1, 1, cols).setBackground('#fafcfb');
  sh.getRange(APP_SEARCH_CELL)
    .setBackground(CLR_SEARCH_BG)
    .setBorder(true, true, true, true, false, false, CLR_SEARCH_BORDER, SpreadsheetApp.BorderStyle.SOLID_MEDIUM)
    .setFontSize(12).setFontWeight('bold');

  sh.getRange('A3').setValue('ค้นหาทำเล/BTS').setFontWeight('bold').setFontColor('#3c4043')
    .setHorizontalAlignment('center').setVerticalAlignment('middle');
  sh.getRange('B3').setValue('→').setHorizontalAlignment('center').setFontColor(CLR_MUTED);
  sh.getRange('D3')
    .setValue('เช่น ทองหล่อ · อโศก · BTS อ่อนนุช (ไม่บังคับ)')
    .setFontColor(CLR_MUTED).setFontStyle('italic').setVerticalAlignment('middle');
  sh.getRange(3, 1, 1, cols).setBackground('#fafcfb');
  sh.getRange(APP_LOC_SEARCH_CELL)
    .setBackground(CLR_SEARCH_BG)
    .setBorder(true, true, true, true, false, false, CLR_SEARCH_BORDER, SpreadsheetApp.BorderStyle.SOLID_MEDIUM)
    .setFontSize(12).setFontWeight('bold');

  sh.getRange(4, 1, 1, cols).setBackground('#f8faf9');

  var header = sh.getRange(APP_HEADER_ROW, 1, 1, cols);
  header.setValues([APP_HEADERS]);
  header
    .setBackground(CLR_HEADER_BG)
    .setFontColor(CLR_HEADER_FG)
    .setFontWeight('bold')
    .setHorizontalAlignment('center')
    .setVerticalAlignment('middle')
    .setWrap(true);

  sh.setColumnWidth(1, 96);
  sh.setColumnWidth(2, 56);
  sh.setColumnWidth(3, 92);
  sh.setColumnWidth(4, 220);
  sh.setColumnWidth(5, 72);
  sh.setColumnWidth(6, 110);
  sh.setColumnWidth(7, 64);
  sh.setColumnWidth(8, 52);
  sh.setColumnWidth(9, 88);
  sh.setColumnWidth(10, 100);
  sh.setColumnWidth(11, 120);
  sh.setColumnWidth(12, 180);
  sh.setColumnWidth(13, 68);
  sh.setColumnWidth(14, 68);
  sh.setColumnWidth(15, 68);
  sh.setColumnWidth(16, 68);
  sh.setFrozenRows(APP_HEADER_ROW);
}

function toSheetNumber_(raw, allowDecimal) {
  var s = String(raw == null ? '' : raw).trim();
  if (!s || s === '-' || s === '—') return '';
  var cleaned = s.replace(/,/g, '');
  if (allowDecimal) cleaned = cleaned.replace(/[^\d.\-]/g, '');
  else cleaned = cleaned.replace(/[^\d\-]/g, '');
  if (!cleaned || cleaned === '-' || cleaned === '.' || cleaned === '-.') return s;
  var n = Number(cleaned);
  return isNaN(n) ? s : n;
}

function cleanLink_(raw) {
  var s = String(raw == null ? '' : raw).trim();
  if (!s || s === '-' || s === '—') return '';
  if (/^https?:\/\//i.test(s)) return s;
  return s;
}

function formatTypeDisplay_(raw) {
  var s = String(raw == null ? '' : raw).trim();
  if (!s || s === '-') return '';
  var low = s.toLowerCase();
  if (low === 'condo') return 'คอนโด';
  if (low === 'house') return 'บ้าน';
  if (/land|ที่ดิ/i.test(s)) return 'ที่ดิน';
  return s;
}

function linkCellDisplay_(url) {
  return cleanLink_(url);
}

/** Integer sqm without trailing dot; decimals keep needed digits. */
function formatSizeDisplay_(raw) {
  var n = toSheetNumber_(raw, true);
  if (n === '' || typeof n !== 'number') return n === '' ? '' : String(raw || '');
  if (Math.round(n) === n) return n;
  return n;
}

function applyNumberFormats_(sh, dataRows) {
  var n = dataRows || Math.max(0, sh.getLastRow() - APP_HEADER_ROW);
  if (n < 1) return;
  var end = APP_DATA_START + n - 1;
  // 0.### drops trailing zeros AND trailing decimal point for integers
  sh.getRange('F' + APP_DATA_START + ':F' + end).setNumberFormat('#,##0.###');
  sh.getRange('H' + APP_DATA_START + ':I' + end).setNumberFormat('#,##0');
}

function findSheet_(ss, names) {
  for (var i = 0; i < names.length; i++) {
    var sh = ss.getSheetByName(names[i]);
    if (sh) return sh;
  }
  var all = ss.getSheets();
  for (var j = 0; j < all.length; j++) {
    var name = all[j].getName();
    if (name === APP_DASH_NAME || name === HUB_SHEET_NAME) continue;
    var h = String(all[j].getRange(1, 1).getDisplayValue() || '');
    if (h.indexOf('รหัสทรัพย์') === 0 || h === 'รหัสทรัพย์') return all[j];
  }
  return null;
}

function loadProjectLocMap_(ss) {
  var map = {};
  var sh = ss.getSheetByName(PROJ_LOC_SHEET);
  if (!sh || sh.getLastRow() < 2) return map;
  var values = sh.getRange(1, 1, sh.getLastRow(), 3).getDisplayValues();
  for (var i = 1; i < values.length; i++) {
    var key = String(values[i][0] || '').trim().toLowerCase();
    if (!key) continue;
    map[key] = {
      zone: String(values[i][1] || '').trim(),
      transit: String(values[i][2] || '').trim()
    };
  }
  return map;
}

function normProjectKey_(name) {
  return String(name || '')
    .toLowerCase()
    .replace(/[()（）]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

function lookupProjectLoc_(projMap, projectName) {
  if (!projMap) return null;
  var key = normProjectKey_(projectName);
  if (projMap[key]) return projMap[key];
  // try without parenthetical alias
  var bare = key.replace(/\s*[-–—].*$/, '').replace(/\s+/g, ' ').trim();
  if (projMap[bare]) return projMap[bare];
  return null;
}

function splitMixedLocation_(raw) {
  var parts = String(raw || '').split(',').map(function (s) {
    return String(s || '').trim();
  }).filter(Boolean);
  var zones = [];
  var transit = [];
  var skipZone = /^(BTS|MRT|ARL|APL|Airport|ทรู|True\s*Digital|กรุงเทพ|กทม|เขต|แขวง|ถนน|ซอย|\d{5})\b/i;
  for (var i = 0; i < parts.length; i++) {
    var p = parts[i];
    if (/^(BTS|MRT|ARL|APL|Airport)\b/i.test(p)) {
      if (transit.length < 3) transit.push(p.replace(/^Airport\s*(Rail\s*)?Link\s*/i, 'ARL '));
    } else if (!skipZone.test(p) && p.length > 1 && p.length <= 28) {
      if (zones.length < 4) zones.push(p);
    }
  }
  return {
    zone: zones.join(', '),
    transit: transit.join(', ')
  };
}

function readSourceRows_(sheet, sourceLabel, projMap) {
  var values = sheet.getDataRange().getDisplayValues();
  if (!values || values.length < 2) return [];
  var header = values[0].map(function (h) { return String(h || '').trim(); });
  var idx = function (name) {
    return header.indexOf(name);
  };
  var cCode = idx('รหัสทรัพย์');
  if (cCode < 0) cCode = 0;
  var cDate = idx('วันที่รับเข้า');
  var cProj = idx('โครงการ');
  var cType = idx('ประเภท');
  var cBeds = idx('ห้องนอน/ห้องน้ำ');
  var cSize = idx('ขนาด');
  var cFloor = idx('ชั้น');
  var cRent = idx('ราคาเช่า');
  var cSale = idx('ราคาขาย');
  var cZone = idx('ทำเล');
  var cTransit = idx('สถานีรถไฟฟ้า');
  var cPost = idx('ลิ้งค์โพส');
  var cPages = idx('ลิ้งค์โพส Pages ');
  if (cPages < 0) cPages = idx('ลิ้งค์โพส Pages');
  var cSource = idx('ลิ้งค์ต้นโพสต์');
  var cOwner = idx('เฟสเจ้าของ');

  var out = [];
  for (var r = 1; r < values.length; r++) {
    var row = values[r];
    var code = String(row[cCode] || '').trim();
    if (!code) continue;
    var project = cProj >= 0 ? String(row[cProj] || '').trim() : '';
    if (sourceLabel === 'ชีท' && !project) continue;

    var dateIn = cDate >= 0 ? String(row[cDate] || '').trim() : '';
    var propType = cType >= 0 ? formatTypeDisplay_(row[cType]) : '';
    var beds = cBeds >= 0 ? String(row[cBeds] || '').trim() : '';
    var size = cSize >= 0 ? String(row[cSize] || '').trim() : '';
    var floor = cFloor >= 0 ? String(row[cFloor] || '').trim() : '';
    var rent = cRent >= 0 ? String(row[cRent] || '').trim() : '';
    var sale = cSale >= 0 ? String(row[cSale] || '').trim() : '';
    var zoneRaw = cZone >= 0 ? String(row[cZone] || '').trim() : '';
    var transitRaw = cTransit >= 0 ? String(row[cTransit] || '').trim() : '';
    var sourceLink = cSource >= 0 ? cleanLink_(row[cSource]) : '';
    var ownerLink = cOwner >= 0 ? cleanLink_(row[cOwner]) : '';
    var postLink = cPost >= 0 ? cleanLink_(row[cPost]) : '';
    var pageLink = cPages >= 0 ? cleanLink_(row[cPages]) : '';

    var loc;
    var master = lookupProjectLoc_(projMap, project);
    if (master && (master.zone || master.transit)) {
      loc = { zone: master.zone, transit: master.transit };
    } else if (sourceLabel === 'Hub' && (zoneRaw || transitRaw)) {
      loc = {
        zone: zoneRaw,
        transit: transitRaw.split(',').map(function (s) { return s.trim(); }).filter(Boolean).slice(0, 3).join(', ')
      };
    } else {
      loc = splitMixedLocation_(transitRaw || zoneRaw);
    }

    var searchGen = [code, project].join(' ').toLowerCase();
    var searchLoc = [loc.zone, loc.transit, zoneRaw, transitRaw].join(' ').toLowerCase();

    out.push({
      code: code,
      source: sourceLabel === 'Hub' ? 'Hub' : 'ชีท',
      dateIn: dateIn,
      project: project,
      propType: propType,
      beds: beds,
      size: size,
      floor: floor,
      rent: rent,
      sale: sale === '-' ? '' : sale,
      zone: loc.zone,
      transit: loc.transit,
      sourceLink: sourceLink,
      ownerLink: ownerLink,
      postLink: postLink,
      pageLink: pageLink,
      searchGen: searchGen,
      searchLoc: searchLoc,
      sortTs: parseSheetDate_(dateIn),
    });
  }
  return out;
}

function parseSheetDate_(raw) {
  var s = String(raw || '').trim();
  if (!s) return 0;
  if (/^\d+(\.\d+)?$/.test(s)) {
    var n = Number(s);
    if (n > 20000 && n < 80000) {
      return (n - 25569) * 86400000;
    }
  }
  var m = s.match(/^(\d{1,2})[\/\-](\d{1,2})[\/\-](\d{2,4})$/);
  if (m) {
    var d = parseInt(m[1], 10);
    var mo = parseInt(m[2], 10) - 1;
    var y = parseInt(m[3], 10);
    if (y < 100) y += 2000;
    return new Date(y, mo, d).getTime();
  }
  // non-date text (เว้น / ขายรอนัทคีย์) → bottom when sorting newest-first
  return 0;
}

function protectAppDashboard_(sh) {
  var protections = sh.getProtections(SpreadsheetApp.ProtectionType.SHEET);
  for (var i = 0; i < protections.length; i++) {
    try { protections[i].remove(); } catch (e) { /* ignore */ }
  }
  var rangeProtections = sh.getProtections(SpreadsheetApp.ProtectionType.RANGE);
  for (var j = 0; j < rangeProtections.length; j++) {
    try { rangeProtections[j].remove(); } catch (e2) { /* ignore */ }
  }

  var protection = sh.protect().setDescription('ทรัพย์รวม · อ่านอย่างเดียว ยกเว้นช่องค้นหา');
  protection.setWarningOnly(false);
  var search = sh.getRange(APP_SEARCH_CELL);
  var locSearch = sh.getRange(APP_LOC_SEARCH_CELL);
  protection.setUnprotectedRanges([search, locSearch]);

  try {
    var me = Session.getEffectiveUser();
    protection.addEditor(me);
    protection.removeEditors(protection.getEditors());
    if (protection.canDomainEdit()) protection.setDomainEdit(false);
    protection.addEditor(me);
  } catch (err) {
    try {
      protection.setWarningOnly(true);
    } catch (e3) { /* ignore */ }
  }
}
