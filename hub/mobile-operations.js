/* Phase Z13 — mobile-first operations enhancements */
(function () {
  "use strict";

  var RECHECK_STATUS_TH = {
    RECHECK_QUEUED: "รอเข้าคิว",
    RECHECK_ASSIGNED: "มอบหมายแล้ว",
    RECHECK_WAITING_OWNER: "รอเจ้าของตอบ",
    RECHECK_CONTACTED: "ติดต่อแล้ว",
    RECHECK_DONE: "เสร็จแล้ว"
  };

  var LISTING_KIND_TH = {
    rent: "เช่า",
    sale: "ขาย",
    both: "เช่า+ขาย"
  };

  function isMobile() {
    return window.matchMedia("(max-width: 768px)").matches;
  }

  function isTablet() {
    return window.matchMedia("(min-width: 769px) and (max-width: 1024px)").matches;
  }

  function esc(s) {
    if (typeof window.esc === "function") return window.esc(s);
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function recheckStatusLabel(st) {
    return RECHECK_STATUS_TH[st] || (st || "—").replace(/_/g, " ");
  }

  function listingKindLabel(k) {
    return LISTING_KIND_TH[k] || k || "—";
  }

  function formatPriceRow(p) {
    var bits = [];
    if (p.rent_price) bits.push("เช่า ฿" + String(p.rent_price).replace(/\B(?=(\d{3})+(?!\d))/g, ","));
    if (p.sale_price) bits.push("ขาย ฿" + String(p.sale_price).replace(/\B(?=(\d{3})+(?!\d))/g, ","));
    return bits.join(" · ") || "—";
  }

  function renderRecheckTaskCard(x, opts) {
    opts = opts || {};
    var code = x.property_code_display || x.property_id || "—";
    var project = x.project_name_display || "—";
    var meta = listingKindLabel(x.listing_kind);
    if (x.record_age_days != null) meta += " · อายุ " + x.record_age_days + " วัน";
    if (x.days_remaining != null) meta += " · เหลือ " + x.days_remaining + " วัน";
    if (x.contract_end) meta += " · หมด " + x.contract_end;
    var status = opts.section === "lease"
      ? "ใกล้หมดสัญญา"
      : opts.section === "backlog"
        ? "รอเข้าคิว"
        : recheckStatusLabel(x.queue_state);
    var openBtn = x.property_id
      ? '<button type="button" class="btn-sm primary" data-recheck-open="' + esc(x.property_id) + '">เปิดทรัพย์</button>'
      : "";
    return (
      '<article class="recheck-task-card" data-recheck-section="' + esc(opts.section || "") + '">' +
        '<div class="rtc-project">' + esc(project) + "</div>" +
        '<div class="rtc-code">' + esc(code) + "</div>" +
        '<div class="rtc-meta">' + esc(meta) + "</div>" +
        '<span class="rtc-status">' + esc(status) + "</span>" +
        '<div class="rtc-actions">' + openBtn + "</div>" +
      "</article>"
    );
  }

  function renderRecheckMobileCards(d, active, backlog) {
    if (!isMobile() && !isTablet()) return;
    var host = document.getElementById("recheck-mobile-cards");
    if (!host) return;
    var cards = [];
    (active || []).forEach(function (x) {
      cards.push(renderRecheckTaskCard(x, { section: "active" }));
    });
    (backlog || []).slice(0, 20).forEach(function (x) {
      cards.push(renderRecheckTaskCard(x, { section: "backlog" }));
    });
    (d.lease_end_soon || []).forEach(function (x) {
      cards.push(renderRecheckTaskCard(x, { section: "lease" }));
    });
    if (!cards.length) {
      host.innerHTML = '<div class="recheck-empty-state">วันนี้ไม่มีทรัพย์ที่ต้องติดตาม</div>';
      return;
    }
    host.innerHTML = cards.join("");
  }

  window.ptpRenderRecheckMobileCards = renderRecheckMobileCards;

  function patchRenderRecheckPanel() {
    if (typeof window.renderRecheckPanel !== "function" || window.renderRecheckPanel.__z13) return;
    var orig = window.renderRecheckPanel;
    window.renderRecheckPanel = function () {
      orig();
      var d = (window.recheckCache && window.recheckCache.dashboard) || {};
      var strip = document.getElementById("recheck-stats-strip");
      if (strip) {
        var cats = d.categories || {};
        strip.innerHTML = [
          { l: "รอเข้าคิว", n: (cats.eligible_backlog || {}).count || 0, f: "backlog" },
          { l: "ต้องติดตาม", n: (cats.active_queue || {}).count || 0, f: "active" },
          { l: "ชุดวันนี้เหลือ", n: (cats.batch_remaining_today || {}).count || 0, f: "" },
          { l: "ใกล้หมดสัญญา", n: (cats.lease_end_soon || {}).count || 0, f: "lease" },
          { l: "รอเจ้าของ", n: (cats.waiting_owner || {}).count || 0, f: "owner" }
        ].map(function (c) {
          var cls = c.f ? ' class="meta-chip recheck-filter-chip" data-recheck-chip="' + esc(c.f) + '"' : ' class="meta-chip"';
          return "<span" + cls + "><strong>" + esc(c.l) + "</strong> " + esc(String(c.n)) + "</span>";
        }).join(" ");
      }
      var active = [];
      var backlog = [];
      if (typeof window.recheckFilterRows === "function") {
        active = window.recheckFilterRows(d.active_queue_rows || [], "active");
        backlog = window.recheckFilterRows((d.capacity_model || {}).backlog_sample || [], "backlog");
      }
      renderRecheckMobileCards(d, active, backlog);
    };
    window.renderRecheckPanel.__z13 = true;
  }

  function initStickySave() {
    var bar = document.getElementById("mobile-sticky-save");
    var btn = document.getElementById("mobile-sticky-save-btn");
    var status = document.getElementById("mobile-sticky-save-status");
    var proceed = document.getElementById("add-proceed");
    if (!bar || !btn || !proceed) return;

    function syncVisible() {
      var onAdd = typeof window.activeView === "string" && window.activeView === "add";
      bar.classList.toggle("show", onAdd && isMobile());
    }

    btn.addEventListener("click", function () {
      proceed.click();
    });

    var dirty = false;
    function markDirty() {
      dirty = true;
      bar.classList.add("unsaved");
      if (status) status.textContent = "ยังไม่บันทึก";
    }
    function markSaved() {
      dirty = false;
      bar.classList.remove("unsaved");
      if (status) status.textContent = "พร้อมบันทึก";
    }

    ["add-url", "add-project", "add-rent", "add-sale", "add-notes", "add-raw"].forEach(function (id) {
      var el = document.getElementById(id);
      if (el) el.addEventListener("input", markDirty);
    });

    proceed.addEventListener("click", function () {
      if (status) status.textContent = "กำลังบันทึก…";
    });

    var origSwitch = window.switchView;
    if (typeof origSwitch === "function" && !origSwitch.__z13Sticky) {
      window.switchView = function (view) {
        var r = origSwitch.apply(this, arguments);
        syncVisible();
        if (view === "add" && !dirty && status) status.textContent = "พร้อมบันทึก";
        return r;
      };
      window.switchView.__z13Sticky = true;
    }

    markSaved();
    syncVisible();
  }

  function useAddStepAccordion() {
    // Phone + iPad portrait/tablet — accordion hides other sections.
    // Desktop (≥1025) keeps all zones expanded.
    return window.matchMedia("(max-width: 1024px)").matches;
  }

  function initAddStepNav() {
    var nav = document.getElementById("add-step-nav");
    if (!nav || nav.dataset.z136Ready === "1") return;
    nav.dataset.z136Ready = "1";
    var zones = [
      { id: "add-zone-source", label: "ต้นทาง" },
      { id: "add-zone-details", label: "ข้อมูลทรัพย์" },
      { id: "add-zone-post", label: "ข้อความโพสต์" },
      { id: "add-zone-groups", label: "บันทึก" }
    ];
    nav.innerHTML = zones.map(function (z, i) {
      return '<button type="button" class="add-step-btn' + (i === 0 ? " active" : "") +
        '" data-step-zone="' + z.id + '">' + esc(z.label) + "</button>";
    }).join("");

    function applyAccordion(zoneId) {
      if (!useAddStepAccordion()) {
        zones.forEach(function (zz) {
          var zzEl = document.getElementById(zz.id);
          if (zzEl) zzEl.classList.remove("collapsed-mobile");
        });
        return;
      }
      zones.forEach(function (zz) {
        var zzEl = document.getElementById(zz.id);
        if (zzEl) zzEl.classList.toggle("collapsed-mobile", zz.id !== zoneId);
      });
    }

    function go(zoneId) {
      if (!zoneId) zoneId = "add-zone-source";
      applyAccordion(zoneId);
      nav.querySelectorAll(".add-step-btn").forEach(function (b) {
        b.classList.toggle("active", b.getAttribute("data-step-zone") === zoneId);
      });
      var el = document.getElementById(zoneId);
      if (el) {
        try {
          el.scrollIntoView({ behavior: "smooth", block: "start" });
        } catch (e) {
          try { el.scrollIntoView(true); } catch (e2) { /* ignore */ }
        }
      }
      return zoneId;
    }

    // Public: Edit/Add open + tests must reset to step 1 (Z13.6).
    window.ptpGoAddStep = go;
    window.ptpResetAddStepNav = function () {
      return go("add-zone-source");
    };

    nav.addEventListener("click", function (e) {
      var btn = e.target.closest("[data-step-zone]");
      if (!btn) return;
      e.preventDefault();
      go(btn.getAttribute("data-step-zone"));
    });

    // Zone heads: ALL steps including ต้นทาง (previously skipped → unreachable).
    zones.forEach(function (z) {
      var zone = document.getElementById(z.id);
      if (!zone) return;
      var head = zone.querySelector(".add-zone-head");
      if (!head || head.dataset.z136Bound === "1") return;
      head.dataset.z136Bound = "1";
      head.style.cursor = "pointer";
      head.addEventListener("click", function () {
        go(z.id);
      });
    });

    // Initial accordion: step 1 open, later steps collapsed on phone/iPad.
    applyAccordion("add-zone-source");
  }

  function initOwnerContactBlock() {
    var grid = document.querySelector("#add-zone-source .add-grid");
    if (!grid || document.getElementById("owner-contact-block")) return;
    var phone = document.getElementById("add-owner-phone");
    var line = document.getElementById("add-owner-line");
    if (!phone || !line) return;

    var block = document.createElement("div");
    block.id = "owner-contact-block";
    block.className = "owner-contact-block add-wide";
    block.innerHTML =
      "<strong>เจ้าของ (ภายในเท่านั้น)</strong>" +
      '<div class="owner-contact-row"><span>โทร</span><span id="owner-phone-display">—</span>' +
      '<div class="owner-contact-actions"><button type="button" class="btn-sm" id="owner-phone-copy">คัดลอก</button></div></div>' +
      '<div class="owner-contact-row"><span>LINE</span><span id="owner-line-display">—</span>' +
      '<div class="owner-contact-actions"><button type="button" class="btn-sm" id="owner-line-copy">คัดลอก</button></div></div>';

    phone.closest("label").style.display = "none";
    line.closest("label").style.display = "none";
    grid.appendChild(block);

    function sync() {
      var pd = document.getElementById("owner-phone-display");
      var ld = document.getElementById("owner-line-display");
      if (pd) pd.textContent = phone.value || "—";
      if (ld) ld.textContent = line.value || "—";
    }
    phone.addEventListener("input", sync);
    line.addEventListener("input", sync);
    sync();

    var pc = document.getElementById("owner-phone-copy");
    var lc = document.getElementById("owner-line-copy");
    if (pc) pc.addEventListener("click", function () {
      if (phone.value && navigator.clipboard) navigator.clipboard.writeText(phone.value);
    });
    if (lc) lc.addEventListener("click", function () {
      if (line.value && navigator.clipboard) navigator.clipboard.writeText(line.value);
    });
  }

  function initMoreMenu() {
    var sheet = document.getElementById("mobile-more-sheet");
    var backdrop = document.getElementById("mobile-more-backdrop");
    var moreBtn = document.querySelector('#mobile-nav [data-view="more"]');
    if (!sheet || !backdrop || !moreBtn) return;

    function open() {
      sheet.classList.add("open");
      backdrop.classList.add("open");
    }
    function close() {
      sheet.classList.remove("open");
      backdrop.classList.remove("open");
    }

    moreBtn.addEventListener("click", function (e) {
      e.stopPropagation();
      open();
    });
    backdrop.addEventListener("click", close);
    sheet.querySelectorAll("[data-more-view]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var view = btn.getAttribute("data-more-view");
        close();
        if (view && typeof window.switchView === "function") {
          window.switchView(view);
          document.querySelectorAll("#mobile-nav button[data-view]").forEach(function (b) {
            b.classList.toggle("active", b.getAttribute("data-view") === view);
          });
        }
        if (view === "db" && typeof window.switchDbTab === "function") {
          var tab = btn.getAttribute("data-more-db") || "projects";
          window.switchDbTab(tab);
        }
      });
    });
  }

  function initMobileNavAdd() {
    var addBtn = document.querySelector('#mobile-nav [data-view="add"]');
    if (!addBtn) return;
    addBtn.addEventListener("click", function (e) {
      e.preventDefault();
      e.stopPropagation();
      if (typeof window.startAddProperty === "function") {
        window.startAddProperty();
      } else if (typeof window.switchView === "function") {
        window.switchView("add");
      }
      document.querySelectorAll("#mobile-nav button[data-view]").forEach(function (b) {
        b.classList.toggle("active", b.getAttribute("data-view") === "add");
      });
    });
  }

  function initFilterSheet() {
    var toggle = document.getElementById("toggle-filters");
    var drawer = document.getElementById("filters-drawer");
    if (!toggle || !drawer) return;

    var backdrop = document.getElementById("filters-drawer-backdrop");
    if (!backdrop) {
      backdrop = document.createElement("div");
      backdrop.className = "filters-drawer-backdrop hidden";
      backdrop.id = "filters-drawer-backdrop";
      document.body.appendChild(backdrop);
    }

    function syncBackdrop() {
      var open = !drawer.classList.contains("hidden") && isMobile();
      backdrop.classList.toggle("hidden", !open);
    }

    syncBackdrop();

    function closeFilterDrawer() {
      drawer.classList.add("hidden");
      toggle.classList.remove("active-filter-btn");
      toggle.textContent = "ตัวกรอง";
      syncBackdrop();
    }

    backdrop.addEventListener("click", function () {
      closeFilterDrawer();
    });

    toggle.addEventListener("click", function () {
      setTimeout(syncBackdrop, 0);
    });

    // Escape must close sheet + backdrop — otherwise backdrop blocks pagination/cards.
    document.addEventListener("keydown", function (e) {
      if (e.key !== "Escape") return;
      if (drawer.classList.contains("hidden")) return;
      closeFilterDrawer();
    });

    var apply = document.getElementById("apply-filter-btn");
    if (apply) apply.addEventListener("click", function () {
      setTimeout(function () {
        closeFilterDrawer();
      }, 0);
    });
  }

  function initRecheckSummaryCards() {
    document.addEventListener("click", function (e) {
      var chip = e.target.closest("[data-recheck-chip]");
      if (!chip) return;
      var f = chip.getAttribute("data-recheck-chip");
      var cards = document.querySelectorAll(".recheck-task-card");
      if (!cards.length) return;
      cards.forEach(function (c) {
        var sec = c.getAttribute("data-recheck-section") || "";
        var show = !f || sec === f || (f === "owner" && sec === "active");
        c.style.display = show ? "" : "none";
      });
      document.querySelectorAll(".recheck-summary-card").forEach(function (b) {
        b.classList.toggle("active", b.getAttribute("data-recheck-filter") === f);
      });
    });
  }

  window.ptpCheckHorizontalOverflow = function () {
    var sw = document.documentElement.scrollWidth;
    var vw = window.innerWidth;
    return { scrollWidth: sw, viewport: vw, overflow: sw > vw + 1 };
  };

  window.ptpMeasureNavGeometry = function () {
    var nav = document.getElementById("mobile-nav");
    if (!nav) return { ok: false, reason: "no nav" };
    var vw = window.innerWidth;
    var slots = nav.querySelectorAll("button[data-view]");
    var widths = [];
    slots.forEach(function (b) {
      var r = b.getBoundingClientRect();
      widths.push(Math.round(r.width));
    });
    var addBtn = nav.querySelector('[data-view="add"]');
    var addFab = addBtn ? addBtn.querySelector(".nav-add-fab") : null;
    var navRect = nav.getBoundingClientRect();
    var centerX = addBtn ? addBtn.getBoundingClientRect().left + addBtn.getBoundingClientRect().width / 2 : 0;
    var fabRect = addFab ? addFab.getBoundingClientRect() : null;
    var avg = widths.length ? widths.reduce(function (a, b) { return a + b; }, 0) / widths.length : 0;
    var maxDev = widths.length ? Math.max.apply(null, widths.map(function (w) { return Math.abs(w - avg); })) : 999;
    return {
      ok: true,
      viewport: vw,
      navWidth: Math.round(navRect.width),
      slotWidths: widths,
      slotWidthDeviation: Math.round(maxDev),
      equalSlots: maxDev <= 12,
      centerOffset: Math.round(centerX - vw / 2),
      centerAligned: Math.abs(centerX - vw / 2) <= 8,
      navHeight: Math.round(navRect.height),
      fabProtrusion: fabRect ? Math.round(navRect.top - fabRect.top) : 0,
      fabSize: fabRect ? Math.round(fabRect.width) : 0
    };
  };

  function initMobileSearch() {
    var box = document.getElementById("search-box");
    if (box && isMobile()) {
      box.placeholder = "ค้นหารหัส โครงการ หรือทำเล";
    }
    var loc = document.getElementById("location-search");
    if (loc && isMobile()) {
      loc.setAttribute("aria-hidden", "true");
    }
  }

  function initPropMoreMenu() {
    document.addEventListener("click", function (e) {
      var moreBtn = e.target.closest("[data-prop-more]");
      if (moreBtn) {
        e.preventDefault();
        e.stopPropagation();
        var wrap = moreBtn.closest(".prop-quick-actions");
        var menu = wrap ? wrap.querySelector(".prop-more-menu") : null;
        document.querySelectorAll(".prop-more-menu").forEach(function (m) {
          if (m !== menu) m.classList.add("hidden");
        });
        if (menu) menu.classList.toggle("hidden");
        return;
      }
      if (!e.target.closest(".prop-more-menu")) {
        document.querySelectorAll(".prop-more-menu").forEach(function (m) {
          m.classList.add("hidden");
        });
      }
    });
  }

  function initFilterSheetPolish() {
    var drawer = document.getElementById("filters-drawer");
    if (!drawer || drawer.dataset.z131 === "1") return;
    drawer.dataset.z131 = "1";
    if (!drawer.querySelector(".mobile-filter-sheet-head")) {
      var head = document.createElement("div");
      head.className = "mobile-filter-sheet-head";
      head.innerHTML = '<strong>ตัวกรอง</strong><button type="button" class="btn-sm" id="mobile-filter-close">ปิด</button>';
      drawer.insertBefore(head, drawer.firstChild);
    }
    if (!drawer.querySelector(".mobile-filter-sheet-actions")) {
      var actions = document.createElement("div");
      actions.className = "mobile-filter-sheet-actions";
      actions.innerHTML =
        '<button type="button" class="btn-sm" id="mobile-filter-reset">ล้างตัวกรอง</button>' +
        '<button type="button" class="btn-sm primary" id="mobile-filter-apply">ดูผลลัพธ์</button>';
      drawer.appendChild(actions);
    }
    var closeBtn = document.getElementById("mobile-filter-close");
    if (closeBtn) {
      closeBtn.addEventListener("click", function () {
        var d = document.getElementById("filters-drawer");
        var t = document.getElementById("toggle-filters");
        if (d) d.classList.add("hidden");
        if (t) { t.classList.remove("active-filter-btn"); t.textContent = "ตัวกรอง"; }
        var bd = document.getElementById("filters-drawer-backdrop");
        if (bd) bd.classList.add("hidden");
      });
    }
    var applyM = document.getElementById("mobile-filter-apply");
    if (applyM) {
      applyM.addEventListener("click", function () {
        var a = document.getElementById("apply-filter-btn");
        if (a) a.click();
        var close = document.getElementById("mobile-filter-close");
        if (close) close.click();
      });
    }
    var resetM = document.getElementById("mobile-filter-reset");
    if (resetM) {
      resetM.addEventListener("click", function () {
        var r = document.getElementById("reset-filter");
        if (r) r.click();
      });
    }
  }

  function boot() {
    patchRenderRecheckPanel();
    initStickySave();
    initAddStepNav();
    initOwnerContactBlock();
    initMoreMenu();
    initMobileNavAdd();
    initFilterSheet();
    initFilterSheetPolish();
    initRecheckSummaryCards();
    initMobileSearch();
    initPropMoreMenu();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
