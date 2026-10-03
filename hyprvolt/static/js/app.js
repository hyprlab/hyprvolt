/* Hyprvolt client. No dependencies, no build step.
 *
 * Sections, in order: API, toasts, theme, mobile sidebar, dialogs, settings,
 * admin, menus, records, the record form, data-* behaviors, the detail sheet,
 * editing in place, the picture viewer, keyboard, search palette, paging, pull
 * to refresh, the About hero. Each section guards on the elements it needs,
 * so deleting one leaves the rest working.
 */
(function () {
  "use strict";

  var CSRF = (document.querySelector('meta[name="csrf"]') || {}).content || "";
  var root = document.documentElement;
  var sheet = document.getElementById("sheet");

  /* ————— API ————— */
  // Every call goes through here, so the CSRF header and the {"error": "..."}
  // convention live in exactly one place.
  function api(url, body) {
    return request(url, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRF": CSRF },
      body: JSON.stringify(body || {})
    });
  }
  function get(url) {
    return request(url, { headers: { "X-CSRF": CSRF, "Accept": "application/json" } });
  }
  function request(url, opts) {
    return fetch(url, opts).then(function (resp) {
      return resp.json().catch(function () { return {}; }).then(function (data) {
        if (!resp.ok) throw new Error(data.error || "Something went wrong.");
        return data;
      });
    }, function () {
      throw new Error("Can't reach the server.");
    });
  }

  function setBusy(btn, busy) {
    if (!btn) return;
    btn.disabled = busy;
    var label = btn.querySelector(".btn-label"), busyEl = btn.querySelector(".btn-busy");
    if (label) label.hidden = busy;
    if (busyEl) busyEl.hidden = !busy;
  }

  /* ————— Toast ————— */
  var toastTimer, toastLeaveTimer;
  function dismissToast(el) {
    if (el.hidden) return;
    el.classList.add("is-leaving");
    clearTimeout(toastLeaveTimer);
    toastLeaveTimer = setTimeout(function () {
      el.hidden = true;
      el.classList.remove("is-leaving");
    }, 260);
  }
  // toast("Saved") · toast("Deleted", "Undo", fn) · toast(err.message, null, null, true)
  function toast(message, actionLabel, actionFn, isError) {
    var el = document.getElementById("toast");
    if (!el) return;
    // A modal <dialog> paints above everything outside it, so a toast raised
    // while a dialog is open has to live inside it to be seen at all; not in
    // one on its way out (the sheet sliding away), or it goes with it.
    var open = document.querySelector("dialog[open]:not(.is-closing)");
    var host = open || document.body;
    if (el.parentNode !== host) host.appendChild(el);
    clearTimeout(toastTimer);
    clearTimeout(toastLeaveTimer);
    el.classList.remove("is-leaving");
    el.classList.toggle("toast--error", !!isError);
    el.textContent = message;
    if (actionLabel) {
      var action = document.createElement("button");
      action.className = "toast-action";
      action.textContent = actionLabel;
      action.addEventListener("click", function () {
        clearTimeout(toastTimer);
        dismissToast(el);
        actionFn();
      });
      el.appendChild(action);
    }
    el.hidden = false;
    toastTimer = setTimeout(function () { dismissToast(el); }, actionLabel ? 3500 : 2600);
  }
  function toastError(err) { toast(err.message || String(err), null, null, true); }

  // Carries a toast across a reload, for changes the page has to be rebuilt for.
  function queueToast(message) {
    try { sessionStorage.setItem("app-toast", message); } catch (_) {}
  }
  function reloadWith(message) { queueToast(message); location.reload(); }
  try {
    var pending = sessionStorage.getItem("app-toast");
    if (pending) {
      sessionStorage.removeItem("app-toast");
      setTimeout(function () { toast(pending); }, 250);
    }
  } catch (_) {}

  /* ————— Theme ————— */
  var media = window.matchMedia("(prefers-color-scheme: dark)");
  function applyTheme(pref) {
    root.setAttribute("data-theme-pref", pref);
    root.setAttribute("data-theme", pref === "system" ? (media.matches ? "dark" : "light") : pref);
  }
  media.addEventListener("change", function () {
    if (root.getAttribute("data-theme-pref") === "system") applyTheme("system");
  });

  var themeBtn = document.getElementById("theme-btn");
  if (themeBtn) {
    themeBtn.addEventListener("click", function () {
      var next = root.getAttribute("data-theme") === "dark" ? "light" : "dark";
      applyTheme(next);
      var radio = document.querySelector('input[name="theme"][value="' + next + '"]');
      if (radio) radio.checked = true;
      // Signed in it is the account's; before that (the first-run setup
      // page), this browser's, and the setup gives it to the admin.
      if (root.hasAttribute("data-signed-in")) api("/settings", { theme: next }).catch(function () {});
      else try { localStorage.setItem("theme", next); } catch (_) {}
    });
  }
  document.querySelectorAll('input[name="theme"]').forEach(function (radio) {
    radio.addEventListener("change", function () {
      applyTheme(radio.value);
      api("/settings", { theme: radio.value }).catch(function () {});
    });
  });

  /* ————— Sidebar (mobile) ————— */
  var sidebar = document.getElementById("sidebar");
  var scrim = document.querySelector(".scrim");
  function setSidebar(open) {
    if (!sidebar) return;
    sidebar.classList.toggle("is-open", open);
    if (scrim) scrim.hidden = !open;
  }
  document.querySelectorAll("[data-open-sidebar]").forEach(function (el) {
    el.addEventListener("click", function () { setSidebar(true); });
  });
  document.querySelectorAll("[data-close-sidebar]").forEach(function (el) {
    el.addEventListener("click", function () { setSidebar(false); });
  });

  /* ————— Dialogs ————— */
  /* The settings window: a rail of sections and one pane at a time. On a
     phone only one of the two shows, and .is-showing-pane says which. */
  var settingsModal = document.getElementById("settings-modal");
  var narrow = window.matchMedia("(max-width: 700px)");
  function settingsItems() {
    return settingsModal ? Array.prototype.slice.call(settingsModal.querySelectorAll(".settings-navitem")) : [];
  }
  function showSettingsSection(name, focusItem) {
    if (!settingsModal) return;
    var chosen = null;
    settingsItems().forEach(function (item) {
      var on = item.getAttribute("data-section") === name;
      item.classList.toggle("is-active", on);
      item.setAttribute("aria-selected", on ? "true" : "false");
      item.tabIndex = on ? 0 : -1;
      if (on) chosen = item;
    });
    if (!chosen) return;
    settingsModal.querySelectorAll(".settings-pane").forEach(function (pane) {
      var on = pane.getAttribute("data-pane") === name;
      if (on && !pane.classList.contains("is-active")) pane.scrollTop = 0;
      pane.classList.toggle("is-active", on);
    });
    document.getElementById("settings-section-title").textContent =
      chosen.querySelector("span").textContent;
    settingsModal.classList.add("is-showing-pane");
    if (focusItem) chosen.focus();
  }
  function showSettingsList() {
    if (!settingsModal) return;
    settingsModal.classList.remove("is-showing-pane");
    var active = settingsModal.querySelector(".settings-navitem.is-active");
    if (active) active.focus();
  }

  function openDialog(id, section) {
    var dialog = document.getElementById(id);
    if (!dialog || dialog.open) return;
    if (id === "settings-modal") {
      // A named section opens straight to it. Otherwise the window reopens
      // where it was left, except on a phone, where it starts at the list.
      if (section) showSettingsSection(section);
      else if (narrow.matches) dialog.classList.remove("is-showing-pane");
    }
    setSidebar(false);
    dialog.showModal();
  }
  // Delegated, so buttons that arrive later (an empty state re-rendered by
  // paging) open their dialog too.
  document.addEventListener("click", function (e) {
    var btn = e.target.closest("[data-open]");
    if (btn) openDialog(btn.getAttribute("data-open"), btn.getAttribute("data-settings-section"));
  });

  function prefersReducedMotion() {
    return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  }

  // The sheet slides back down out of view before it actually closes, so
  // every way of dismissing it routes through here (its button, Escape).
  var SHEET_EXIT_MS = 300;   // keep in step with the sheet-out animation
  var sheetExitTimer = null;
  function closeDialog(dialog, then, force) {
    // A record being edited saves what is still unsaved before it goes; if
    // that fails it stays open once, with the error at the field.
    if (dialog.id === "sheet" && !force && editsPending()) {
      flushEdits().then(function (ok) {
        if (ok || discardArmed) { discardArmed = false; closeDialog(dialog, then, true); }
        else warnUnsaved("Close");
      });
      return;
    }
    if (dialog.id !== "sheet" || prefersReducedMotion()) {
      dialog.close();
      if (then) then();
      return;
    }
    if (dialog.classList.contains("is-closing")) return;
    dialog.classList.add("is-closing");
    clearTimeout(sheetExitTimer);
    sheetExitTimer = setTimeout(function () {
      dialog.classList.remove("is-closing");
      dialog.close();
      if (then) then();
    }, SHEET_EXIT_MS);
  }

  // A click on a modal's ::backdrop is dispatched to the <dialog> itself, so
  // target identity alone can't tell it from a click on the dialog's own
  // chrome: the sheet's shell is wider than its 660px article column, so
  // its side gutters are the dialog element too. Compare the pointer with the
  // dialog's box (which follows the open/close transform) instead, and require
  // the press to have started outside as well, so a text selection dragged off
  // the article doesn't dismiss it.
  function hitOutside(dialog, e) {
    var r = dialog.getBoundingClientRect();
    if (!r.width || !r.height) return false;
    return e.clientX < r.left || e.clientX > r.right ||
           e.clientY < r.top || e.clientY > r.bottom;
  }
  function onBackdropClick(dialog, close) {
    var pressedOutside = false;
    dialog.addEventListener("pointerdown", function (e) {
      pressedOutside = e.target === dialog && hitOutside(dialog, e);
    });
    dialog.addEventListener("click", function (e) {
      var fromBackdrop = pressedOutside;
      pressedOutside = false;   // don't let a stale press arm a later click
      if (fromBackdrop && e.target === dialog && hitOutside(dialog, e)) close();
    });
  }
  // A toast showing inside a dialog that closes moves out with it still showing.
  document.querySelectorAll("dialog").forEach(function (dialog) {
    dialog.addEventListener("close", function () {
      var el = document.getElementById("toast");
      if (el && el.parentNode === dialog) (document.querySelector("dialog[open]") || document.body).appendChild(el);
    });
  });
  document.querySelectorAll("dialog").forEach(function (dialog) {
    // A modal or the sheet closes only when asked to (its close button, or
    // Escape), never from a click beside it that could throw away a form
    // half filled in. The search palette has no close button: a click
    // outside it still dismisses it.
    if (dialog.classList.contains("palette")) onBackdropClick(dialog, function () { closeDialog(dialog); });
    dialog.querySelectorAll("[data-close]").forEach(function (btn) {
      btn.addEventListener("click", function () { closeDialog(dialog); });
    });
    if (dialog.id === "sheet") {
      dialog.addEventListener("cancel", function (e) {   // Escape
        e.preventDefault();
        closeDialog(dialog);
      });
    }
  });

  /* ————— Settings ————— */
  if (settingsModal) {
    settingsItems().forEach(function (item) {
      item.addEventListener("click", function () {
        showSettingsSection(item.getAttribute("data-section"));
      });
    });
    // Arrow keys move through the rail and select as they go (the WAI-ARIA
    // vertical tab pattern); Home and End jump to the ends.
    settingsModal.querySelector(".settings-nav").addEventListener("keydown", function (e) {
      var items = settingsItems();
      var at = items.indexOf(document.activeElement);
      if (at === -1) return;
      var next = { ArrowDown: at + 1, ArrowUp: at - 1, Home: 0, End: items.length - 1 }[e.key];
      if (next === undefined) return;
      e.preventDefault();
      next = (next + items.length) % items.length;
      showSettingsSection(items[next].getAttribute("data-section"), true);
      if (narrow.matches) settingsModal.classList.remove("is-showing-pane");
    });
    settingsModal.querySelector(".settings-back").addEventListener("click", showSettingsList);
    // On a phone, Escape inside a section goes back to the list first.
    settingsModal.addEventListener("cancel", function (e) {
      if (narrow.matches && settingsModal.classList.contains("is-showing-pane")) {
        e.preventDefault();
        showSettingsList();
      }
    });
  }
  document.querySelectorAll('input[name="view_mode"]').forEach(function (radio) {
    radio.addEventListener("change", function () {
      api("/settings", { view_mode: radio.value })
        .then(function () { toast("Default view saved"); })
        .catch(toastError);
    });
  });

  var recordsRoot = document.getElementById("records-root");
  var infinite = document.getElementById("infinite-scroll");
  if (infinite) {
    infinite.addEventListener("change", function () {
      // Takes effect on the page behind the modal, no reload needed.
      if (recordsRoot) recordsRoot.setAttribute("data-infinite", infinite.checked ? "1" : "0");
      watchPager();
      api("/settings", { infinite_scroll: infinite.checked })
        .then(function () {
          toast(infinite.checked ? "Records load as you scroll" : "Load more records by hand");
        })
        .catch(toastError);
    });
  }

  var recordScroll = document.getElementById("record-scroll");
  if (recordScroll) {
    recordScroll.addEventListener("change", function () {
      api("/settings", { record_scroll: recordScroll.checked })
        .then(function () {
          toast(recordScroll.checked ? "A record shows all its sections" : "A record shows one section at a time");
          refreshSheet();    // an open record follows at once
        })
        .catch(toastError);
    });
  }

  var acctName = document.getElementById("acct-name");
  if (acctName) {
    acctName.addEventListener("change", function () {
      var value = acctName.value.trim();
      api("/settings", { name: value }).then(function () {
        toast("Name saved");
        var nameEl = document.getElementById("user-name");
        var emailEl = document.getElementById("user-email");
        var avatar = document.getElementById("user-avatar");
        var email = (emailEl && emailEl.textContent) || "";
        if (nameEl) nameEl.textContent = value || email;
        if (avatar) avatar.textContent = (value || email).charAt(0).toUpperCase();
        if (emailEl) emailEl.hidden = !value;
      }).catch(toastError);
    });
  }

  var passwordForm = document.getElementById("password-form");
  if (passwordForm) {
    passwordForm.addEventListener("submit", function (e) {
      e.preventDefault();
      var errEl = document.getElementById("pw-error");
      errEl.hidden = true;
      api("/account/password", {
        current: document.getElementById("pw-current").value,
        new: document.getElementById("pw-new").value
      }).then(function () {
        passwordForm.reset();
        toast("Password updated");
      }).catch(function (err) {
        errEl.textContent = err.message;
        errEl.hidden = false;
      });
    });
  }

  /* ————— Admin ————— */
  var regOpen = document.getElementById("reg-open");
  if (regOpen) {
    regOpen.addEventListener("change", function () {
      api("/admin/registration", { open: regOpen.checked }).then(function (data) {
        toast(data.open ? "Registration is open" : "Registration is closed");
      }).catch(toastError);
    });
  }
  [["inst-worker", "worker_minutes", "Background interval saved"],
   ["inst-perpage", "items_per_page", "Page size saved"],
   ["inst-purge", "purge_days", "Deleted records are kept that long"],
   ["inst-upload", "max_upload_mb", "Upload limit saved"],
   ["inst-reminders", "reminder_days", "Reminder window saved"],
   ["inst-backup-hours", "backup_hours", "Backup schedule saved"],
   ["inst-backup-keep", "backup_keep", "Saved"]].forEach(function (spec) {
    var input = document.getElementById(spec[0]);
    if (!input) return;
    input.addEventListener("change", function () {
      var body = {};
      body[spec[1]] = parseInt(input.value, 10);
      api("/admin/instance", body).then(function () { toast(spec[2]); }).catch(toastError);
    });
  });

  var tzSelect = document.getElementById("inst-tz");
  if (tzSelect) {
    tzSelect.addEventListener("change", function () {
      api("/admin/instance", { time_zone: tzSelect.value })
        .then(function () { toast("Times are in " + tzSelect.value); })
        .catch(toastError);
    });
  }

  document.querySelectorAll('input[name="default_role"]').forEach(function (radio) {
    radio.addEventListener("change", function () {
      api("/admin/instance", { default_role: radio.value })
        .then(function () { toast("New accounts start as " + radio.value + "s"); })
        .catch(toastError);
    });
  });

  document.querySelectorAll("[data-module-toggle]").forEach(function (box) {
    box.addEventListener("change", function () {
      var on = box.checked;
      api("/admin/modules/" + box.getAttribute("data-module-toggle"), { enabled: on }).then(function () {
        // The sidebar, search and every page change with it.
        reloadWith(on ? "Module turned on" : "Module turned off; its records are kept");
      }).catch(function (err) {
        box.checked = !on;   // the server still has it the other way
        toastError(err);
      });
    });
  });

  // [data-sortable]: a list whose [data-sort-item] children move by their
  // .sort-handle, dragged (mouse, pen or touch) or with ↑ and ↓ while it has
  // focus. Each move fires a "sorted" event from the list; what the order
  // means, and saving it, is up to whoever listens.
  var sorting = null;
  function sortItems(list) {
    return Array.prototype.filter.call(list.children, function (el) { return el.hasAttribute("data-sort-item"); });
  }
  function sortParts(handle) {
    var item = handle.closest("[data-sort-item]");
    var list = item && item.parentNode;
    return list && list.hasAttribute("data-sortable") ? { item: item, list: list } : null;
  }
  function sorted(list) { list.dispatchEvent(new CustomEvent("sorted", { bubbles: true })); }
  document.addEventListener("pointerdown", function (e) {
    var handle = e.target.closest(".sort-handle");
    var parts = handle && sortParts(handle);
    if (!parts || e.button !== 0) return;
    e.preventDefault();
    handle.setPointerCapture(e.pointerId);
    sorting = { handle: handle, item: parts.item, list: parts.list, before: sortItems(parts.list).indexOf(parts.item) };
    parts.item.classList.add("is-sorting");
    document.body.classList.add("is-sorting");
  });
  document.addEventListener("pointermove", function (e) {
    if (!sorting) return;
    // Near an edge of what scrolls around it, that scrolls, so a long list
    // can be crossed in one drag.
    var pane = sorting.list.closest(".settings-pane, .modal, .sheet");
    if (pane) {
      var box = pane.getBoundingClientRect();
      if (e.clientY < box.top + 40) pane.scrollTop -= 14;
      else if (e.clientY > box.bottom - 40) pane.scrollTop += 14;
    }
    // Goes before the first other item whose middle is below the pointer.
    var others = sortItems(sorting.list).filter(function (el) { return el !== sorting.item; });
    var next = others.find(function (el) {
      var r = el.getBoundingClientRect();
      return e.clientY < r.top + r.height / 2;
    });
    if (next ? sorting.item.nextElementSibling !== next : sortItems(sorting.list).pop() !== sorting.item) {
      sorting.list.insertBefore(sorting.item, next || null);
    }
  });
  function endSort() {
    if (!sorting) return;
    var s = sorting;
    sorting = null;
    s.item.classList.remove("is-sorting");
    document.body.classList.remove("is-sorting");
    if (sortItems(s.list).indexOf(s.item) !== s.before) sorted(s.list);
    s.handle.focus({ preventScroll: true });
  }
  document.addEventListener("pointerup", endSort);
  document.addEventListener("pointercancel", endSort);
  document.addEventListener("keydown", function (e) {
    var handle = e.target.closest && e.target.closest(".sort-handle");
    var parts = handle && sortParts(handle);
    if (!parts || (e.key !== "ArrowUp" && e.key !== "ArrowDown")) return;
    e.preventDefault();
    var items = sortItems(parts.list), at = items.indexOf(parts.item);
    var to = e.key === "ArrowUp" ? at - 1 : at + 1;
    if (to < 0 || to >= items.length) return;
    parts.list.insertBefore(parts.item, e.key === "ArrowUp" ? items[to] : items[to].nextElementSibling);
    handle.focus({ preventScroll: true });
    sorted(parts.list);
  });

  // Settings > Modules: the sidebar's order, saved as it changes; the
  // sidebar behind the settings follows at once.
  var sidebarOrder = document.querySelector("[data-sidebar-order]");
  var orderReset = document.getElementById("sidebar-order-reset");
  function arrangeSidebar(groups, modules) {
    var blocks = document.querySelectorAll(".sidebar .sidebar-group[data-group]");
    if (!blocks.length) return;
    var parent = blocks[0].parentNode, after = blocks[blocks.length - 1].nextSibling;
    groups.forEach(function (label) {
      var block = parent.querySelector(':scope > .sidebar-group[data-group="' + CSS.escape(label) + '"]');
      if (block) parent.insertBefore(block, after);
    });
    modules.forEach(function (id) {
      var link = parent.querySelector('.navitem[data-module="' + CSS.escape(id) + '"]');
      if (!link) return;
      var nested = link.nextElementSibling && link.nextElementSibling.matches(".sidelist--nested") ? link.nextElementSibling : null;
      link.parentNode.appendChild(link);
      if (nested) link.parentNode.appendChild(nested);
    });
  }
  if (sidebarOrder) {
    sidebarOrder.addEventListener("sorted", function () {
      var groups = Array.prototype.map.call(sidebarOrder.querySelectorAll("[data-group]"), function (el) { return el.getAttribute("data-group"); });
      var modules = Array.prototype.map.call(sidebarOrder.querySelectorAll("[data-module]"), function (el) { return el.getAttribute("data-module"); });
      api("/admin/sidebar-order", { groups: groups, modules: modules }).then(function () {
        arrangeSidebar(groups, modules);
        if (orderReset) orderReset.hidden = false;
      }).catch(toastError);
    });
  }
  if (orderReset) {
    orderReset.addEventListener("click", function () {
      api("/admin/sidebar-order", { reset: true }).then(function () {
        reloadWith("The sidebar is back in its default order");
      }).catch(toastError);
    });
  }

  var adduserForm = document.getElementById("admin-adduser");
  if (adduserForm) {
    adduserForm.addEventListener("submit", function (e) {
      e.preventDefault();
      var errEl = document.getElementById("au-error");
      errEl.hidden = true;
      api("/admin/users", {
        name: document.getElementById("au-name").value.trim(),
        username: document.getElementById("au-email").value.trim(),
        password: document.getElementById("au-password").value,
        role: document.getElementById("au-role").value
      }).then(function () {
        reloadWith("User created");
      }).catch(function (err) {
        errEl.textContent = err.message;
        errEl.hidden = false;
      });
    });
  }
  document.querySelectorAll(".manage-item[data-user]").forEach(function (item) {
    var userId = item.getAttribute("data-user");
    var username = item.getAttribute("data-username");
    var pwBtn = item.querySelector("[data-admin-password]");
    var deleteBtn = item.querySelector("[data-admin-delete]");
    if (pwBtn) {
      pwBtn.addEventListener("click", function () {
        var pw = prompt('New password for "' + username + '" (at least 8 characters):');
        if (pw === null) return;
        api("/admin/users/" + userId + "/password", { new: pw })
          .then(function () { toast("Password reset for " + username); })
          .catch(toastError);
      });
    }
    item.querySelectorAll("[data-admin-role]").forEach(function (radio) {
      radio.addEventListener("change", function () {
        api("/admin/users/" + userId + "/role", { role: radio.value }).then(function (data) {
          toast(username + " is now " + (data.role === "admin" ? "an admin" : "a" + (data.role === "editor" ? "n editor" : " viewer")));
        }).catch(function (err) {
          // Roll back to the role the server still has.
          var was = item.getAttribute("data-role");
          item.querySelectorAll("[data-admin-role]").forEach(function (r) { r.checked = r.value === was; });
          toastError(err);
        }).then(function () {
          var now = item.querySelector("[data-admin-role]:checked");
          if (now) item.setAttribute("data-role", now.value);
        });
      });
    });
    if (deleteBtn) {
      deleteBtn.addEventListener("click", function () {
        if (!confirm('Delete the account "' + username + '"? The documentation they wrote stays. This cannot be undone.')) return;
        api("/admin/users/" + userId + "/delete")
          .then(function () { reloadWith("Deleted " + username); })
          .catch(toastError);
      });
    }
  });

  /* ————— Security: Cloudflare Turnstile ————— */
  // Turning Turnstile on (or changing its keys) goes through a real challenge
  // rendered with the new site key; the server saves the keys only if
  // Cloudflare accepts the answer with the new secret. A wrong pair saved
  // blindly would lock everyone out of sign-in.
  var tsForm = document.getElementById("ts-form");
  var tsScript = null;
  var tsWidget = null;

  function loadTurnstile() {
    if (window.turnstile) return Promise.resolve(window.turnstile);
    if (!tsScript) {
      tsScript = new Promise(function (resolve, reject) {
        var s = document.createElement("script");
        s.src = "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit";
        s.async = true;
        s.onload = function () { resolve(window.turnstile); };
        s.onerror = function () {
          tsScript = null;
          reject(new Error("Couldn't load Cloudflare's challenge. Check the server's connection."));
        };
        document.head.appendChild(s);
      });
    }
    return tsScript;
  }

  // The widget's own failure codes, for the ones an admin can act on.
  function turnstileWidgetError(code) {
    code = String(code || "");
    if (code.indexOf("1101") === 0) return "Cloudflare doesn't recognize that site key.";
    if (code === "110200") return "This address isn't in the widget's hostname list. Add " + location.hostname + " to it in the Cloudflare dashboard.";
    if (code.indexOf("300") === 0 || code.indexOf("600") === 0) return "The challenge failed in this browser (error " + code + "). Try again.";
    return "The challenge failed to load (error " + code + ").";
  }

  function setTurnstileStatus(status) {
    var chip = document.getElementById("ts-chip");
    chip.textContent = status.on ? "On" : "Off";
    chip.classList.toggle("chip--muted", !status.on);
    document.getElementById("ts-status-text").textContent = status.on
      ? (status.source === "environment"
          ? "From the TURNSTILE_SITE_KEY and TURNSTILE_SECRET_KEY environment variables. Keys saved here take over from them."
          : "Sign-in and sign-up show a challenge.")
      : "Sign-in and sign-up have no challenge.";
    document.getElementById("ts-off").hidden = !status.on;
    tsForm.querySelector("#ts-verify .btn-label").textContent =
      status.on ? "Verify and save the keys" : "Verify and turn on";
    var secret = document.getElementById("ts-secret");
    secret.value = "";
    secret.placeholder = status.secret_hint
      ? "Saved, ends in " + status.secret_hint + ". Leave empty to keep it."
      : "From the same widget";
    tsForm.setAttribute("data-has-secret", status.secret_hint ? "1" : "0");
  }

  function clearTurnstileWidget() {
    if (tsWidget !== null && window.turnstile) window.turnstile.remove(tsWidget);
    tsWidget = null;
    document.getElementById("ts-challenge").hidden = true;
  }

  if (tsForm) {
    var tsError = document.getElementById("ts-error");
    var tsVerify = document.getElementById("ts-verify");
    function showTsError(message) {
      tsError.textContent = message;
      tsError.hidden = !message;
    }

    tsForm.addEventListener("submit", function (e) {
      e.preventDefault();
      showTsError("");
      var siteKey = document.getElementById("ts-site").value.trim();
      var secretKey = document.getElementById("ts-secret").value.trim();
      if (!siteKey) { showTsError("Enter the site key."); return; }
      if (!secretKey && tsForm.getAttribute("data-has-secret") !== "1") {
        showTsError("Enter the secret key."); return;
      }
      setBusy(tsVerify, true);
      loadTurnstile().then(function (turnstile) {
        clearTurnstileWidget();
        document.getElementById("ts-challenge").hidden = false;
        tsWidget = turnstile.render("#ts-widget", {
          sitekey: siteKey,
          theme: root.getAttribute("data-theme") === "dark" ? "dark" : "light",
          callback: function (token) {
            api("/admin/turnstile", { site_key: siteKey, secret_key: secretKey, token: token })
              .then(function (data) {
                clearTurnstileWidget();
                setTurnstileStatus(data.status);
                setBusy(tsVerify, false);
                toast("Turnstile is on");
              })
              .catch(function (err) {
                // Remove, not reset: a reset widget passes again by itself
                // and would resubmit the same wrong keys in a loop.
                showTsError(err.message);
                clearTurnstileWidget();
                setBusy(tsVerify, false);
              });
          },
          "error-callback": function (code) {
            showTsError(turnstileWidgetError(code));
            clearTurnstileWidget();
            setBusy(tsVerify, false);
            return true;   // handled: don't let the widget retry on its own
          },
          "expired-callback": function () {
            showTsError("The challenge expired. Press the button again.");
            clearTurnstileWidget();
            setBusy(tsVerify, false);
          }
        });
      }).catch(function (err) {
        showTsError(err.message);
        setBusy(tsVerify, false);
      });
    });

    document.getElementById("ts-off").addEventListener("click", function () {
      showTsError("");
      clearTurnstileWidget();
      api("/admin/turnstile/disable").then(function (data) {
        setTurnstileStatus(data.status);
        toast("Turnstile is off");
      }).catch(toastError);
    });
  }

  /* ————— Menus (the topbar sort, and any .menu) ————— */
  document.querySelectorAll(".menu").forEach(function (menu) {
    var btn = menu.querySelector(".menubtn");
    var pop = menu.querySelector(".menupop");
    if (!btn || !pop) return;
    function set(open) {
      menu.classList.toggle("is-open", open);
      pop.hidden = !open;
      btn.setAttribute("aria-expanded", open ? "true" : "false");
    }
    btn.addEventListener("click", function (e) {
      e.stopPropagation();
      set(pop.hidden);
    });
    document.addEventListener("click", function (e) {
      if (!menu.contains(e.target)) set(false);
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") set(false);
    });
  });

  /* ————— Records ————— */
  function cardFor(id) {
    return recordsRoot && recordsRoot.querySelector('[data-item="' + id + '"]');
  }
  function itemIds() {
    if (!recordsRoot) return [];
    return Array.prototype.map.call(recordsRoot.querySelectorAll("[data-item]"), function (el) {
      return parseInt(el.getAttribute("data-item"), 10);
    });
  }
  function removeCard(id) {
    var el = cardFor(id);
    if (el) el.remove();
  }

  if (recordsRoot) {
    // Delegated: records appended by paging need no binding of their own.
    recordsRoot.addEventListener("click", function (e) {
      if (e.target.closest("a, button")) return;
      var card = e.target.closest("[data-item]");
      if (card) openEntity(parseInt(card.getAttribute("data-item"), 10));
    });
    recordsRoot.addEventListener("keydown", function (e) {
      var card = e.target.closest("[data-item]");
      if (card && e.target === card && (e.key === "Enter" || e.key === " ")) {
        e.preventDefault();
        openEntity(parseInt(card.getAttribute("data-item"), 10));
      }
    });
  }

  // A link to a record (a[data-entity], or /e/<id> inside a document) opens
  // its sheet in place. A modified click keeps the browser's own behavior,
  // so Ctrl-click still opens it in a new tab.
  document.addEventListener("click", function (e) {
    var a = e.target.closest("a[data-entity], .prose a[href^='/e/']");
    if (!a || e.button !== 0 || e.ctrlKey || e.metaKey || e.shiftKey || e.altKey) return;
    var id = parseInt(a.getAttribute("data-entity") || a.getAttribute("href").slice(3), 10);
    if (!id) return;
    e.preventDefault();
    openEntity(id);
  });

  // Anything the server says can be taken back comes with an "undo": the URL
  // and body that take it back.
  function offerUndo(message, undo, after) {
    if (!undo) { if (message) toast(message); return; }
    toast(message, "Undo", function () {
      api(undo.url, undo.body).then(function () {
        if (after) after(); else location.reload();
      }).catch(toastError);
    });
  }

  function closeMenus() {
    document.querySelectorAll(".menu.is-open").forEach(function (menu) {
      menu.classList.remove("is-open");
      var pop = menu.querySelector(".menupop");
      if (pop) pop.hidden = true;
    });
  }

  /* ————— The record form ————— */
  // One dialog for every type: the form inside is the server's, built from
  // the type's field schema (sheet/form.html), fetched each time it opens.
  var entityModal = document.getElementById("entity-modal");
  var formSlot = document.getElementById("entity-form-slot");
  var formSource = null;

  function fetchHTML(url) {
    return fetch(url, { headers: { "Accept": "text/html" } }).then(function (resp) {
      if (resp.ok) return resp.text();
      return resp.json().catch(function () { return {}; }).then(function (data) {
        throw new Error(data.error || "Couldn't load that.");
      });
    }, function () { throw new Error("Can't reach the server."); });
  }

  function loadForm(url) {
    return fetchHTML(url).then(function (html) {
      formSlot.innerHTML = html;
      formSource = url;
      var form = formSlot.querySelector("form");
      document.getElementById("entity-modal-title").textContent = form.getAttribute("data-title");
      return form;
    });
  }

  function openEntityForm(url) {
    if (!entityModal) return;
    loadForm(url).then(function (form) {
      if (!entityModal.open) entityModal.showModal();
      var first = form.querySelector("[autofocus]");
      if (first) first.focus();
    }).catch(toastError);
  }

  function formData(form) {
    var out = {};
    Array.prototype.forEach.call(form.elements, function (el) {
      if (!el.name || el.disabled || el.type === "file" || el.type === "submit") return;
      if (el.closest("[data-section][hidden]")) return;   // hidden by a choice: left as it is
      if (el.type === "radio" && !el.checked) return;       // a choice: the one chosen
      out[el.name] = el.type === "checkbox" ? el.checked : el.value;
    });
    return out;
  }
  function fillForm(form, values) {
    Object.keys(values || {}).forEach(function (name) {
      var el = form.elements[name];
      if (!el || el.type === "file") return;
      if (el.type === "checkbox") el.checked = !!values[name];
      // A choice the form no longer offers (a location the new type can't
      // be in) leaves the form's own.
      else if (el.tagName === "SELECT" && !Array.prototype.some.call(el.options, function (o) { return o.value === String(values[name]); })) return;
      else el.value = values[name];
    });
  }

  // After a save, show the record: its sheet, over a list that has it.
  function goToEntity(id) {
    var params = new URLSearchParams(location.search);
    params.set("open", id);
    params.delete("tab");
    location.assign(location.pathname + "?" + params.toString());
  }

  // A choice that hides form sections, in the form and in an editor's
  // Overview: a server made a tower loses its rack position section.
  // data-hides: "section=value,value" rules, each section hidden while the
  // choice is one of its values (an empty one: none chosen).
  function showSections(select) {
    var root = select.closest("form, [data-autosave]") || document;
    select.getAttribute("data-hides").split(" ").forEach(function (rule) {
      var key = rule.split("=")[0], hide = rule.slice(key.length + 1).split(",").indexOf(select.value) !== -1;
      root.querySelectorAll('[data-section="' + key + '"]').forEach(function (s) { s.hidden = hide; });
    });
  }
  document.addEventListener("change", function (e) {
    if (e.target.matches && e.target.matches("select[data-hides]")) showSections(e.target);
  });

  if (formSlot) {
    // Another type chosen for a record: the form for that type, with what
    // was typed carried over.
    formSlot.addEventListener("change", function (e) {
      var select = e.target.closest("select[data-retype]");
      if (!select) return;
      var form = select.form, values = formData(form);
      delete values.type;
      loadForm("/e/" + form.getAttribute("data-id") + "/form?type=" + encodeURIComponent(select.value)).then(function (fresh) {
        fillForm(fresh, values);
        fresh.querySelectorAll("select[data-hides]").forEach(showSections);
        var again = fresh.querySelector("select[data-retype]");
        if (again) again.focus();
      }).catch(toastError);
    });
    formSlot.addEventListener("submit", function (e) {
      var form = e.target.closest("#entity-form");
      if (!form) return;
      e.preventDefault();
      var errEl = form.querySelector(".form-error");
      var btn = form.querySelector("button[type=submit]");
      var id = form.getAttribute("data-id");
      errEl.hidden = true;
      setBusy(btn, true);
      api(id ? "/api/entities/" + id : "/api/entities", formData(form)).then(function (data) {
        entityModal.close();   // saved: the page that follows shows the record, not the form
        // What the save did beyond what was asked (an address moved), told after the reload.
        if (data.notices && data.notices.length) queueToast(data.notices.join(" "));
        // Edited from its open sheet: reload, and the sheet comes back in
        // place (same tab, same scroll) over the refreshed list.
        if (id && sheet && sheet.open && new URLSearchParams(location.search).get("open") === id) location.reload();
        else goToEntity(data.entity.id);
      }).catch(function (err) {
        errEl.textContent = err.message;
        errEl.hidden = false;
        setBusy(btn, false);
      });
    });
  }

  document.addEventListener("click", function (e) {
    var btn = e.target.closest("[data-new-type]");
    if (!btn) return;
    e.preventDefault();
    closeMenus();
    var params = new URLSearchParams({ type: btn.getAttribute("data-new-type") });
    if (btn.getAttribute("data-new-location")) params.set("location_id", btn.getAttribute("data-new-location"));
    if (btn.getAttribute("data-new-attach")) params.set("attach_to", btn.getAttribute("data-new-attach"));
    // data-new-link="affects:12": the new record is linked to record 12.
    if (btn.getAttribute("data-new-link")) params.set("link", btn.getAttribute("data-new-link"));
    if (btn.getAttribute("data-new-name")) params.set("name", btn.getAttribute("data-new-name"));
    var preset = btn.getAttribute("data-new-fields");
    if (preset) {
      try {
        var values = JSON.parse(preset);
        Object.keys(values).forEach(function (key) { params.set("f." + key, values[key]); });
      } catch (err) { /* a template mistake; open the form without them */ }
    }
    setSidebar(false);
    openEntityForm("/e/form?" + params.toString());
  });

  /* ————— Small behaviors templates ask for with data-* ————— */
  // Module templates use these instead of scripts of their own:
  //   form[data-api="/url"]      submits its fields as JSON (or multipart,
  //                              with enctype) and then does data-then
  //   [data-api-post="/url"]     posts data-body (JSON) and then does data-then
  //   data-then="sheet|reload|remove"  re-render the open sheet, reload the
  //                              page, or remove the closest [data-row]
  //   data-then="go"             go to the page in data-go ("/" if none)
  //   data-then="replace"        put the answer's html in #data-replace
  //   data-done="Message"        the toast, with Undo when the answer has one
  //   data-confirm="Question?"   asks first, in #confirm-modal; data-confirm-text
  //                              explains, data-confirm-go names the button
  //   [data-pick]                chooses a record in the palette; its id goes
  //                              into the form's data-pick-into field (other_id)
  //   [data-fill='{"a": 1}']     sets fields of its form (or data-fill-form)
  //   [data-reveal="/url"]       posts to url and shows its value in the
  //                              element named by data-reveal-into; again hides it
  //   [data-copy="text"]         copies the text; [data-copy-url] posts first
  //                              and copies the answer's value
  //   input[data-autosubmit]     submits its form when it changes
  //   [data-print]               prints the page (a sheet of labels)
  //   .infotip[popovertarget]    opens its help (a native popover) beside it
  //   [data-gallery]             its [data-gallery-item] links open in the
  //                              picture viewer (see "Picture viewer")
  //   [data-zoom]                a diagram's frame: fitted, zoomed with its
  //                              buttons or Ctrl/Cmd and the wheel, dragged
  //   [data-views="key"]         radios that show one [data-view] panel of
  //                              the tab (a list or a diagram), remembered
  //                              in this browser under the key
  //   select[data-go]            goes to the page its chosen option names
  function afterAction(el, data) {
    var then = el.getAttribute("data-then");
    // An answer that says what happened ("12 made, 2 skipped") wins over
    // the element's fixed message.
    var done = (data && typeof data.message === "string" && data.message) || el.getAttribute("data-done");
    if (then === "reload") {
      if (done) queueToast(done);
      location.reload();
    } else if (then === "go") {
      if (done) queueToast(done);
      location.href = el.getAttribute("data-go") || "/";
    } else if (then === "remove") {
      var row = el.closest("[data-row]");
      if (row) row.remove();
      offerUndo(done, data && data.undo);
    } else if (then === "replace") {
      // The answer's html takes the place of what is in data-replace: the
      // next step of the import, its check.
      var target = document.getElementById(el.getAttribute("data-replace"));
      if (target && data && typeof data.html === "string") target.innerHTML = data.html;
      if (done) toast(done);
    } else if (then === "sheet") {
      refreshSheet();
      if (data && data.undo) offerUndo(done, data.undo, refreshSheet);
    } else if (done) {
      offerUndo(done, data && data.undo);
    }
  }

  function submitApiForm(form) {
    var errEl = form.querySelector(".form-error");
    if (errEl) errEl.hidden = true;
    var url = form.getAttribute("data-api");
    var sending = form.getAttribute("enctype") === "multipart/form-data"
      ? request(url, { method: "POST", headers: { "X-CSRF": CSRF, "Accept": "application/json" }, body: new FormData(form) })
      : api(url, formData(form));
    form.classList.add("is-busy");
    sending.then(function (data) {
      form.classList.remove("is-busy");
      afterAction(form, data);
    }).catch(function (err) {
      form.classList.remove("is-busy");
      if (errEl) { errEl.textContent = err.message; errEl.hidden = false; }
      else toastError(err);
    });
  }

  document.addEventListener("submit", function (e) {
    var form = e.target.closest("form[data-api]");
    if (!form) return;
    e.preventDefault();
    submitApiForm(form);
  });
  // A tree of places (the site setup guide's Buildings and rooms): each
  // is added where its + button is, moved by dragging its handle onto
  // another (or with → and ←), and deleted, every change saved at once
  // through the records API; then the tree is drawn again from the server.
  function treeOf(el) { return el.closest("[data-tree]"); }
  function treeNode(el) { return el && el.closest(".tree-node"); }
  function treeAccepts(node, type) {
    return (node.getAttribute("data-accepts") || "").split(" ").indexOf(type) !== -1;
  }
  function redrawTree(tree, then) {
    return fetchHTML(tree.getAttribute("data-tree-url")).then(function (html) {
      var holder = document.createElement("div");
      holder.innerHTML = html;
      var fresh = holder.querySelector("[data-tree]");
      tree.replaceWith(fresh);
      if (then) then(fresh);
      return fresh;
    });
  }
  function treeFind(tree, id) { return tree.querySelector('.tree-node[data-node="' + id + '"]'); }
  function openTreeAdd(node, type, label) {
    var list = node.querySelector(":scope > .tree-children");
    var open = list.querySelector(":scope > .tree-adding");
    if (open) open.remove();
    var li = document.createElement("li");
    li.className = "tree-adding";
    var form = document.createElement("form");
    var input = document.createElement("input");
    input.type = "text";
    input.maxLength = 200;
    input.autocomplete = "off";
    input.placeholder = label + " name";
    input.setAttribute("aria-label", "Name of the new " + label.toLowerCase() + " in " + node.getAttribute("data-name"));
    var hint = document.createElement("span");
    hint.className = "hint";
    hint.textContent = "Enter adds it, and the next one can be typed straight away. Esc stops.";
    form.appendChild(input);
    form.appendChild(hint);
    li.appendChild(form);
    list.appendChild(li);
    input.focus();
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      var name = input.value.trim();
      if (!name) return;
      input.disabled = true;
      api("/api/entities", { type: type, name: name, location_id: node.getAttribute("data-node") }).then(function () {
        var id = node.getAttribute("data-node");
        redrawTree(treeOf(node), function (fresh) {
          var again = treeFind(fresh, id);
          if (again) openTreeAdd(again, type, label);
        });
      }).catch(function (err) { input.disabled = false; input.focus(); toastError(err); });
    });
    input.addEventListener("keydown", function (e) {
      if (e.key === "Escape") { e.preventDefault(); li.remove(); }
    });
  }
  function moveTreeNode(node, target) {
    var id = node.getAttribute("data-node"), tree = treeOf(node);
    api("/api/entities/" + id, { location_id: target.getAttribute("data-node") }).then(function () {
      redrawTree(tree, function (fresh) {
        var moved = treeFind(fresh, id), handle = moved && moved.querySelector(".tree-handle");
        if (handle) handle.focus({ preventScroll: true });
      });
    }).catch(toastError);
  }
  // Where a place can go: a place that takes its kind, not itself or
  // anything inside it, and not where it already is.
  function treeDropOk(node, target) {
    if (!target || target === node || node.contains(target)) return false;
    if (treeNode(node.parentNode) === target) return false;
    return treeAccepts(target, node.getAttribute("data-type"));
  }
  document.addEventListener("click", function (e) {
    var add = e.target.closest("[data-tree-add]");
    if (add && treeOf(add)) {
      openTreeAdd(treeNode(add), add.getAttribute("data-tree-add"), add.getAttribute("data-tree-label"));
      return;
    }
    var del = e.target.closest("[data-tree-delete]");
    if (!del || !treeOf(del)) return;
    var node = treeNode(del), tree = treeOf(del);
    // A building goes with the rooms in it; the dialog says how many, and
    // what else was placed in them.
    var inside = del.getAttribute("data-inside");     // "2 rooms", or ""
    var holds = parseInt(del.getAttribute("data-holds"), 10) || 0;
    var name = node.getAttribute("data-name");
    del.setAttribute("data-confirm", "Delete " + name + (inside ? " and the " + inside + " in it?" : "?"));
    del.setAttribute("data-confirm-text", (inside ? "They go" : "It goes") + " to Recently deleted, where " +
      (inside ? "they" : "it") + " can be restored until purged, and Undo brings " + (inside ? "them all" : "it") +
      " back." + (holds ? " " + holds + (holds === 1 ? " other record is" : " other records are") + " placed in " +
      (inside ? "them" : "it") + ", and will show no location unless " + (inside ? "they are" : "it is") + " restored." : ""));
    del.setAttribute("data-confirm-go", "Delete");
    confirmFirst(del, function () {
      api(del.getAttribute("data-tree-delete")).then(function (data) {
        redrawTree(tree).then(function () {
          offerUndo("Deleted", data.undo, function () {
            var now = document.querySelector("[data-tree]");
            if (now) redrawTree(now);
          });
        });
      }).catch(toastError);
    });
  });
  var treeDrag = null;
  document.addEventListener("pointerdown", function (e) {
    var handle = e.target.closest(".tree-handle");
    if (!handle || !treeOf(handle) || e.button !== 0) return;
    e.preventDefault();
    handle.setPointerCapture(e.pointerId);
    var node = treeNode(handle), ghost = document.createElement("div");
    ghost.className = "tree-ghost";
    ghost.textContent = node.getAttribute("data-name");
    document.body.appendChild(ghost);
    treeDrag = { node: node, handle: handle, ghost: ghost, target: null };
    node.classList.add("is-dragging");
    document.body.classList.add("is-sorting");
  });
  document.addEventListener("pointermove", function (e) {
    if (!treeDrag) return;
    treeDrag.ghost.style.transform = "translate(" + (e.clientX + 14) + "px, " + (e.clientY + 10) + "px)";
    var under = document.elementFromPoint(e.clientX, e.clientY);
    var row = under && under.closest(".tree-row");
    var target = row && treeOf(row) === treeOf(treeDrag.node) ? treeNode(row) : null;
    if (!treeDropOk(treeDrag.node, target)) target = null;
    if (target !== treeDrag.target) {
      if (treeDrag.target) treeDrag.target.classList.remove("is-drop");
      if (target) target.classList.add("is-drop");
      treeDrag.target = target;
    }
  });
  function endTreeDrag() {
    if (!treeDrag) return;
    var d = treeDrag;
    treeDrag = null;
    d.ghost.remove();
    d.node.classList.remove("is-dragging");
    document.body.classList.remove("is-sorting");
    if (d.target) { d.target.classList.remove("is-drop"); moveTreeNode(d.node, d.target); }
    else d.handle.focus({ preventScroll: true });
  }
  document.addEventListener("pointerup", endTreeDrag);
  document.addEventListener("pointercancel", endTreeDrag);
  document.addEventListener("keydown", function (e) {
    var handle = e.target.closest && e.target.closest(".tree-handle");
    if (!handle || !treeOf(handle) || (e.key !== "ArrowRight" && e.key !== "ArrowLeft")) return;
    e.preventDefault();
    var node = treeNode(handle), parent = treeNode(node.parentNode), target;
    if (e.key === "ArrowRight") {
      // Into the place just above it, at its own level.
      var prev = node.previousElementSibling;
      while (prev && !prev.matches(".tree-node")) prev = prev.previousElementSibling;
      target = prev;
    } else {
      target = parent && treeNode(parent.parentNode);
    }
    if (treeDropOk(node, target)) moveTreeNode(node, target);
    else toast(e.key === "ArrowRight" ? "There is no place above it that can hold it." : "It can't go up another level.");
  });

  // A speed ([data-speed]): a number and Mb/s or Gb/s. The named, hidden
  // input holds megabits, and a change to either reaches whoever saves it
  // (the form, the Overview, a guide row) as a change of that input.
  function speedSync(box) {
    var number = box.querySelector('input[type="number"]'), unit = box.querySelector("select");
    var out = box.querySelector("input[name]"), raw = number.value.trim();
    var value = raw === "" ? "" : String(Math.round(parseFloat(raw) * (unit.value === "g" ? 1000 : 1)));
    if (raw !== "" && isNaN(parseFloat(raw))) value = raw;       // the server says what's wrong
    out.value = value;
  }
  document.addEventListener("input", function (e) {
    var box = e.target.closest && e.target.closest("[data-speed]");
    if (box && e.target !== box.querySelector("input[name]")) speedSync(box);
  });
  document.addEventListener("change", function (e) {
    var box = e.target.closest && e.target.closest("[data-speed]");
    if (!box || e.target === box.querySelector("input[name]")) return;
    // The input the saving listens to, told of the change once it is made:
    // the Overview compares it with what it was drawn with.
    speedSync(box);
    box.querySelector("input[name]").dispatchEvent(new Event("change", { bubbles: true }));
  });

  // A field shown only while another has a value ([data-when] names that
  // one, [data-when-is] the value: "1" for a switch that is on), in a form,
  // a guide row or an editor's Overview. One that follows a field hidden
  // itself is hidden too; the server drew them as they start.
  function applyWhen(scope) {
    scope.querySelectorAll("[data-when]").forEach(function (el) {
      var name = CSS.escape(el.getAttribute("data-when"));
      var ctl = scope.querySelector('[name="' + name + '"]:checked, [name="' + name + '"]:not([type="radio"])');
      if (!ctl) return;
      var holder = ctl.closest("[data-when]");
      var value = ctl.type === "checkbox" ? (ctl.checked ? "1" : "0") : ctl.value;
      el.hidden = !!(holder && holder.hidden) || el.getAttribute("data-when-is").split(" ").indexOf(value) === -1;
    });
  }
  // A label that changes with another field ([data-relabel]): a server's IP
  // address is its BMC's once it runs a hypervisor.
  function applyRelabel(scope) {
    scope.querySelectorAll("[data-relabel]").forEach(function (label) {
      var ctl = scope.querySelector('[name="' + CSS.escape(label.getAttribute("data-relabel")) + '"]');
      if (!ctl) return;
      var value = ctl.type === "checkbox" ? (ctl.checked ? "1" : "0") : ctl.value;
      label.textContent = label.getAttribute(value === label.getAttribute("data-relabel-is") ? "data-relabel-to" : "data-relabel-from");
    });
  }
  document.addEventListener("change", function (e) {
    var el = e.target;
    if (!el.name || !el.closest) return;
    var scope = el.closest("[data-row], [data-row-new], form, [data-autosave]");
    if (scope && scope.querySelector("[data-when]")) applyWhen(scope);
    if (scope && scope.querySelector("[data-relabel]")) applyRelabel(scope);
  });
  // A box whose unticking deletes something ([data-confirm-off]: a server's
  // hypervisor) asks first; ticking it doesn't.
  document.addEventListener("click", function (e) {
    var box = e.target.closest && e.target.closest("input[type=checkbox][data-confirm-off]");
    if (!box || box.checked) return;     // during a click it is already as it will be: ticked is fine
    e.preventDefault();                  // unticked: it stays ticked until the answer
    // What it would delete can't be deleted yet (a hypervisor with VMs on it): say why instead.
    if (box.hasAttribute("data-confirm-blocked")) {
      askFirst(box.getAttribute("data-confirm-blocked"), box.getAttribute("data-confirm-blocked-text"));
      return;
    }
    askFirst(box.getAttribute("data-confirm-off"), box.getAttribute("data-confirm-text"), "Delete", function () {
      box.checked = false;
      box.dispatchEvent(new Event("change", { bubbles: true }));
    });
  });

  // A value typed in parts ([data-join]): a subnet's address and mask
  // ("/"), a range's first and last address ("-"). The parts, joined, go in
  // the named, hidden input, and a change reaches whoever saves it as a
  // change of that input; with nothing typed, the value is empty.
  function joinParts(box) {
    var parts = Array.prototype.slice.call(box.querySelectorAll("[data-part]"));
    var typed = parts.filter(function (p) { return p.tagName !== "SELECT"; });
    var empty = typed.every(function (p) { return !p.value.trim(); });
    box.querySelector("input[name]").value = empty ? "" :
      parts.map(function (p) { return p.value.trim(); }).join(box.getAttribute("data-join"));
  }
  document.addEventListener("input", function (e) {
    var box = e.target.closest && e.target.closest("[data-join]");
    if (box && e.target.hasAttribute("data-part")) joinParts(box);
  });
  document.addEventListener("change", function (e) {
    var box = e.target.closest && e.target.closest("[data-join]");
    if (!box || !e.target.hasAttribute("data-part")) return;
    joinParts(box);
    box.querySelector("input[name]").dispatchEvent(new Event("change", { bubbles: true }));
  });

  // A choice of several ([data-multi]): the values of the boxes ticked,
  // joined by commas, go in the named, hidden input, and a change reaches
  // whoever saves it as a change of that input.
  document.addEventListener("change", function (e) {
    var box = e.target.closest && e.target.closest("[data-multi]");
    if (!box || !e.target.hasAttribute("data-multi-item")) return;
    var input = box.querySelector("input[name]");
    input.value = Array.prototype.filter.call(box.querySelectorAll("[data-multi-item]"), function (c) {
      return c.checked;
    }).map(function (c) { return c.value; }).join(",");
    input.dispatchEvent(new Event("change", { bubbles: true }));
  });

  // A text field that offers a catalog's names as it is typed in
  // ([data-suggest]: operating systems, core/catalogs.py): the names that
  // hold every word typed, under their groups, picked with a click or with
  // the arrow keys and Enter. The last choice keeps what was typed, a custom
  // name. A pick is a change of the field, saved as any other. One list, put
  // under whichever field is open; each catalog is fetched once.
  var catalogs = {}, suggestPop = null, suggestFor = null, suggestItems = [], suggestAt = -1;
  function catalogOf(key) {
    if (!catalogs[key]) {
      catalogs[key] = get("/api/catalogs/" + encodeURIComponent(key)).then(function (data) { return data.groups || []; });
      catalogs[key].catch(function () { delete catalogs[key]; });
    }
    return catalogs[key];
  }
  function suggestClose() {
    if (!suggestPop || suggestPop.hidden) return;
    suggestPop.hidden = true;
    if (suggestFor) {
      suggestFor.setAttribute("aria-expanded", "false");
      suggestFor.removeAttribute("aria-activedescendant");
    }
    suggestFor = null;
  }
  function suggestMark(n) {
    suggestAt = n;
    suggestItems.forEach(function (el, i) { el.classList.toggle("is-current", i === n); });
    if (n >= 0 && suggestItems[n]) {
      suggestFor.setAttribute("aria-activedescendant", suggestItems[n].id);
      suggestItems[n].scrollIntoView({ block: "nearest" });
    } else if (suggestFor) suggestFor.removeAttribute("aria-activedescendant");
  }
  function suggestOpen(input) {
    catalogOf(input.getAttribute("data-suggest")).then(function (groups) {
      if (document.activeElement !== input) return;
      if (!suggestPop) {
        suggestPop = document.createElement("div");
        suggestPop.className = "menupop menupop--scroll suggest-pop";
        suggestPop.id = "suggest-pop";
        suggestPop.setAttribute("role", "listbox");
        // Picking keeps the focus in the field.
        suggestPop.addEventListener("mousedown", function (e) { e.preventDefault(); });
        suggestPop.addEventListener("click", function (e) {
          e.preventDefault();          // inside the field's label: not a click on the field too
          var opt = e.target.closest("[data-pick-value]");
          if (opt) suggestPick(opt);
        });
      }
      var typed = input.value.trim(), all = [];
      groups.forEach(function (g) { g.items.forEach(function (name) { all.push(name); }); });
      // A name picked before shows the whole list again, to choose another.
      var exact = all.some(function (name) { return name.toLowerCase() === typed.toLowerCase(); });
      var words = exact ? [] : typed.toLowerCase().split(/\s+/).filter(Boolean);
      suggestPop.textContent = "";
      suggestItems = [];
      function option(text, value, custom) {
        var el = document.createElement("div");
        el.className = "menuopt" + (custom ? " suggest-custom" : "");
        el.id = "suggest-" + suggestItems.length;
        el.setAttribute("role", "option");
        el.setAttribute("data-pick-value", value);
        if (custom) el.setAttribute("data-custom", "");
        el.textContent = text;
        suggestPop.appendChild(el);
        suggestItems.push(el);
      }
      groups.forEach(function (g) {
        var found = g.items.filter(function (name) {
          var hay = (g.label + " " + name).toLowerCase();
          return words.every(function (w) { return hay.indexOf(w) !== -1; });
        });
        if (!found.length) return;
        var head = document.createElement("p");
        head.className = "menupop-head";
        head.textContent = g.label;
        suggestPop.appendChild(head);
        found.forEach(function (name) { option(name, name); });
      });
      if (!suggestItems.length) {
        var none = document.createElement("p");
        none.className = "menupop-head";
        none.textContent = "No known name matches";
        suggestPop.appendChild(none);
      }
      option(typed && !exact ? "Use “" + typed + "” as typed" : "Custom: type the name", typed, true);
      var holder = input.parentNode;
      holder.classList.add("has-suggest");
      if (suggestPop.parentNode !== holder) input.insertAdjacentElement("afterend", suggestPop);
      suggestFor = input;
      input.setAttribute("aria-controls", "suggest-pop");
      input.setAttribute("aria-expanded", "true");
      suggestPop.hidden = false;
      suggestMark(-1);
    }).catch(function () { /* no list: the field is typed in as any other */ });
  }
  function suggestPick(opt) {
    var input = suggestFor;
    if (!input) return;
    if (!opt.hasAttribute("data-custom")) {
      input.value = opt.getAttribute("data-pick-value");
      input.dispatchEvent(new Event("change", { bubbles: true }));
    }
    suggestClose();
    input.focus();
  }
  document.addEventListener("input", function (e) {
    if (e.target.matches && e.target.matches("input[data-suggest]")) suggestOpen(e.target);
  });
  document.addEventListener("click", function (e) {
    var input = e.target.closest && e.target.closest("input[data-suggest]");
    if (!input) return;
    if (suggestFor === input) suggestClose();
    else suggestOpen(input);
  });
  document.addEventListener("focusout", function (e) {
    if (suggestFor && e.target === suggestFor) suggestClose();
  });
  // Before the guide's Enter (add the row) and a dialog's Escape (close it).
  document.addEventListener("keydown", function (e) {
    var input = e.target;
    if (!input.matches || !input.matches("input[data-suggest]")) return;
    var open = suggestFor === input && suggestPop && !suggestPop.hidden;
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      if (!open) { suggestOpen(input); return; }
      var n = suggestAt + (e.key === "ArrowDown" ? 1 : -1);
      suggestMark(Math.max(0, Math.min(suggestItems.length - 1, n)));
    } else if (e.key === "Enter" && open && suggestAt >= 0) {
      e.preventDefault();
      e.stopPropagation();
      suggestPick(suggestItems[suggestAt]);
    } else if (e.key === "Escape" && open) {
      e.preventDefault();
      e.stopPropagation();
      suggestClose();
    }
  }, true);

  // A subnet that fills in others ([data-prefills]: a gateway, a DHCP
  // range): once it is typed, the first host becomes the gateway and the
  // upper half of it the DHCP range, leaving the lower half for fixed
  // addresses. Only a field left empty, or filled in this way, is filled;
  // one typed in is left alone. IPv4 only.
  function ipv4(text) {
    var m = /^(\d+)\.(\d+)\.(\d+)\.(\d+)$/.exec(text);
    if (!m) return null;
    var n = 0;
    for (var i = 1; i <= 4; i++) { if (+m[i] > 255) return null; n = n * 256 + +m[i]; }
    return n;
  }
  function ipv4Text(n) { return [n >>> 24 & 255, n >>> 16 & 255, n >>> 8 & 255, n & 255].join("."); }
  function prefill(box) {
    var cidr = box.querySelector("input[name]").value.split("/"), start = ipv4(cidr[0]), prefix = +cidr[1];
    if (start === null || !(prefix >= 8 && prefix <= 30)) return;
    var size = Math.pow(2, 32 - prefix), net = start - start % size, first = net + 1, last = net + size - 2;
    var scope = box.closest("[data-row], [data-row-new], form, [data-autosave]") || document;
    box.getAttribute("data-prefills").split(" ").forEach(function (name) {
      var el = scope.querySelector('[name="' + CSS.escape(name) + '"]');
      if (!el || el.disabled || (el.value && !el.hasAttribute("data-prefilled"))) return;
      var range = el.closest('[data-join="-"]'), value;
      if (range) {
        if (size < 16) return;                       // too small to share
        var from = net + size / 2, parts = range.querySelectorAll("[data-part]");
        parts[0].value = ipv4Text(from);
        parts[1].value = ipv4Text(last);
        value = ipv4Text(from) + "-" + ipv4Text(last);
      } else {
        value = ipv4Text(first);
      }
      if (el.value === value) return;
      el.value = value;
      el.setAttribute("data-prefilled", "");
      el.dispatchEvent(new Event("change", { bubbles: true }));   // a saved row saves it
    });
  }
  document.addEventListener("change", function (e) {
    var box = e.target.closest && e.target.closest("[data-prefills]");
    if (box && e.target === box.querySelector("input[name]")) prefill(box);
  });
  // Typed in by hand: no longer filled in.
  document.addEventListener("input", function (e) {
    var el = e.target, range = el.closest && el.closest('[data-join="-"]');
    var target = range ? range.querySelector("input[name]") : el;
    if (target && target.hasAttribute && target.hasAttribute("data-prefilled")) target.removeAttribute("data-prefilled");
  });

  // A choice that is a page: the site setup guide's choice of site.
  document.addEventListener("change", function (e) {
    var select = e.target.closest && e.target.closest("select[data-go]");
    if (select && select.value) location.href = select.value;
  });

  // What a save did beyond what was asked (an address moved from a server
  // to its hypervisor), as the server says it.
  function showNotices(data) {
    if (data && data.notices && data.notices.length) toast(data.notices.join(" "));
  }

  // A step of rows in the site setup guide ([data-rows]): each row a record,
  // each field saved as it changes; the blank row at the end added only when
  // asked (Enter, its Add button, or Continue with a name typed in it); a row
  // deleted after asking, with Undo. Adding or deleting draws the rows again.
  var rowAdding = null;          // the add on its way, so Continue waits for it
  function rowsOf(el) { return el.closest("[data-rows]"); }
  function rowValue(el) { return el.type === "checkbox" ? el.checked : el.value; }
  function rowError(row, message) {
    var p = row.querySelector(".guide-row-error");
    if (p) { p.textContent = message || ""; p.hidden = !message; }
  }
  // A saved row folded to one line ([data-row-toggle]): its name and a
  // summary of what it holds, written from its fields; open to change it.
  // Moving into another row folds an open one again, so the list stays tidy.
  var openRows = {};              // row id -> open, kept across a redraw
  function fieldText(item) {
    if (item.hidden || item.classList.contains("guide-break")) return "";
    var locked = item.querySelector(".guide-locked-text");
    if (locked) return locked.textContent.trim();
    var speed = item.querySelector("[data-speed]");
    if (speed) {
      var n = speed.querySelector('input[type="number"]').value.trim(), unit = speed.querySelector("select");
      return n ? n + " " + unit.options[unit.selectedIndex].text : "";
    }
    var joined = item.querySelector("[data-join]");
    if (joined) {
      var v = joined.querySelector("input[name]").value;
      return joined.getAttribute("data-join") === "-" ? v.replace("-", " to ") : v;
    }
    var multi = item.querySelector("[data-multi]");
    if (multi) {
      return Array.prototype.filter.call(multi.querySelectorAll("[data-multi-item]"), function (c) {
        return c.checked;
      }).map(function (c) { return c.parentNode.textContent.trim(); }).join(", ");
    }
    var chosen = item.querySelector('input[type="radio"]:checked');
    if (chosen) return chosen.parentNode.textContent.trim();
    var box = item.querySelector('input[type="checkbox"]');
    if (box) return box.checked ? item.textContent.trim() : "";
    var select = item.querySelector("select");
    if (select) return select.value ? select.options[select.selectedIndex].text : "";
    var input = item.querySelector("input[name]");
    if (!input || input.name === "name" || input.disabled || !input.value.trim()) return "";
    // A number with its unit: 1500 VA, 25 min.
    return input.value.trim() + (input.getAttribute("data-unit") ? " " + input.getAttribute("data-unit") : "");
  }
  function summarizeRow(row) {
    var body = row.querySelector(".guide-row-body"), out = row.querySelector("[data-row-summary]");
    if (!body || !out) return;
    out.textContent = Array.prototype.map.call(body.children, fieldText).filter(Boolean).join(" · ");
  }
  function setRowOpen(row, open) {
    row.classList.toggle("is-collapsed", !open);
    var toggle = row.querySelector("[data-row-toggle]");
    if (toggle) toggle.setAttribute("aria-expanded", open ? "true" : "false");
    openRows[row.getAttribute("data-row-id")] = open;
    if (!open) summarizeRow(row);
  }
  function initRows(box) {
    box.querySelectorAll("[data-row]").forEach(function (row) {
      summarizeRow(row);
      if (openRows[row.getAttribute("data-row-id")]) setRowOpen(row, true);
    });
  }
  document.querySelectorAll("[data-rows]").forEach(initRows);
  document.addEventListener("click", function (e) {
    var toggle = e.target.closest && e.target.closest("[data-row-toggle]");
    if (!toggle) return;
    var row = toggle.closest("[data-row]");
    setRowOpen(row, row.classList.contains("is-collapsed"));
  });
  document.addEventListener("focusin", function (e) {
    var here = e.target.closest && e.target.closest("[data-row], [data-row-new]");
    var box = here && rowsOf(here);
    if (!box) return;
    box.querySelectorAll("[data-row]:not(.is-collapsed)").forEach(function (row) {
      if (row !== here && !row.contains(e.target)) setRowOpen(row, false);
    });
  });

  function redrawRows(box, then) {
    return fetchHTML(box.getAttribute("data-rows-url")).then(function (html) {
      var holder = document.createElement("div");
      holder.innerHTML = html;
      var fresh = holder.querySelector("[data-rows]");
      box.replaceWith(fresh);
      initRows(fresh);
      fitDiagrams(fresh);   // a step's diagram below its rows (the cables')
      if (then) then(fresh);
      return fresh;
    });
  }
  function focusNewRow(box) {
    var row = box.querySelector("[data-row-new]");
    var first = row && (row.querySelector("input[type=text]") || row.querySelector("input, select"));
    if (first) first.focus();
  }
  // Worth adding: a name, or in a row with none (a cable), anything chosen.
  function newRowFilled(row) {
    var name = row.querySelector('[name="name"]');
    if (name) return !!name.value.trim();
    return Array.prototype.some.call(row.querySelectorAll("select, input[type=text]"), function (el) {
      return !!el.value.trim();
    });
  }
  // Once only: a row being added (or gone from the page, drawn again) is
  // left alone, and the add is done only when the rows are drawn again, so
  // the focus leaving the old row doesn't add it a second time.
  // Added on the step itself (Enter, Add): a new site's step comes back
  // about the new site.
  function addRowHere(row) {
    return addRow(row).then(function (done) { if (done && done.go) location.href = done.go; });
  }
  // Anything typed into the blank row: a box that differs from how it was
  // drawn (a number it starts with, such as a rack's 42 units, doesn't count).
  function newRowTouched(row) {
    return Array.prototype.some.call(row.querySelectorAll('input[type="text"], input[type="number"]'), function (el) {
      return el.value.trim() !== el.defaultValue.trim();
    });
  }
  // ``force``: added whatever it holds, for the server to say what is
  // missing (a name) rather than lose what was typed.
  function addRow(row, force) {
    if (rowAdding) return rowAdding;
    if (!row.isConnected || row.hasAttribute("data-adding") || !(force || newRowFilled(row))) return Promise.resolve(true);
    var box = rowsOf(row), values = {};
    row.querySelectorAll("[name]").forEach(function (el) {
      if (el.type !== "radio" || el.checked) values[el.name] = rowValue(el);
    });
    row.setAttribute("data-adding", "");
    rowError(row, null);
    row.classList.add("is-saving");
    rowAdding = api(box.getAttribute("data-create"), { values: values }).then(function (data) {
      showNotices(data);
      // The site's own step: where to go next, about the new site.
      if (data && data.go) { rowAdding = null; return { go: data.go }; }
      return redrawRows(box, focusNewRow).then(function () { rowAdding = null; return true; },
                                               function () { rowAdding = null; return true; });
    }, function (err) {
      rowAdding = null;
      row.removeAttribute("data-adding");
      row.classList.remove("is-saving");
      rowError(row, err.message);
      return false;
    });
    return rowAdding;
  }
  // One save after another, so a check across fields (a gateway inside the
  // address's network) sees the ones saved just before it.
  var rowSaves = Promise.resolve();
  document.addEventListener("change", function (e) {
    var el = e.target, row = el.closest && el.closest("[data-row]");
    if (!row || !rowsOf(row) || !el.name) return;
    rowError(row, null);
    el.removeAttribute("aria-invalid");
    row.classList.add("is-saving");
    var body = { name: el.name, value: rowValue(el) };
    var saving = rowSaves.then(function () { return api(row.getAttribute("data-update"), body); });
    rowSaves = saving.catch(function () {});
    saving.then(function (data) {
      row.classList.remove("is-saving");
      showNotices(data);
      // What was kept, as the server wrote it, unless the field is being typed in.
      if (data && data.value !== undefined && data.value !== null && el.type === "text" && document.activeElement !== el) {
        el.value = data.value;
      }
      if (el.name === "name") {
        row.setAttribute("data-name", el.value.trim());
        var title = row.querySelector("[data-row-title]");
        if (title) title.textContent = el.value.trim();
      }
      // Another kind can have other fields (a printer has no Used by); in
      // rows that aren't records (cables, [data-redraw]), another choice
      // changes what the others offer, and the diagram below them.
      if (el.name === "_kind" || (el.tagName === "SELECT" && rowsOf(row).hasAttribute("data-redraw"))) {
        redrawRows(rowsOf(row));
      }
    }, function (err) {
      row.classList.remove("is-saving");
      el.setAttribute("aria-invalid", "true");
      rowError(row, err.message);
    });
  });
  document.addEventListener("keydown", function (e) {
    var el = e.target;
    if (e.key !== "Enter" || !el.closest || el.tagName !== "INPUT" || el.type === "checkbox") return;
    var fresh = el.closest("[data-row-new]"), saved = el.closest("[data-row]");
    if (fresh && rowsOf(fresh)) { e.preventDefault(); addRowHere(fresh); }
    else if (saved && rowsOf(saved)) { e.preventDefault(); el.blur(); }
  });
  // A row's form is never sent: Enter adds the blank row, and a field saves itself.
  document.addEventListener("submit", function (e) {
    var form = e.target.closest && e.target.closest("form[data-row-form]");
    if (!form) return;
    e.preventDefault();
    var fresh = form.querySelector("[data-row-new]");
    if (fresh) addRowHere(fresh);
  });
  document.addEventListener("click", function (e) {
    var add = e.target.closest("[data-row-add]");
    if (add && rowsOf(add)) { addRowHere(add.closest("[data-row-new]")); return; }
    // Leaving the step (Continue, Back, another step, Exit setup) with
    // something typed in the blank row adds it first; if it can't be added,
    // the row says why and the page stays.
    var go = e.target.closest("a[href]");
    if (go && !go.closest("[data-rows]") && !go.target && !(e.ctrlKey || e.metaKey || e.shiftKey || e.altKey)) {
      var pending = document.querySelector("[data-rows] [data-row-new]");
      if (!pending || !newRowTouched(pending)) return;
      e.preventDefault();
      addRow(pending, true).then(function (done) {
        if (!done) {
          pending.scrollIntoView({ block: "center", behavior: prefersReducedMotion() ? "auto" : "smooth" });
          return;
        }
        // A new site: the next step, about it.
        var next = new URL(go.href, location.href), site = done.go && new URL(done.go, location.href).searchParams.get("site");
        if (site) next.searchParams.set("site", site);
        location.href = next.toString();
      });
      return;
    }
    var del = e.target.closest("[data-row-delete]");
    if (!del || !rowsOf(del)) return;
    var row = del.closest("[data-row]"), box = rowsOf(del);
    del.setAttribute("data-confirm", "Delete " + row.getAttribute("data-name") + "?");
    del.setAttribute("data-confirm-text", "It goes to Recently deleted, where it can be restored until purged, and Undo brings it back.");
    del.setAttribute("data-confirm-go", "Delete");
    confirmFirst(del, function () {
      api(row.getAttribute("data-delete")).then(function (data) {
        redrawRows(box).then(function () {
          offerUndo("Deleted", data.undo, function () {
            var now = document.querySelector("[data-rows]");
            if (now) redrawRows(now);
          });
        });
      }).catch(toastError);
    });
  });

  document.addEventListener("change", function (e) {
    var input = e.target.closest("input[data-autosubmit]");
    if (input && input.form && input.form.hasAttribute("data-api")) submitApiForm(input.form);
  });
  // Files dropped on a .dropzone go in through its file input.
  ["dragenter", "dragover"].forEach(function (type) {
    document.addEventListener(type, function (e) {
      var zone = e.target.closest && e.target.closest(".dropzone");
      if (!zone) return;
      e.preventDefault();
      zone.classList.add("is-over");
    });
  });
  document.addEventListener("dragleave", function (e) {
    var zone = e.target.closest && e.target.closest(".dropzone");
    if (zone && !zone.contains(e.relatedTarget)) zone.classList.remove("is-over");
  });
  document.addEventListener("drop", function (e) {
    var zone = e.target.closest && e.target.closest(".dropzone");
    if (!zone) return;
    e.preventDefault();
    zone.classList.remove("is-over");
    var input = zone.querySelector("input[type=file]");
    if (input && e.dataTransfer.files.length) {
      input.files = e.dataTransfer.files;
      submitApiForm(zone);
    }
  });

  // [data-zoom]: a diagram drawn on the server, in a frame that opens with all
  // of it showing (never larger than drawn). −, Fit and + zoom it, as do
  // Ctrl/Cmd and the wheel (a trackpad's pinch), about the pointer; zoomed
  // in, it scrolls, and a mouse drags it around.
  var ZOOM_STEP = 1.25, ZOOM_MAX = 3;
  function zoomParts(frame) {
    var box = frame.querySelector(".diagram-scroll"), svg = box && box.querySelector("svg.diagram");
    return svg ? { box: box, svg: svg, natural: svg.viewBox.baseVal.width } : null;
  }
  function fitScale(p) { return Math.min(1, (p.box.clientWidth - 2) / p.natural); }
  function setZoom(frame, scale, focus) {
    var p = zoomParts(frame);
    if (!p || !p.box.clientWidth) return;
    var fit = fitScale(p);
    scale = Math.max(fit, Math.min(ZOOM_MAX, scale));
    var rect = p.box.getBoundingClientRect();
    var fx = focus ? focus.x - rect.left : p.box.clientWidth / 2;
    var fy = focus ? focus.y - rect.top : p.box.clientHeight / 2;
    var was = p.svg.getBoundingClientRect().width / p.natural || fit;
    var px = (p.box.scrollLeft + fx) / was, py = (p.box.scrollTop + fy) / was;
    p.svg.classList.remove("diagram--fit");
    p.svg.style.width = (p.natural * scale) + "px";
    p.svg.style.height = "auto";
    frame.classList.toggle("is-zoomed", scale > fit + 0.001);
    frame.setAttribute("data-scale", scale);
    var out = frame.querySelector("[data-zoom-by='-1']"), inn = frame.querySelector("[data-zoom-by='1']");
    if (out) out.disabled = scale <= fit + 0.001;
    if (inn) inn.disabled = scale >= ZOOM_MAX - 0.001;
    // Keep the point under the pointer (or the middle) where it was.
    p.box.scrollLeft = px * scale - fx;
    p.box.scrollTop = py * scale - fy;
  }
  function fitDiagrams(root) {
    root.querySelectorAll("[data-zoom]").forEach(function (frame) {
      if (frame.offsetParent !== null && !frame.classList.contains("is-zoomed")) setZoom(frame, 0);
    });
  }
  document.addEventListener("click", function (e) {
    var btn = e.target.closest("[data-zoom] [data-zoom-by], [data-zoom] [data-zoom-fit]");
    if (!btn) return;
    var frame = btn.closest("[data-zoom]");
    if (btn.hasAttribute("data-zoom-fit")) { frame.classList.remove("is-zoomed"); setZoom(frame, 0); return; }
    var now = parseFloat(frame.getAttribute("data-scale")) || 1;
    setZoom(frame, now * Math.pow(ZOOM_STEP, parseInt(btn.getAttribute("data-zoom-by"), 10)));
  });
  document.addEventListener("wheel", function (e) {
    if (!(e.ctrlKey || e.metaKey)) return;
    var box = e.target.closest && e.target.closest("[data-zoom] .diagram-scroll");
    if (!box) return;
    e.preventDefault();
    var frame = box.closest("[data-zoom]");
    var now = parseFloat(frame.getAttribute("data-scale")) || 1;
    setZoom(frame, now * Math.exp(-e.deltaY * 0.01), { x: e.clientX, y: e.clientY });
  }, { passive: false });
  var zoomDrag = null, zoomDragged = false;
  document.addEventListener("pointerdown", function (e) {
    var box = e.target.closest && e.target.closest("[data-zoom].is-zoomed .diagram-scroll");
    if (!box || e.pointerType !== "mouse" || e.button !== 0) return;
    zoomDrag = { box: box, x: e.clientX, y: e.clientY, left: box.scrollLeft, top: box.scrollTop, moved: false };
  });
  document.addEventListener("pointermove", function (e) {
    if (!zoomDrag) return;
    var dx = e.clientX - zoomDrag.x, dy = e.clientY - zoomDrag.y;
    if (!zoomDrag.moved && Math.abs(dx) + Math.abs(dy) < 5) return;
    zoomDrag.moved = true;
    zoomDrag.box.classList.add("is-dragging");
    zoomDrag.box.scrollLeft = zoomDrag.left - dx;
    zoomDrag.box.scrollTop = zoomDrag.top - dy;
  });
  document.addEventListener("pointerup", function () {
    if (zoomDrag && zoomDrag.moved) {
      zoomDrag.box.classList.remove("is-dragging");
      zoomDragged = true;     // the click that ends a drag opens nothing
      setTimeout(function () { zoomDragged = false; }, 0);
    }
    zoomDrag = null;
  });
  document.addEventListener("click", function (e) {
    if (zoomDragged && e.target.closest && e.target.closest(".diagram-scroll")) { e.preventDefault(); e.stopPropagation(); }
  }, true);
  window.addEventListener("resize", function () { fitDiagrams(document); });

  // [data-views]: a choice of how to show something, remembered per browser.
  var VIEWS_KEY = "app-views";
  function storedViews() {
    try { return JSON.parse(localStorage.getItem(VIEWS_KEY) || "{}"); } catch (_) { return {}; }
  }
  function showView(group, value) {
    var scope = group.closest(".tab-panel") || group.parentNode.parentNode;
    scope.querySelectorAll("[data-view]").forEach(function (panel) {
      panel.hidden = panel.getAttribute("data-view") !== value;
      if (!panel.hidden) fitDiagrams(panel);
    });
  }
  function applyViews(root) {
    var stored = storedViews();
    (root || document).querySelectorAll("[data-views]").forEach(function (group) {
      var want = stored[group.getAttribute("data-views")];
      var radio = want && group.querySelector('input[value="' + want + '"]');
      if (radio) radio.checked = true;
      var on = group.querySelector("input:checked");
      if (on) showView(group, on.value);
    });
    fitDiagrams(root || document);
  }
  document.addEventListener("change", function (e) {
    var group = e.target.closest && e.target.closest("[data-views]");
    if (!group) return;
    showView(group, e.target.value);
    var stored = storedViews();
    stored[group.getAttribute("data-views")] = e.target.value;
    try { localStorage.setItem(VIEWS_KEY, JSON.stringify(stored)); } catch (_) {}
  });
  applyViews(document);

  // A popover opens in the top layer, above a dialog, with nothing tying it
  // to its button; place it under the button (above, if there's no room),
  // kept inside the window. "toggle" doesn't bubble, so listen as it passes.
  document.addEventListener("toggle", function (e) {
    var pop = e.target;
    if (!pop.classList || !pop.classList.contains("infotip-pop") || e.newState !== "open") return;
    var btn = document.querySelector('[popovertarget="' + pop.id + '"]');
    if (!btn) return;
    var r = btn.getBoundingClientRect(), w = pop.offsetWidth, h = pop.offsetHeight;
    // A wide one (the setup guide's help) opens from the button's left edge,
    // over the step rather than the steps beside it.
    var from = pop.classList.contains("infotip-pop--wide") ? r.left : r.left + r.width / 2 - w / 2;
    var left = Math.min(Math.max(8, from), window.innerWidth - w - 8);
    var top = r.bottom + 8;
    if (top + h > window.innerHeight - 8) top = Math.max(8, r.top - h - 8);
    pop.style.left = left + "px";
    pop.style.top = top + "px";
  }, true);
  // Placed once, so it would be left behind by a scroll: close it instead.
  document.addEventListener("scroll", function () {
    document.querySelectorAll(".infotip-pop:popover-open").forEach(function (pop) { pop.hidePopover(); });
  }, true);

  // A link to a heading on the same page (a document's contents list)
  // scrolls to it inside whatever scrolls, the sheet included, and leaves the
  // address alone: the address says which record is open.
  document.addEventListener("click", function (e) {
    var a = e.target.closest('a[href^="#h-"]');
    if (!a) return;
    var target = document.getElementById(a.getAttribute("href").slice(1));
    if (!target) return;
    e.preventDefault();
    target.scrollIntoView({ behavior: prefersReducedMotion() ? "auto" : "smooth", block: "start" });
  });

  // [data-confirm]: the action waits for its button in the confirm modal.
  // Cancel, Escape or closing it does nothing.
  var confirmModal = document.getElementById("confirm-modal");
  function confirmFirst(btn, go) {
    if (!btn.hasAttribute("data-confirm")) { go(); return; }
    askFirst(btn.getAttribute("data-confirm"), btn.getAttribute("data-confirm-text"),
             btn.getAttribute("data-confirm-go") || "Remove", go);
  }
  // With no ``go``, it only tells: why it can't be done, and OK.
  function askFirst(question, detail, goLabel, go) {
    if (!confirmModal) { if (go) go(); return; }
    document.getElementById("confirm-title").textContent = question;
    var text = document.getElementById("confirm-text");
    text.textContent = detail || "";
    text.hidden = !text.textContent;
    var yes = document.getElementById("confirm-go");
    yes.hidden = !go;
    confirmModal.querySelector("[data-close]").textContent = go ? "Cancel" : "OK";
    yes.textContent = goLabel || "";
    yes.onclick = function () {
      yes.onclick = null;
      confirmModal.close();
      go();
    };
    confirmModal.showModal();
  }

  document.addEventListener("click", function (e) {
    var print = e.target.closest("[data-print]");
    if (print) { e.preventDefault(); window.print(); return; }
    var btn = e.target.closest("[data-api-post]");
    if (btn) {
      e.preventDefault();
      confirmFirst(btn, function () {
        var body = {};
        try { body = JSON.parse(btn.getAttribute("data-body") || "{}"); } catch (_) {}
        btn.disabled = true;
        api(btn.getAttribute("data-api-post"), body).then(function (data) {
          btn.disabled = false;
          afterAction(btn, data);
        }).catch(function (err) { btn.disabled = false; toastError(err); });
      });
      return;
    }
    var pick = e.target.closest("[data-pick]");
    if (pick) {
      e.preventDefault();
      var form = pick.closest("form");
      openPalette({
        types: pick.getAttribute("data-pick-types") || "",
        exclude: pick.getAttribute("data-pick-exclude") || "",
        pick: function (item) {
          var field = form && form.elements[pick.getAttribute("data-pick-into") || "other_id"];
          if (field) field.value = item.id;
          var label = pick.querySelector("[data-pick-label]");
          if (label) { label.textContent = item.title; pick.classList.add("is-picked"); }
          if (pick.hasAttribute("data-pick-submit") && form) submitApiForm(form);
          else pick.focus();
        }
      });
      return;
    }
    var reveal = e.target.closest("[data-reveal]");
    if (reveal) {
      e.preventDefault();
      var into = document.getElementById(reveal.getAttribute("data-reveal-into"));
      if (!into) return;
      if (reveal.getAttribute("aria-pressed") === "true") { hideSecret(reveal, into); return; }
      api(reveal.getAttribute("data-reveal"), {}).then(function (data) {
        into.textContent = data.value;
        into.classList.add("is-shown");
        reveal.setAttribute("aria-pressed", "true");
        reveal.textContent = "Hide";
        clearTimeout(reveal._hide);
        reveal._hide = setTimeout(function () { hideSecret(reveal, into); }, 30000);
      }).catch(toastError);
      return;
    }
    var copy = e.target.closest("[data-copy], [data-copy-url]");
    if (copy) {
      e.preventDefault();
      var text = copy.hasAttribute("data-copy") ? Promise.resolve(copy.getAttribute("data-copy"))
        : api(copy.getAttribute("data-copy-url"), {}).then(function (data) { return data.value; });
      text.then(copyText).then(function () { toast(copy.getAttribute("data-done") || "Copied"); }).catch(toastError);
      return;
    }
    var fill = e.target.closest("[data-fill]");
    if (fill) {
      e.preventDefault();
      var target = fill.getAttribute("data-fill-form")
        ? document.getElementById(fill.getAttribute("data-fill-form")) : fill.closest("form");
      if (!target) return;
      try { fillForm(target, JSON.parse(fill.getAttribute("data-fill"))); } catch (_) { return; }
      target.hidden = false;
      var focus = target.querySelector("[data-fill-focus]") || target.querySelector("input, select");
      if (focus) focus.focus();
      return;
    }
    if (e.target.closest("[data-sheet-action='archive']")) { e.preventDefault(); toggleArchive(); }
  });

  // A revealed secret goes back to its mask on a second click, or by itself
  // after 30 seconds.
  function hideSecret(btn, into) {
    clearTimeout(btn._hide);
    into.textContent = into.getAttribute("data-mask") || "••••••••";
    into.classList.remove("is-shown");
    btn.setAttribute("aria-pressed", "false");
    btn.textContent = "Show";
  }

  // The clipboard API needs HTTPS or localhost; on a plain-HTTP LAN address
  // the old way still works.
  function copyText(text) {
    if (navigator.clipboard && window.isSecureContext) return navigator.clipboard.writeText(text);
    return new Promise(function (resolve, reject) {
      var area = document.createElement("textarea");
      area.value = text;
      area.setAttribute("readonly", "");
      area.style.position = "fixed";
      area.style.opacity = "0";
      document.body.appendChild(area);
      area.select();
      var ok = false;
      try { ok = document.execCommand("copy"); } catch (_) { ok = false; }
      area.remove();
      if (ok) resolve(); else reject(new Error("The browser didn't allow copying. Select the text instead."));
    });
  }

  /* ————— Detail sheet ————— */
  // The article is the server's (sheet/sheet.html): the header, the tabs and
  // the open tab. The record and its tab live in the URL (?open=&tab=), which
  // also makes them a link.
  var sheetArticle = document.getElementById("sheet-article");
  var current = null;

  function openURL(id, tab) {
    var params = new URLSearchParams(location.search);
    if (id) params.set("open", id); else params.delete("open");
    if (id && tab && tab !== "overview") params.set("tab", tab); else params.delete("tab");
    var qs = params.toString();
    return location.pathname + (qs ? "?" + qs : "");
  }
  function setOpenParam(id, tab) {
    history.replaceState(id ? history.state : null, "", openURL(id, tab));
  }

  // Where the sheet has been. A record opened from another (a link, a page's
  // Next, j and k) is a step on the trail and an entry in the browser's
  // history, so Back and Forward, the sheet's and the browser's alike, walk
  // it; Back from the first record closes the sheet. history.state carries
  // the step's place on the trail ({sheetPos}).
  var trail = [], pos = -1;
  var trailOwnsEntry = false;    // the sheet pushed the first entry (not a link or a reload)
  // How a close and the history's moves line up: "closing" (Back closed the
  // sheet; its close event has nothing to do), "walking" (the close button
  // is taking the history back before the sheet; the popstate that follows
  // has nothing to do), "strip" (as walking, then drop ?open= from the entry
  // the page was loaded with).
  var leaving = null;
  var forgetForward = false;     // the record ahead was deleted: the trail ends here

  function updateNav() {
    var back = document.getElementById("sheet-back"), fwd = document.getElementById("sheet-forward");
    if (back) back.disabled = pos <= 0;
    if (fwd) fwd.disabled = pos < 0 || pos >= trail.length - 1;
  }

  function recordStep(id, tab, nav) {
    var url = openURL(id, tab);
    if (nav === "new" || nav === "restore") {
      trail = [{ id: id, tab: tab }];
      pos = 0;
      trailOwnsEntry = nav === "new";
      if (nav === "new") history.pushState({ sheetPos: 0 }, "", url);
      else history.replaceState({ sheetPos: 0 }, "", url);
    } else if (nav === "push") {
      trail = trail.slice(0, pos + 1).concat([{ id: id, tab: tab }]);
      pos += 1;
      history.pushState({ sheetPos: pos }, "", url);
    } else {
      trail[pos] = { id: id, tab: tab };
      history.replaceState({ sheetPos: pos }, "", url);
    }
    updateNav();
  }

  function openEntity(id, opts) {
    if (!sheet) return;
    opts = opts || {};
    // Leaving a record (another record, another tab) saves it first.
    if (!opts.flushed && sheet.open && editsPending()) {
      var next = Object.assign({}, opts, { flushed: true });
      return flushEdits().then(function (ok) {
        if (ok || discardArmed || opts.nav === "pop") {
          if (!ok && opts.nav === "pop") toast("Some changes weren't saved.", null, null, true);
          discardArmed = false;
          return openEntity(id, next);
        }
        warnUnsaved("Try again");
      });
    }
    // A step on the trail, or the same record again (a tab, a refresh).
    var nav = opts.nav || (opts.restoring || opts.fromURL ? "restore"
                           : !sheet.open || pos < 0 ? "new"
                           : current && current.id === id ? "replace" : "push");
    var before = sheet.scrollTop;
    return fetchHTML("/e/" + id + "/sheet?tab=" + encodeURIComponent(opts.tab || "overview")).then(function (html) {
      sheetArticle.innerHTML = html;
      applyViews(sheetArticle);
      var root = sheetArticle.querySelector(".sheet-content");
      current = {
        id: id,
        tab: root.getAttribute("data-tab"),
        name: root.getAttribute("data-name"),
        archived: root.getAttribute("data-archived") === "1",
        deleted: root.getAttribute("data-deleted") === "1"
      };
      updateSheetBar();
      if (!sheet.open) {
        if (opts.restoring) markRestoring(sheet);
        sheet.showModal();
        fitDiagrams(sheetArticle);    // drawn before it showed, with no width to fit to
      }
      if (opts.keepScroll) {
        sheet.scrollTop = before;
      } else if (opts.tabSwitch) {
        // One section at a time: keep the section's start in view when it is
        // shorter than the scroll, under the row of links on a narrow screen.
        var mark = sheetArticle.querySelector(".sheet-sections");
        var top = mark ? sheet.scrollTop + mark.getBoundingClientRect().top - sheet.getBoundingClientRect().top
                         - sectionOffset() + 14 : 0;
        sheet.scrollTop = Math.min(before, Math.max(0, top));
      } else if (!opts.scroll && current.tab !== "overview" && allSections()) {
        scrollToSection(current.tab, false);
      } else {
        sheet.scrollTop = opts.scroll || 0;
      }
      spyLock = null;
      markSection(current.tab);
      recordStep(id, current.tab, nav);
    }).catch(toastError);
  }

  window.addEventListener("popstate", function (e) {
    if (leaving === "walking" || leaving === "strip") {
      if (leaving === "strip") setOpenParam(null);
      leaving = null;
      return;
    }
    var st = e.state;
    if (st && typeof st.sheetPos === "number" && trail[st.sheetPos]) {
      pos = st.sheetPos;
      if (forgetForward) { trail = trail.slice(0, pos + 1); forgetForward = false; }
      openEntity(trail[pos].id, { tab: trail[pos].tab, nav: "pop" });
    } else if (st && typeof st.sheetPos === "number") {
      // A step the trail no longer has (after a reload, or a deleted record
      // ahead): open what the address says, which starts a new trail.
      var params = new URLSearchParams(location.search);
      var id = parseInt(params.get("open"), 10);
      if (id) openEntity(id, { tab: params.get("tab"), fromURL: true });
    } else if (sheet && sheet.open) {
      leaving = "closing";
      flushEdits().then(function (ok) {
        if (!ok) toast("Some changes weren't saved.", null, null, true);
        closeDialog(sheet, null, true);
      });
    }
  });
  function refreshSheet() {
    if (current && sheet && sheet.open) openEntity(current.id, { tab: current.tab, keepScroll: true, nav: "replace" });
  }

  function updateSheetBar() {
    var archive = document.getElementById("sheet-archive");
    var edit = document.getElementById("sheet-edit");
    var del = document.getElementById("sheet-delete");
    if (archive) {
      archive.hidden = current.deleted;
      archive.classList.toggle("is-on", current.archived);
      archive.setAttribute("title", current.archived ? "Unarchive (a)" : "Archive (a)");
      archive.setAttribute("aria-label", current.archived ? "Unarchive" : "Archive");
    }
    if (edit) edit.hidden = current.deleted;
    if (del) del.hidden = current.deleted;
  }

  function openSibling(step) {
    if (!current) return;
    var ids = itemIds();
    var at = ids.indexOf(current.id);
    if (at !== -1 && ids[at + step] !== undefined) openEntity(ids[at + step], { tab: current.tab });
  }
  // Wide enough for the sections' rail (app.css, .sheet-content).
  function sheetRail() { return window.matchMedia("(min-width: 901px)").matches; }
  // Every section is on the page: choosing one scrolls to it, and scrolling
  // marks the one being read in the rail (and in ?tab=, for a reload).
  var spyLock = null, spyTimer = 0, spyFrame = 0;
  // Unless the account shows one section at a time (Settings, record_scroll).
  function allSections() {
    var root = sheetArticle.querySelector(".sheet-content");
    return !!root && root.getAttribute("data-scroll") === "1";
  }
  function sectionOffset() {
    if (sheetRail()) return 24;
    var bar = sheet.querySelector(".sheet-bar"), nav = sheetArticle.querySelector(".sheet-nav");
    return (bar ? bar.offsetHeight : 0) + (nav ? nav.offsetHeight : 0) + 14;
  }
  function scrollToSection(key, smooth) {
    var section = document.getElementById("section-" + key);
    if (!section) return;
    var top = sheet.scrollTop + section.getBoundingClientRect().top - sheet.getBoundingClientRect().top - sectionOffset();
    if (key === "overview") top = 0;
    smooth = smooth && !prefersReducedMotion();
    // The rail shows where it is going, not each section passed on the way.
    spyLock = smooth ? key : null;
    clearTimeout(spyTimer);
    if (smooth) spyTimer = setTimeout(function () { spyLock = null; spySections(); }, 900);
    sheet.scrollTo({ top: Math.max(0, top), behavior: smooth ? "smooth" : "auto" });
  }
  function markSection(key) {
    sheetArticle.querySelectorAll(".sheet-nav .tab[data-tab]").forEach(function (tab) {
      var on = tab.getAttribute("data-tab") === key;
      tab.classList.toggle("is-active", on);
      if (on) {
        tab.setAttribute("aria-current", "true");
        if (!sheetRail()) {       // the row scrolls sideways to keep it in view
          var row = tab.parentNode;
          if (tab.offsetLeft < row.scrollLeft || tab.offsetLeft + tab.offsetWidth > row.scrollLeft + row.clientWidth) {
            row.scrollLeft = tab.offsetLeft - 20;
          }
        }
      } else {
        tab.removeAttribute("aria-current");
      }
    });
    if (current && current.tab !== key) {
      current.tab = key;
      recordStep(current.id, key, "replace");
    }
  }
  function spySections() {
    spyFrame = 0;
    if (!current || !sheet.open || spyLock || !allSections()) return;
    var sections = sheetArticle.querySelectorAll(".sheet-section");
    if (!sections.length) return;
    var line = sheet.getBoundingClientRect().top + sectionOffset() + 40, key = sections[0].getAttribute("data-panel");
    sections.forEach(function (section) {
      if (section.getBoundingClientRect().top <= line) key = section.getAttribute("data-panel");
    });
    markSection(key);
  }
  if (sheet) {
    sheet.addEventListener("scroll", function () {
      if (!spyFrame) spyFrame = requestAnimationFrame(spySections);
    }, { passive: true });
    sheet.addEventListener("scrollend", function () {
      if (spyLock) { clearTimeout(spyTimer); spyLock = null; }
    });
  }
  function openTab(key) {
    if (!current || !key) return;
    if (!allSections()) {
      if (key !== current.tab) openEntity(current.id, { tab: key, tabSwitch: true, nav: "replace" });
      return;
    }
    markSection(key);
    scrollToSection(key, true);
  }
  function toggleArchive() {
    if (!current || current.deleted) return;
    var id = current.id, next = !current.archived;
    api("/api/entities/" + id + "/archive", { archived: next }).then(function (data) {
      refreshSheet();
      var card = cardFor(id);
      if (card) card.classList.toggle("is-archived", next);
      offerUndo(next ? "Archived" : "Unarchived", data.undo, function () {
        refreshSheet();
        if (card) card.classList.toggle("is-archived", !next);
      });
    }).catch(toastError);
  }
  // A record is edited where it is shown: e puts the cursor in its first
  // field, on the Overview.
  function editCurrent() {
    if (!current || current.deleted) return;
    var ready = allSections() || current.tab === "overview" ? Promise.resolve()
      : openEntity(current.id, { tab: "overview", tabSwitch: true, nav: "replace" });
    Promise.resolve(ready).then(function () {
      var first = sheetArticle.querySelector("[data-autosave] [data-save]:not([hidden])");
      if (!first) return;
      first.focus({ preventScroll: true });
      scrollToSection("overview", true);
    });
  }

  if (sheet) {
    sheet.addEventListener("close", function () {
      current = null;
      if (leaving === "closing") {
        leaving = null;         // Back closed it: the address has already moved
        pos = -1;
        updateNav();
        return;
      }
      var st = history.state;
      if (st && typeof st.sheetPos === "number" && (st.sheetPos > 0 || trailOwnsEntry)) {
        // Back to the page as it was before the sheet opened, so its steps
        // don't linger in the browser's history.
        leaving = trailOwnsEntry ? "walking" : "strip";
        history.go(-(st.sheetPos + (trailOwnsEntry ? 1 : 0)));
      } else {
        setOpenParam(null);
      }
      pos = -1;
      updateNav();
    });
    sheetArticle.addEventListener("click", function (e) {
      var tab = e.target.closest(".tab[data-tab]");
      if (!tab || e.ctrlKey || e.metaKey || e.shiftKey) return;
      e.preventDefault();
      openTab(tab.getAttribute("data-tab"));
    });
    sheetArticle.addEventListener("keydown", function (e) {
      // Arrow keys move along the sections: up and down the rail, left and
      // right along the row.
      var tab = e.target.closest(".tab[data-tab]");
      var keys = sheetRail() ? { ArrowDown: 1, ArrowUp: -1 } : { ArrowRight: 1, ArrowLeft: -1 };
      if (!tab || !(keys[e.key] || e.key === "Home" || e.key === "End")) return;
      var all = Array.prototype.slice.call(sheetArticle.querySelectorAll(".tab[data-tab]"));
      var next = e.key === "Home" ? all[0] : e.key === "End" ? all[all.length - 1]
               : all[(all.indexOf(tab) + keys[e.key] + all.length) % all.length];
      e.preventDefault();
      next.focus({ preventScroll: true });
      openTab(next.getAttribute("data-tab"));
    });
    document.getElementById("sheet-back").addEventListener("click", function () { if (pos > 0) history.back(); });
    document.getElementById("sheet-forward").addEventListener("click", function () {
      if (pos >= 0 && pos < trail.length - 1) history.forward();
    });
    var editBtn = document.getElementById("sheet-edit");
    if (editBtn) editBtn.addEventListener("click", editCurrent);
    var archiveBtn = document.getElementById("sheet-archive");
    if (archiveBtn) archiveBtn.addEventListener("click", toggleArchive);
    document.getElementById("sheet-copy").addEventListener("click", copyLink);
    var deleteBtn = document.getElementById("sheet-delete");
    if (deleteBtn) deleteBtn.addEventListener("click", function () {
      if (!current) return;
      var id = current.id;
      // Always asked first, in the confirm dialog; Undo still follows.
      deleteBtn.setAttribute("data-confirm", "Delete " + current.name + "?");
      deleteBtn.setAttribute("data-confirm-text", "It goes to Recently deleted, where it can be restored until it is purged. Its links come back with it.");
      deleteBtn.setAttribute("data-confirm-go", "Delete");
      confirmFirst(deleteBtn, function () { deleteCurrent(id); });
    });
  }

  function deleteCurrent(id) {
    api("/api/entities/" + id + "/delete").then(function (data) {
      removeCard(id);
      if (pos > 0) {
        // Reached from another record: back to it, and Forward no longer
        // leads to the one just deleted.
        forgetForward = true;
        history.back();
      } else {
        closeDialog(sheet, null, true);
      }
      // Undo as well: the delete only marks the record, and restoring
      // it brings back the same id and its links.
      offerUndo("Deleted", data.undo);
    }).catch(toastError);
  }

  function copyLink() {
    if (!current) return;
    var btn = document.getElementById("sheet-copy");
    copyText(location.origin + "/e/" + current.id).then(function () {
      btn.classList.add("show-tip");
      setTimeout(function () { btn.classList.remove("show-tip"); }, 1200);
    });
  }

  function copyText(text) {
    if (navigator.clipboard && window.isSecureContext) {
      return navigator.clipboard.writeText(text);
    }
    // Plain HTTP on a LAN has no clipboard API, so fall back to the old way.
    return new Promise(function (resolve) {
      var ta = document.createElement("textarea");
      ta.value = text;
      ta.setAttribute("readonly", "");
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      (document.querySelector("dialog[open]") || document.body).appendChild(ta);
      ta.select();
      try { document.execCommand("copy"); } catch (_) {}
      ta.remove();
      resolve();
    });
  }

  // ?open=<id> deep-links straight into a record; see "Dialogs survive a
  // reload" below, which opens it (and keeps its scroll across a refresh).

  /* ————— Editing in place ————— */
  // An editor's Overview is the record's form. Its controls ([data-save],
  // or every field of a [data-save-group], a module's form section) live
  // inside [data-autosave="/api/entities/<id>"]. A change (leaving a text
  // field, choosing an option) posts that field alone; a failure shows its
  // message under the field and keeps what was typed. After a save, the
  // parts marked data-live are redrawn from the server, except one the
  // cursor is in, and the record's card in the list follows. Long text
  // ([data-prose]) shows formatted until its Edit button opens it.
  var savesInFlight = [], discardArmed = false;
  function saveControls() {
    return Array.prototype.slice.call(sheetArticle ? sheetArticle.querySelectorAll(
      "[data-autosave] [data-save], [data-autosave] [data-save-group] [name]") : []).filter(function (el) {
      return el.type !== "file" && !el.disabled;
    });
  }
  function isDirty(el) {
    if (el.type === "checkbox" || el.type === "radio") return el.checked !== el.defaultChecked;
    if (el.tagName === "SELECT") {
      return Array.prototype.some.call(el.options, function (o) { return o.selected !== o.defaultSelected; });
    }
    return el.value !== el.defaultValue;
  }
  function markSaved(el) {
    // A choice of radios is saved as one: each of them now as it is, or an
    // earlier one would read as a change still to save.
    if (el.type === "radio") {
      (el.closest("[data-autosave]") || document).querySelectorAll('input[type="radio"][name="' + CSS.escape(el.name) + '"]')
        .forEach(function (r) { r.defaultChecked = r.checked; });
    } else if (el.type === "checkbox" || el.type === "radio") el.defaultChecked = el.checked;
    else if (el.tagName === "SELECT") Array.prototype.forEach.call(el.options, function (o) { o.defaultSelected = o.selected; });
    else el.defaultValue = el.value;
  }
  function editsPending() {
    return savesInFlight.length > 0 || saveControls().some(isDirty);
  }
  function fieldOf(el) { return el.closest("[data-save-group]") || el.closest("[data-field]") || el.parentNode; }
  function showFieldError(el, message) {
    var holder = fieldOf(el), at = el.closest("dd") || holder;
    var p = at.querySelector(":scope > .field-error");
    if (!p) { p = document.createElement("p"); p.className = "form-error field-error"; p.setAttribute("role", "alert"); at.appendChild(p); }
    p.textContent = message;
    el.setAttribute("aria-invalid", "true");
  }
  function clearFieldError(el) {
    var holder = fieldOf(el), at = el.closest("dd") || holder;
    var p = at.querySelector(":scope > .field-error");
    if (p) p.remove();
    holder.querySelectorAll("[aria-invalid]").forEach(function (c) { c.removeAttribute("aria-invalid"); });
  }
  function bodyFor(el) {
    var group = el.closest("[data-save-group]");
    var els = group ? Array.prototype.slice.call(group.querySelectorAll("[name]")).filter(function (c) { return c.type !== "file"; }) : [el];
    var body = {};
    els.forEach(function (c) {
      if (c.type === "radio" && !c.checked) return;
      body[c.name] = c.type === "checkbox" ? c.checked : c.value;
    });
    return { url: el.closest("[data-autosave]").getAttribute("data-autosave"), body: body, els: els };
  }
  function saveField(el) {
    var req = bodyFor(el), holder = fieldOf(el), id = current && current.id;
    clearFieldError(el);
    holder.classList.add("is-saving");
    var p = api(req.url, req.body).then(function () {
      req.els.forEach(markSaved);
      holder.classList.remove("is-saving");
      discardArmed = false;
      // After this save has left savesInFlight: a new type redraws the
      // whole record; anything else only its live parts.
      setTimeout(function () {
        if (el.hasAttribute("data-retype")) refreshSheet(); else refreshLive(id);
        refreshCard(id);
      }, 0);
      return true;
    }, function (err) {
      holder.classList.remove("is-saving");
      showFieldError(el, err.message);
      return false;
    });
    savesInFlight.push(p);
    p.then(function () { savesInFlight.splice(savesInFlight.indexOf(p), 1); });
    return p;
  }
  // Everything unsaved, saved now (one request per field or group), with
  // those already on their way. True when all of it went.
  function flushEdits() {
    var seen = [], saves = savesInFlight.slice();
    saveControls().filter(isDirty).forEach(function (el) {
      var key = el.closest("[data-save-group]") || el;
      if (seen.indexOf(key) !== -1) return;
      seen.push(key);
      saves.push(saveField(el));
    });
    return Promise.all(saves).then(function (results) { return results.every(Boolean); });
  }
  function warnUnsaved(action) {
    discardArmed = true;
    toast("A change isn't saved: its field says why. " + action + " again to discard it.", null, null, true);
  }
  function refreshLive(id) {
    if (!current || current.id !== id) return;
    fetchHTML("/e/" + id + "/sheet?tab=" + encodeURIComponent(current.tab)).then(function (html) {
      if (!current || current.id !== id) return;
      var fresh = document.createElement("div");
      fresh.innerHTML = html;
      fresh.querySelectorAll("[data-live]").forEach(function (part) {
        var old = sheetArticle.querySelector('[data-live="' + part.getAttribute("data-live") + '"]');
        if (old && !old.contains(document.activeElement)) old.replaceWith(part);
      });
      var root = fresh.querySelector(".sheet-content"), here = sheetArticle.querySelector(".sheet-content");
      if (root && here) {
        current.name = root.getAttribute("data-name");
        here.setAttribute("data-name", current.name);
      }
    }).catch(function () { /* the value is saved; the page catches up on the next load */ });
  }
  // The list behind the sheet shows the record as it now is.
  function refreshCard(id) {
    var card = id && cardFor(id);
    if (!card) return;
    var view = card.classList.contains("row") ? "list" : "cards";
    fetchHTML("/e/" + id + "/card?view=" + view).then(function (html) {
      var fresh = document.createElement("div");
      fresh.innerHTML = html;
      var item = fresh.querySelector("[data-item]"), now = cardFor(id);
      if (item && now) now.replaceWith(item);
    }).catch(function () {});
  }
  if (sheetArticle) {
    document.addEventListener("change", function (e) {
      var el = e.target;
      if (!el.closest || !sheetArticle.contains(el) || !el.closest("[data-autosave]") || el.type === "file") return;
      if (!el.hasAttribute("data-save") && !el.closest("[data-save-group]")) return;
      if (isDirty(el)) saveField(el);
    });
    // Enter in a one-line field saves it, as leaving it would.
    sheetArticle.addEventListener("keydown", function (e) {
      var el = e.target;
      if (e.key !== "Enter" || el.tagName !== "INPUT" || !el.hasAttribute("data-save")) return;
      e.preventDefault();
      if (isDirty(el)) saveField(el);
    });
    sheetArticle.addEventListener("click", function (e) {
      var btn = e.target.closest("[data-prose-edit]");
      if (!btn) return;
      var box = btn.closest("[data-prose]"), text = box.querySelector("textarea");
      box.classList.add("is-editing");
      text.hidden = false;
      autosize(text);
      text.focus();
    });
    sheetArticle.addEventListener("input", function (e) {
      if (e.target.matches(".prose-input")) autosize(e.target);
    });
    // Left unchanged, long text goes back to showing formatted; changed, it
    // is saved (above) and comes back formatted from the server.
    sheetArticle.addEventListener("focusout", function (e) {
      var text = e.target;
      if (!text.matches || !text.matches(".prose-input") || isDirty(text)) return;
      var box = text.closest("[data-prose]");
      box.classList.remove("is-editing");
      text.hidden = true;
    });
  }
  function autosize(text) {
    text.style.height = "auto";
    text.style.height = Math.max(text.scrollHeight + 2, 160) + "px";
  }
  // A reload or a closed tab still sends what was typed.
  window.addEventListener("pagehide", function () {
    var seen = [];
    saveControls().filter(isDirty).forEach(function (el) {
      var key = el.closest("[data-save-group]") || el;
      if (seen.indexOf(key) !== -1) return;
      seen.push(key);
      var req = bodyFor(el);
      try {
        fetch(req.url, { method: "POST", keepalive: true, body: JSON.stringify(req.body),
                         headers: { "Content-Type": "application/json", "X-CSRF": CSRF } });
      } catch (_) {}
    });
  });

  /* ————— Picture viewer ————— */
  // A [data-gallery] holds links to pictures ([data-gallery-item], each with
  // data-large and data-caption). A click shows them large in #lightbox, where
  // the arrow keys, the side buttons and a swipe move through them. A link
  // opened in a new tab still gets the file itself.
  var lightbox = document.getElementById("lightbox");
  if (lightbox) {
    var lbImg = document.getElementById("lightbox-img");
    var lbItems = [], lbAt = 0, lbSwiped = false;
    var showPicture = function (i) {
      var n = lbItems.length;
      lbAt = (i + n) % n;
      var item = lbItems[lbAt];
      lbImg.src = item.large;
      lbImg.alt = item.caption;
      document.getElementById("lightbox-caption").textContent = item.caption;
      document.getElementById("lightbox-count").textContent = n > 1 ? (lbAt + 1) + " of " + n : "";
      document.getElementById("lightbox-original").href = item.href;
      lightbox.classList.toggle("is-single", n < 2);
      if (n > 1) {   // the neighbors load ahead, so moving on is instant
        new Image().src = lbItems[(lbAt + 1) % n].large;
        new Image().src = lbItems[(lbAt - 1 + n) % n].large;
      }
    };
    document.addEventListener("click", function (e) {
      var link = e.target.closest("[data-gallery] [data-gallery-item]");
      if (!link || e.ctrlKey || e.metaKey || e.shiftKey || e.altKey || e.button) return;
      e.preventDefault();
      var seen = {}, start = 0;
      lbItems = [];
      link.closest("[data-gallery]").querySelectorAll("[data-gallery-item]").forEach(function (a) {
        var large = a.getAttribute("data-large") || a.href;
        if (a === link) start = seen[large] !== undefined ? seen[large] : lbItems.length;
        if (seen[large] !== undefined) return;   // a picture listed twice shows once
        seen[large] = lbItems.length;
        lbItems.push({ href: a.href, large: large, caption: a.getAttribute("data-caption") || "" });
      });
      showPicture(start);
      lightbox.showModal();
    });
    document.getElementById("lightbox-prev").addEventListener("click", function () { showPicture(lbAt - 1); });
    document.getElementById("lightbox-next").addEventListener("click", function () { showPicture(lbAt + 1); });
    lightbox.addEventListener("keydown", function (e) {
      if (e.key === "ArrowLeft") { e.preventDefault(); showPicture(lbAt - 1); }
      else if (e.key === "ArrowRight") { e.preventDefault(); showPicture(lbAt + 1); }
    });
    // A swipe sideways on a touch screen moves along; a tap beside the
    // picture closes it, as there is nothing in the viewer to lose.
    var swipeFrom = null;
    lightbox.addEventListener("pointerdown", function (e) {
      swipeFrom = e.pointerType === "mouse" ? null : { x: e.clientX, y: e.clientY };
    });
    lightbox.addEventListener("pointerup", function (e) {
      if (!swipeFrom) return;
      var dx = e.clientX - swipeFrom.x, dy = e.clientY - swipeFrom.y;
      swipeFrom = null;
      if (Math.abs(dx) > 50 && Math.abs(dx) > Math.abs(dy) * 1.5 && lbItems.length > 1) {
        lbSwiped = true;
        showPicture(lbAt + (dx < 0 ? 1 : -1));
      }
    });
    lightbox.addEventListener("click", function (e) {
      if (lbSwiped) { lbSwiped = false; return; }
      if (e.target === lightbox) closeDialog(lightbox);
    });
    lightbox.addEventListener("close", function () { lbImg.removeAttribute("src"); });
  }

  /* ————— Keyboard ————— */
  document.addEventListener("keydown", function (e) {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
      e.preventDefault();
      openPalette();
      return;
    }
    var typing = /^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName) || e.target.isContentEditable;
    if (typing || e.ctrlKey || e.metaKey || e.altKey) return;
    var top = document.querySelector("dialog[open]:not(#sheet)");
    if (sheet && sheet.open && !top) {
      if (e.key === "j") { e.preventDefault(); openSibling(1); }
      else if (e.key === "k") { e.preventDefault(); openSibling(-1); }
      else if (e.key === "e") { e.preventDefault(); editCurrent(); }
      else if (e.key === "a") { e.preventDefault(); toggleArchive(); }
      else if (e.key === "c") { e.preventDefault(); copyLink(); }
      else if (/^[1-9]$/.test(e.key)) {
        var tabs = sheetArticle.querySelectorAll(".tab[data-tab]");
        var tab = tabs[parseInt(e.key, 10) - 1];
        if (tab) { e.preventDefault(); openTab(tab.getAttribute("data-tab")); }
      }
      return;
    }
    if (document.querySelector("dialog[open]")) return;
    if (e.key === "n") {
      var newBtn = document.getElementById("new-btn");
      if (newBtn) { e.preventDefault(); newBtn.click(); }
    } else if (e.key === "/") { e.preventDefault(); openPalette(); }
  });

  /* ————— Search palette (Ctrl/Cmd+K) ————— */
  // Also the record picker: openPalette({pick: fn}) hands the chosen record
  // to fn instead of opening it, which is how links are made.
  var palette = document.getElementById("search-modal");
  var searchInput = document.getElementById("search-input");
  var searchResults = document.getElementById("search-results");
  var searchTimer = null;
  var searchSeq = 0;
  var activeIndex = -1;
  var paletteItems = [];
  var picking = null;

  var kbd = document.getElementById("search-kbd");
  if (kbd && /Mac|iPhone|iPad/.test(navigator.platform)) kbd.textContent = "⌘K";

  function openPalette(opts) {
    if (!palette || palette.open) return;
    picking = opts && opts.pick ? opts : null;
    searchInput.value = "";
    searchInput.placeholder = picking ? "Find the record to link…" : "Search everything…";
    // A half-made link isn't worth bringing back after a reload.
    if (picking) palette.setAttribute("data-restore", "off"); else palette.removeAttribute("data-restore");
    searchResults.hidden = true;
    searchResults.textContent = "";
    activeIndex = -1;
    paletteItems = [];
    palette.showModal();
    searchInput.focus();
  }
  if (palette) palette.addEventListener("close", function () { picking = null; });
  var searchBtn = document.getElementById("search-btn");
  if (searchBtn) searchBtn.addEventListener("click", function () { openPalette(); });

  function highlight(text, query) {
    var at = text.toLowerCase().indexOf(query.toLowerCase());
    var frag = document.createDocumentFragment();
    if (at === -1) { frag.appendChild(document.createTextNode(text)); return frag; }
    frag.appendChild(document.createTextNode(text.slice(0, at)));
    var mark = document.createElement("mark");
    mark.textContent = text.slice(at, at + query.length);
    frag.appendChild(mark);
    frag.appendChild(document.createTextNode(text.slice(at + query.length)));
    return frag;
  }

  function renderResults(groups, query) {
    searchResults.textContent = "";
    paletteItems = [];
    var found = groups.some(function (g) { return g.items.length; });
    if (!found) {
      var empty = document.createElement("p");
      empty.className = "palette-empty";
      empty.textContent = "Nothing matches “" + query + "”.";
      searchResults.appendChild(empty);
      searchResults.hidden = false;
      activeIndex = -1;
      return;
    }
    if (!picking) {
      groups = groups.concat([{ label: "", items: [{ url: "/all?q=" + encodeURIComponent(query),
        title: "Every record matching “" + query + "”", meta: "as a list", all: true }] }]);
    }
    groups.forEach(function (group) {
      if (group.label) {
        var label = document.createElement("p");
        label.className = "palette-label";
        label.textContent = group.label;
        searchResults.appendChild(label);
      }
      group.items.forEach(function (r) {
        var i = paletteItems.length;
        paletteItems.push(r);
        var row = document.createElement("div");
        row.className = "palette-item" + (r.archived ? " is-done" : "") + (r.all ? " palette-item--all" : "");
        var title = document.createElement("span");
        title.className = "palette-item-title";
        title.appendChild(r.all ? document.createTextNode(r.title) : highlight(r.title, query));
        var meta = document.createElement("span");
        meta.className = "palette-item-meta";
        meta.textContent = r.meta || "";
        row.appendChild(title);
        row.appendChild(meta);
        row.addEventListener("click", function () { choose(i); });
        row.addEventListener("mousemove", function () { setActive(i, true); });
        searchResults.appendChild(row);
      });
    });
    searchResults.hidden = false;
    setActive(0, true);
  }

  function rows() { return searchResults.querySelectorAll(".palette-item"); }
  function setActive(i, noScroll) {
    var all = rows();
    if (!all.length) return;
    activeIndex = Math.max(0, Math.min(all.length - 1, i));
    all.forEach(function (el, n) { el.classList.toggle("is-active", n === activeIndex); });
    if (!noScroll) all[activeIndex].scrollIntoView({ block: "nearest" });
  }
  function choose(i) {
    var item = paletteItems[i === undefined ? activeIndex : i];
    if (!item) return;
    var pick = picking && picking.pick;
    palette.close();
    if (pick) { pick(item); return; }
    if (item.id) openEntity(item.id);
    else if (item.url) location.href = item.url;
  }

  if (searchInput) {
    searchInput.addEventListener("input", function () {
      var query = searchInput.value.trim();
      clearTimeout(searchTimer);
      if (query.length < 2) { searchResults.hidden = true; return; }
      var url = "/search?q=" + encodeURIComponent(query);
      if (picking) {
        url += "&pick=1";
        if (picking.types) url += "&types=" + encodeURIComponent(picking.types);
        if (picking.exclude) url += "&exclude=" + encodeURIComponent(picking.exclude);
      }
      // Debounced, and sequenced so a slow answer to an old query never
      // replaces the answer to the current one.
      searchTimer = setTimeout(function () {
        var seq = ++searchSeq;
        get(url).then(function (data) {
          if (seq === searchSeq) renderResults(data.groups || [], query);
        }).catch(function () {});
      }, 150);
    });
    searchInput.addEventListener("keydown", function (e) {
      if (e.key === "ArrowDown") { e.preventDefault(); setActive(activeIndex + 1); }
      else if (e.key === "ArrowUp") { e.preventDefault(); setActive(activeIndex - 1); }
      else if (e.key === "Enter") { e.preventDefault(); choose(); }
    });
  }

  /* ————— Paging: Load more, or infinite scroll ————— */
  var loading = false;
  var pagerObserver = null;

  function infiniteOn() {
    return recordsRoot && recordsRoot.getAttribute("data-infinite") === "1";
  }

  function loadMore(btn) {
    if (loading || !btn || !recordsRoot) return;
    loading = true;
    var params = new URLSearchParams(location.search);
    params.delete("open");
    params.set("page", btn.getAttribute("data-page"));
    params.set("partial", "1");
    params.set("view", recordsRoot.getAttribute("data-view"));
    setBusy(btn, true);
    fetch(location.pathname + "?" + params.toString(), { headers: { "Accept": "text/html" } })
      .then(function (resp) {
        if (!resp.ok) throw new Error();
        return resp.text();
      })
      .then(function (html) {
        var holder = document.createElement("div");
        holder.innerHTML = html;
        var incoming = holder.querySelector(".grid--cards, .grid--list");
        var target = recordsRoot.querySelector(".grid--cards, .grid--list");
        if (incoming && target) {
          while (incoming.firstChild) target.appendChild(incoming.firstChild);
        }
        var oldPager = btn.closest(".pager");
        var newPager = holder.querySelector(".pager, .pager-end");
        if (newPager) oldPager.replaceWith(newPager); else oldPager.remove();
        loading = false;
        watchPager();
      })
      .catch(function () {
        loading = false;
        setBusy(btn, false);
        toast("Couldn't load more records.", null, null, true);
      });
  }

  // Watch the pager row, not the last record: it is replaced wholesale by
  // every load, so re-observing after each one is enough.
  function watchPager() {
    if (pagerObserver) pagerObserver.disconnect();
    var btn = document.getElementById("load-more");
    if (!btn || !infiniteOn() || !("IntersectionObserver" in window)) return;
    pagerObserver = new IntersectionObserver(function (entries) {
      if (entries[0].isIntersecting) loadMore(document.getElementById("load-more"));
    }, { rootMargin: "600px 0px" });
    pagerObserver.observe(btn.closest(".pager"));
  }

  document.addEventListener("click", function (e) {
    var btn = e.target.closest("#load-more");
    if (btn) loadMore(btn);
  });
  watchPager();

  /* ————— Pull to refresh (touch devices) ————— */
  (function initPullToRefresh() {
    var ptr = document.getElementById("ptr");
    if (!ptr || !("ontouchstart" in window)) return;
    var THRESHOLD = 80, startY = null, pull = 0;
    document.addEventListener("touchstart", function (e) {
      if (window.scrollY > 0 || document.querySelector("dialog[open]") ||
          (sidebar && sidebar.classList.contains("is-open"))) { startY = null; return; }
      startY = e.touches[0].clientY;
      pull = 0;
    }, { passive: true });
    document.addEventListener("touchmove", function (e) {
      if (startY === null) return;
      pull = Math.max(0, e.touches[0].clientY - startY);
      // Resistance: the spinner follows the finger at a third of its travel.
      var y = Math.min(pull / 2.5, THRESHOLD + 20);
      ptr.classList.add("is-dragging");
      ptr.classList.toggle("is-armed", pull > THRESHOLD * 1.6);
      ptr.style.transform = "translateY(" + y + "px) rotate(" + (pull * 1.5) + "deg)";
    }, { passive: true });
    document.addEventListener("touchend", function () {
      if (startY === null) return;
      startY = null;
      ptr.classList.remove("is-dragging");
      if (ptr.classList.contains("is-armed")) {
        ptr.classList.add("is-refreshing");
        ptr.style.transform = "translateY(" + (THRESHOLD + 10) + "px)";
        location.reload();
      } else {
        ptr.style.transform = "";
      }
    });
  })();

  /* ————— Dialogs survive a reload ————— */
  // Refreshing the page brings back the dialog that was open, as it was: the
  // settings section and its scroll, a half-typed record, the search query.
  // It is the default for every <dialog>, including ones added later: one
  // with nothing to remember simply reopens. Add data-restore="off" to a
  // dialog that must not come back. Only a reload restores; arriving at the
  // page any other way starts clean. sessionStorage keeps it to this tab.
  //
  // Dialogs with state register a save/restore pair in dialogMemory.
  var RESTORE_KEY = "app-dialog";
  var navEntry = (performance.getEntriesByType && performance.getEntriesByType("navigation")[0]) || {};
  var reloaded = navEntry.type === "reload";
  var remembered = null;
  try { remembered = JSON.parse(sessionStorage.getItem(RESTORE_KEY) || "null"); } catch (_) {}
  try { sessionStorage.removeItem(RESTORE_KEY); } catch (_) {}
  if (!reloaded || !remembered || remembered.path !== location.pathname) remembered = null;

  var dialogMemory = {
    "settings-modal": {
      save: function (d) {
        var active = d.querySelector(".settings-navitem.is-active");
        var pane = d.querySelector(".settings-pane.is-active");
        return {
          section: active && active.getAttribute("data-section"),
          pane: d.classList.contains("is-showing-pane"),
          scroll: pane ? pane.scrollTop : 0
        };
      },
      restore: function (d, s) {
        openDialog("settings-modal", s.section);
        if (narrow.matches && !s.pane) d.classList.remove("is-showing-pane");
        var pane = d.querySelector(".settings-pane.is-active");
        if (pane) requestAnimationFrame(function () { pane.scrollTop = s.scroll || 0; });
      }
    },
    "entity-modal": {
      save: function () {
        var form = formSlot && formSlot.querySelector("form");
        return form ? { src: formSource, values: formData(form) } : null;
      },
      restore: function (d, s) {
        if (!s || !s.src) return;
        loadForm(s.src).then(function (form) {   // the form fresh, then the draft back in
          fillForm(form, s.values);
          d.showModal();
        }).catch(toastError);
      }
    },
    "search-modal": {
      save: function () { return { q: searchInput.value }; },
      restore: function (d, s) {
        openPalette();
        searchInput.value = s.q || "";
        searchInput.dispatchEvent(new Event("input"));
      }
    },
    // The sheet's record and tab live in the URL (?open=<id>&tab=), which
    // also makes them a link; only its scroll offset needs remembering.
    "sheet": {
      save: function (d) { return { scroll: d.scrollTop }; },
      restore: function () {}
    }
  };

  function markRestoring(d) {
    // Reappear in place: no entrance animation for a dialog that never left.
    d.classList.add("is-restoring");
    setTimeout(function () { d.classList.remove("is-restoring"); }, 60);
  }

  var topDialog = null;
  function rememberDialog() {
    try {
      if (!topDialog || !topDialog.open || topDialog.getAttribute("data-restore") === "off") {
        sessionStorage.removeItem(RESTORE_KEY);
        return;
      }
      var memory = dialogMemory[topDialog.id];
      sessionStorage.setItem(RESTORE_KEY, JSON.stringify({
        id: topDialog.id,
        path: location.pathname,
        state: memory ? memory.save(topDialog) : null
      }));
    } catch (_) {}
  }
  var dialogWatcher = new MutationObserver(function (records) {
    records.forEach(function (r) {
      if (r.target.open) topDialog = r.target;
      else if (topDialog === r.target) topDialog = document.querySelector("dialog[open]");
    });
    rememberDialog();
  });
  document.querySelectorAll("dialog[id]").forEach(function (d) {
    dialogWatcher.observe(d, { attributes: true, attributeFilter: ["open"] });
  });
  // The latest draft, section and scroll are read as the page goes away.
  window.addEventListener("pagehide", rememberDialog);

  function restoreDialog() {
    var toRestore = document.getElementById(remembered.id);
    if (toRestore && toRestore.tagName === "DIALOG" && toRestore.getAttribute("data-restore") !== "off" && remembered.id !== "sheet") {
      markRestoring(toRestore);
      var memory = dialogMemory[remembered.id];
      if (memory) memory.restore(toRestore, remembered.state || {});
      else toRestore.showModal();
    }
  }
  var deepLink = parseInt(new URLSearchParams(location.search).get("open"), 10);
  if (deepLink) {
    // The sheet first, then whatever was open over it (a record's form).
    var sheetState = remembered && remembered.id === "sheet" ? remembered.state || {} : null;
    var opening = openEntity(deepLink, { tab: new URLSearchParams(location.search).get("tab"), restoring: !!remembered,
                                         fromURL: true, scroll: sheetState ? sheetState.scroll : 0 });
    if (remembered && !sheetState && opening) opening.then(restoreDialog);
  } else if (remembered) {
    restoreDialog();
  }

  /* ————— About hero: animated sine-wave gradient ————— */
  (function initAboutHeroBg() {
    var canvas = document.querySelector(".about-hero-bg");
    if (!canvas || prefersReducedMotion() || !("IntersectionObserver" in window)) return;
    var W = 200, H = 120;
    canvas.width = W; canvas.height = H;
    var cctx = canvas.getContext("2d");

    function hslToRgb(h, s, l) {
      h /= 360;
      var a = s * Math.min(l, 1 - l);
      var f = function (n) {
        var k = (n + h * 12) % 12;
        return Math.round((l - a * Math.max(-1, Math.min(k - 3, 9 - k, 1))) * 255);
      };
      return [f(0), f(8), f(4)];
    }
    var rand = function (a, b) { return a + Math.random() * (b - a); };

    // A triadic palette from a random base hue: every visit looks different
    // and none of them clash.
    var hueBase = Math.random() * 360;
    var triad = [0, 120, 240].map(function (d) { return (hueBase + d + rand(-8, 8) + 360) % 360; });
    for (var i = triad.length - 1; i > 0; i--) {
      var j = Math.floor(Math.random() * (i + 1));
      var tmp = triad[i]; triad[i] = triad[j]; triad[j] = tmp;
    }
    var rgb = triad.map(function (h) { return hslToRgb(h, 1, 0.55); });
    var n = rgb.length;

    var freq1 = rand(2.2, 4.0), freq2 = rand(5.0, 8.0);
    var amp1 = rand(0.16, 0.28), amp2 = rand(0.06, 0.12);
    var speed1 = rand(0.05, 0.12) * (Math.random() < 0.5 ? 1 : -1);
    var speed2 = rand(0.06, 0.14) * (Math.random() < 0.5 ? 1 : -1);
    var phase = Math.random() * Math.PI * 2;
    var rot = Math.random() * Math.PI * 2;
    var cosR = Math.cos(rot), sinR = Math.sin(rot);
    var maxDim = Math.max(W, H);

    var img = cctx.createImageData(W, H);
    var d = img.data;
    var running = false, start = 0;

    function frame(now) {
      if (!running) return;
      var t = (now - start) / 1000;
      var p1 = t * speed1, p2 = t * speed2 + phase;
      for (var y = 0; y < H; y++) {
        for (var x = 0; x < W; x++) {
          var cx = x - W / 2, cy = y - H / 2;
          var rx = cx * cosR - cy * sinR, ry = cx * sinR + cy * cosR;
          var nx = (rx + maxDim / 2) / maxDim, ny = (ry + maxDim / 2) / maxDim;
          var wave = Math.sin(nx * freq1 + p1) * amp1 + Math.sin(nx * freq2 + p2) * amp2;
          var g = Math.min(0.9999, Math.max(0, ny + wave));
          var seg = g * (n - 1), lo = Math.floor(seg), f = seg - lo;
          var c0 = rgb[lo], c1 = rgb[Math.min(lo + 1, n - 1)];
          var o = (y * W + x) * 4;
          d[o] = c0[0] + (c1[0] - c0[0]) * f;
          d[o + 1] = c0[1] + (c1[1] - c0[1]) * f;
          d[o + 2] = c0[2] + (c1[2] - c0[2]) * f;
          d[o + 3] = 255;
        }
      }
      cctx.putImageData(img, 0, 0);
      requestAnimationFrame(frame);
    }
    // Animate only while the canvas is visible (the About section is open).
    new IntersectionObserver(function (entries) {
      var visible = entries[0].isIntersecting;
      if (visible && !running) {
        running = true;
        start = performance.now();
        requestAnimationFrame(frame);
      } else if (!visible) {
        running = false;
      }
    }).observe(canvas);
  })();
})();
