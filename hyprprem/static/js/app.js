/* Hyprprem client. No dependencies, no build step.
 *
 * Sections, in order: API, toasts, theme, mobile sidebar, dialogs, settings,
 * admin, menus, records, the record form, the detail sheet, keyboard, search
 * palette, paging, pull to refresh, the About hero. Each section guards on
 * the elements it needs, so deleting one leaves the rest working.
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
    // while a dialog is open has to live inside it to be seen at all.
    var open = document.querySelector("dialog[open]");
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
      api("/settings", { theme: next }).catch(function () {});
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
    if (id === "item-modal") resetItemForm();
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

  // The sheet slides back out through the top before it actually closes, so
  // every way of dismissing it routes through here (button, backdrop, Escape).
  var SHEET_EXIT_MS = 300;   // keep in step with the sheet-out animation
  var sheetExitTimer = null;
  function closeDialog(dialog, then) {
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
  // chrome: the sheet's 840px shell is wider than its 660px article column, so
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
  document.querySelectorAll("dialog").forEach(function (dialog) {
    onBackdropClick(dialog, function () { closeDialog(dialog); });
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
   ["inst-perpage", "items_per_page", "Page size saved"]].forEach(function (spec) {
    var input = document.getElementById(spec[0]);
    if (!input) return;
    input.addEventListener("change", function () {
      var body = {};
      body[spec[1]] = parseInt(input.value, 10);
      api("/admin/instance", body).then(function () { toast(spec[2]); }).catch(toastError);
    });
  });

  document.querySelectorAll('input[name="default_role"]').forEach(function (radio) {
    radio.addEventListener("change", function () {
      api("/admin/instance", { default_role: radio.value })
        .then(function () { toast("New accounts start as " + radio.value + "s"); })
        .catch(toastError);
    });
  });

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
  function setCardDone(id, done) {
    var el = cardFor(id);
    if (!el) return;
    el.classList.toggle("is-done", !!done);
    var meta = el.querySelector(".card-meta");
    if (meta) meta.textContent = done ? "Done" : "Open";
  }
  function setCardPinned(id, pinned) {
    var el = cardFor(id);
    var btn = el && el.querySelector(".pinbtn");
    if (!btn) return;
    btn.classList.toggle("is-pinned", !!pinned);
    btn.setAttribute("title", pinned ? "Unpin" : "Pin");
    btn.setAttribute("aria-label", pinned ? "Unpin" : "Pin");
  }
  function removeCard(id) {
    var el = cardFor(id);
    if (el) el.remove();
  }

  if (recordsRoot) {
    // Delegated: records appended by paging need no binding of their own.
    recordsRoot.addEventListener("click", function (e) {
      var pin = e.target.closest("[data-pin]");
      if (pin) {
        e.stopPropagation();
        var pid = parseInt(pin.getAttribute("data-pin"), 10);
        var next = !pin.classList.contains("is-pinned");
        setCardPinned(pid, next);             // optimistic: the UI answers at once
        api("/items/" + pid, { pinned: next }).catch(function (err) {
          setCardPinned(pid, !next);          // and rolls back if the server says no
          toastError(err);
        });
        return;
      }
      var card = e.target.closest("[data-item]");
      if (card) openItem(parseInt(card.getAttribute("data-item"), 10));
    });
    recordsRoot.addEventListener("keydown", function (e) {
      var card = e.target.closest("[data-item]");
      if (card && e.target === card && (e.key === "Enter" || e.key === " ")) {
        e.preventDefault();
        openItem(parseInt(card.getAttribute("data-item"), 10));
      }
    });
  }

  /* ————— The record form ————— */
  var itemModal = document.getElementById("item-modal");
  var itemForm = document.getElementById("item-form");

  function resetItemForm(item) {
    if (!itemForm) return;
    document.getElementById("item-id").value = item ? item.id : "";
    document.getElementById("item-title").value = item ? item.title : "";
    document.getElementById("item-body").value = item ? item.body : "";
    document.getElementById("item-modal-title").textContent = item ? "Edit record" : "New record";
    document.getElementById("item-error").hidden = true;
  }

  if (itemForm) {
    itemForm.addEventListener("submit", function (e) {
      e.preventDefault();
      var errEl = document.getElementById("item-error");
      var btn = itemForm.querySelector("button[type=submit]");
      var id = document.getElementById("item-id").value;
      errEl.hidden = true;
      setBusy(btn, true);
      api(id ? "/items/" + id : "/items", {
        title: document.getElementById("item-title").value.trim(),
        body: document.getElementById("item-body").value
      }).then(function () {
        itemModal.close();   // saved: the reload shows the list, not the form again
        reloadWith(id ? "Record updated" : "Record created");
      }).catch(function (err) {
        errEl.textContent = err.message;
        errEl.hidden = false;
        setBusy(btn, false);
      });
    });
  }

  /* ————— Detail sheet ————— */
  var currentItem = null;

  function renderSheet(item) {
    currentItem = item;
    document.getElementById("sheet-title").textContent = item.title;
    document.getElementById("sheet-kicker").textContent = item.done ? "Done" : "Open";
    document.getElementById("sheet-meta").textContent = "Created " +
      new Date(item.created_at).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
    // textContent, never innerHTML: the body is whatever the user typed.
    var body = document.getElementById("sheet-body");
    body.textContent = "";
    (item.body || "").split(/\n{2,}/).forEach(function (para) {
      if (!para.trim()) return;
      var p = document.createElement("p");
      p.textContent = para;
      body.appendChild(p);
    });
    var pin = document.getElementById("sheet-pin");
    pin.classList.toggle("is-pinned", item.pinned);
    pin.setAttribute("title", item.pinned ? "Unpin (p)" : "Pin (p)");
    var done = document.getElementById("sheet-done");
    done.classList.toggle("is-done", item.done);
    done.setAttribute("title", item.done ? "Mark as open (d)" : "Mark as done (d)");
  }

  function setOpenParam(id) {
    var params = new URLSearchParams(location.search);
    if (id) params.set("open", id); else params.delete("open");
    var qs = params.toString();
    history.replaceState(null, "", location.pathname + (qs ? "?" + qs : ""));
  }

  function openItem(id, opts) {
    if (!sheet) return;
    opts = opts || {};
    get("/items/" + id).then(function (data) {
      renderSheet(data.item);
      if (!sheet.open) {
        if (opts.restoring) markRestoring(sheet);
        sheet.showModal();
      }
      sheet.scrollTop = opts.scroll || 0;
      setOpenParam(id);
    }).catch(toastError);
  }

  function openSibling(step) {
    if (!currentItem) return;
    var ids = itemIds();
    var next = ids[ids.indexOf(currentItem.id) + step];
    if (next !== undefined && ids.indexOf(currentItem.id) !== -1) openItem(next);
  }

  function togglePin() {
    if (!currentItem) return;
    api("/items/" + currentItem.id, { pinned: !currentItem.pinned }).then(function (data) {
      renderSheet(data.item);
      setCardPinned(data.item.id, data.item.pinned);
    }).catch(toastError);
  }
  function toggleDone() {
    if (!currentItem) return;
    api("/items/" + currentItem.id, { done: !currentItem.done }).then(function (data) {
      renderSheet(data.item);
      setCardDone(data.item.id, data.item.done);
    }).catch(toastError);
  }
  function editCurrent() {
    if (!currentItem) return;
    var item = currentItem;
    closeDialog(sheet, function () {
      resetItemForm(item);
      itemModal.showModal();
    });
  }

  if (sheet) {
    sheet.addEventListener("close", function () {
      currentItem = null;
      setOpenParam(null);
    });
    document.getElementById("sheet-prev").addEventListener("click", function () { openSibling(-1); });
    document.getElementById("sheet-next").addEventListener("click", function () { openSibling(1); });
    document.getElementById("sheet-pin").addEventListener("click", togglePin);
    document.getElementById("sheet-done").addEventListener("click", toggleDone);
    document.getElementById("sheet-edit").addEventListener("click", editCurrent);
    document.getElementById("sheet-copy").addEventListener("click", function () {
      if (!currentItem) return;
      var btn = this;
      copyText(location.origin + "/?open=" + currentItem.id).then(function () {
        btn.classList.add("show-tip");
        setTimeout(function () { btn.classList.remove("show-tip"); }, 1200);
      });
    });
    document.getElementById("sheet-delete").addEventListener("click", function () {
      if (!currentItem) return;
      var id = currentItem.id;
      api("/items/" + id + "/delete").then(function (data) {
        closeDialog(sheet);
        removeCard(id);
        // Undo instead of a confirm dialog: the delete happens at once, and
        // the snapshot the server returned is enough to put it back.
        toast("Record deleted", "Undo", function () {
          api("/items/restore", data.item)
            .then(function () { reloadWith("Record restored"); })
            .catch(toastError);
        });
      }).catch(toastError);
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

  /* ————— Keyboard ————— */
  document.addEventListener("keydown", function (e) {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
      e.preventDefault();
      openPalette();
      return;
    }
    var typing = /^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName) || e.target.isContentEditable;
    if (typing || e.ctrlKey || e.metaKey || e.altKey) return;
    if (sheet && sheet.open) {
      if (e.key === "j") { e.preventDefault(); openSibling(1); }
      else if (e.key === "k") { e.preventDefault(); openSibling(-1); }
      else if (e.key === "p") { e.preventDefault(); togglePin(); }
      else if (e.key === "d") { e.preventDefault(); toggleDone(); }
      else if (e.key === "e") { e.preventDefault(); editCurrent(); }
      return;
    }
    if (document.querySelector("dialog[open]")) return;
    if (e.key === "n" && itemModal) { e.preventDefault(); openDialog("item-modal"); }
    else if (e.key === "/") { e.preventDefault(); openPalette(); }
  });

  /* ————— Search palette (Ctrl/Cmd+K) ————— */
  var palette = document.getElementById("search-modal");
  var searchInput = document.getElementById("search-input");
  var searchResults = document.getElementById("search-results");
  var searchTimer = null;
  var searchSeq = 0;
  var activeIndex = -1;

  var kbd = document.getElementById("search-kbd");
  if (kbd && /Mac|iPhone|iPad/.test(navigator.platform)) kbd.textContent = "⌘K";

  function openPalette() {
    if (!palette || palette.open) return;
    searchInput.value = "";
    searchResults.hidden = true;
    searchResults.textContent = "";
    activeIndex = -1;
    palette.showModal();
    searchInput.focus();
  }
  var searchBtn = document.getElementById("search-btn");
  if (searchBtn) searchBtn.addEventListener("click", openPalette);

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

  function renderResults(results, query) {
    searchResults.textContent = "";
    activeIndex = results.length ? 0 : -1;
    if (!results.length) {
      var empty = document.createElement("p");
      empty.className = "palette-empty";
      empty.textContent = "Nothing matches “" + query + "”.";
      searchResults.appendChild(empty);
      searchResults.hidden = false;
      return;
    }
    var label = document.createElement("p");
    label.className = "palette-label";
    label.textContent = "Records";
    searchResults.appendChild(label);
    results.forEach(function (r, i) {
      var row = document.createElement("div");
      row.className = "palette-item" + (r.done ? " is-done" : "") + (i === 0 ? " is-active" : "");
      row.setAttribute("data-id", r.id);
      var title = document.createElement("span");
      title.className = "palette-item-title";
      title.appendChild(highlight(r.title, query));
      var meta = document.createElement("span");
      meta.className = "palette-item-meta";
      meta.textContent = r.when;
      row.appendChild(title);
      row.appendChild(meta);
      row.addEventListener("click", function () { choose(i); });
      row.addEventListener("mousemove", function () { setActive(i, true); });
      searchResults.appendChild(row);
    });
    searchResults.hidden = false;
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
    var all = rows();
    var pick = all[i === undefined ? activeIndex : i];
    if (!pick) return;
    palette.close();
    openItem(parseInt(pick.getAttribute("data-id"), 10));
  }

  if (searchInput) {
    searchInput.addEventListener("input", function () {
      var query = searchInput.value.trim();
      clearTimeout(searchTimer);
      if (query.length < 2) { searchResults.hidden = true; return; }
      // Debounced, and sequenced so a slow answer to an old query never
      // replaces the answer to the current one.
      searchTimer = setTimeout(function () {
        var seq = ++searchSeq;
        get("/search?q=" + encodeURIComponent(query)).then(function (data) {
          if (seq === searchSeq) renderResults(data.results || [], query);
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
    "item-modal": {
      save: function () {
        return {
          id: document.getElementById("item-id").value,
          title: document.getElementById("item-title").value,
          body: document.getElementById("item-body").value
        };
      },
      restore: function (d, s) {
        openDialog("item-modal");   // resets the form, then the draft goes back in
        document.getElementById("item-id").value = s.id || "";
        document.getElementById("item-title").value = s.title || "";
        document.getElementById("item-body").value = s.body || "";
        document.getElementById("item-modal-title").textContent = s.id ? "Edit record" : "New record";
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
    // The sheet's record lives in the URL (?open=<id>), which also makes it a
    // link; only its scroll offset needs remembering.
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

  var deepLink = parseInt(new URLSearchParams(location.search).get("open"), 10);
  if (deepLink) {
    var sheetState = remembered && remembered.id === "sheet" ? remembered.state || {} : null;
    openItem(deepLink, { restoring: !!sheetState, scroll: sheetState ? sheetState.scroll : 0 });
  } else if (remembered) {
    var toRestore = document.getElementById(remembered.id);
    if (toRestore && toRestore.tagName === "DIALOG" && toRestore.getAttribute("data-restore") !== "off" && remembered.id !== "sheet") {
      markRestoring(toRestore);
      var memory = dialogMemory[remembered.id];
      if (memory) memory.restore(toRestore, remembered.state || {});
      else toRestore.showModal();
    }
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
