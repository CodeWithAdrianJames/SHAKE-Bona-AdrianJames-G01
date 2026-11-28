/*
 * SHAKE "Settle" UI script — offline, dependency-free progressive enhancement.
 *
 * Loaded once from templates/base.html via {% static 'js/shake-ui.js' %} (no CDN, no network requests).
 * Every page still works without it: links navigate, forms POST, and the server enforces POST,
 * CSRF, and ownership. This file only adds:
 *   1. Navigation rail: pinned state (localStorage "shake.sidebar.pinned") and the < 992px drawer.
 *   2. data-confirm prompts on destructive POST forms (delete, archive, revoke).
 *   3. Clipboard copy buttons ([data-shake-copy]) with 1.5 s "Copied" feedback.
 *   4. "/" keyboard shortcut that focuses a list search input ([data-shake-search-shortcut]).
 *   5. Live client-side filtering of the contract rate ledger ([data-shake-ledger]).
 *   6. Upload dropzone: drag-and-drop, selected-file cards, and the downward step highlight.
 *   7. Read-only values marked [data-shake-select-on-focus] select their text on focus (one-time API token).
 */
(function () {
    "use strict";

    var PIN_KEY = "shake.sidebar.pinned";
    var root = document.documentElement;

    function readPinned() {
        try { return window.localStorage.getItem(PIN_KEY) === "1"; } catch (e) { return false; }
    }
    function writePinned(value) {
        try { window.localStorage.setItem(PIN_KEY, value ? "1" : "0"); } catch (e) { /* storage disabled: state lasts for this page only */ }
    }

    // Applied before first paint (this script runs in <head>), so a pinned rail never flashes closed.
    if (readPinned()) { root.classList.add("shake-rail-pinned"); }

    // ------------------------------------------------------------------
    // 2. Confirmation prompt for destructive POST forms. The message comes from the
    //    form's data-confirm attribute (HTML-escaped by Django).
    // ------------------------------------------------------------------
    document.addEventListener("submit", function (event) {
        var form = event.target;
        if (form.matches && form.matches("form[data-confirm]") && !window.confirm(form.getAttribute("data-confirm"))) {
            event.preventDefault();
        }
    });

    function onReady(fn) {
        if (document.readyState === "loading") { document.addEventListener("DOMContentLoaded", fn); } else { fn(); }
    }

    // ------------------------------------------------------------------
    // 1. Navigation rail
    // ------------------------------------------------------------------
    function initRail() {
        var rail = document.querySelector("[data-shake-rail]");
        if (!rail) { return; }
        var backdrop = document.querySelector(".shake-rail-backdrop");
        var openers = document.querySelectorAll("[data-shake-drawer-open]");
        var pin = rail.querySelector("[data-shake-pin]");
        var lastOpener = null;

        function syncPin() {
            if (!pin) { return; }
            var pinned = root.classList.contains("shake-rail-pinned");
            pin.setAttribute("aria-pressed", pinned ? "true" : "false");
            var label = pinned ? "Let the sidebar collapse" : "Keep the sidebar open";
            pin.setAttribute("aria-label", label);
            pin.setAttribute("title", label);
            var icon = pin.querySelector(".ti");
            if (icon) {
                icon.classList.toggle("ti-pin", !pinned);
                icon.classList.toggle("ti-pinned", pinned);
            }
        }
        syncPin();

        if (pin) {
            pin.addEventListener("click", function (event) {
                var pinned = !root.classList.contains("shake-rail-pinned");
                root.classList.toggle("shake-rail-pinned", pinned);
                writePinned(pinned);
                syncPin();
                // A mouse click leaves focus on the button; drop it so :focus-within does not hold the rail open.
                if (!pinned && event.detail > 0) { pin.blur(); }
            });
        }

        function setDrawer(open) {
            rail.classList.toggle("is-open", open);
            root.classList.toggle("shake-drawer-open", open);
            if (backdrop) { backdrop.hidden = !open; }
            Array.prototype.forEach.call(openers, function (btn) { btn.setAttribute("aria-expanded", open ? "true" : "false"); });
            if (open) {
                var first = rail.querySelector(".shake-rail-link");
                if (first) { first.focus(); }
            } else if (lastOpener) {
                lastOpener.focus();
            }
        }

        Array.prototype.forEach.call(openers, function (btn) {
            btn.addEventListener("click", function () { lastOpener = btn; setDrawer(true); });
        });
        Array.prototype.forEach.call(document.querySelectorAll("[data-shake-drawer-close]"), function (el) {
            el.addEventListener("click", function () { setDrawer(false); });
        });
        document.addEventListener("keydown", function (event) {
            if (event.key === "Escape" && rail.classList.contains("is-open")) { setDrawer(false); }
        });
        // Leaving the drawer breakpoint closes it so the desktop rail is never stuck "open".
        if (window.matchMedia) {
            var desktop = window.matchMedia("(min-width: 992px)");
            var onChange = function (mq) { if (mq.matches && rail.classList.contains("is-open")) { setDrawer(false); } };
            if (desktop.addEventListener) { desktop.addEventListener("change", onChange); } else if (desktop.addListener) { desktop.addListener(onChange); }
        }
    }

    // ------------------------------------------------------------------
    // 3. Clipboard copy
    // ------------------------------------------------------------------
    function legacyCopy(text) {
        return new Promise(function (resolve, reject) {
            var area = document.createElement("textarea");
            area.value = text;
            area.setAttribute("readonly", "");
            area.className = "shake-visually-hidden";
            document.body.appendChild(area);
            area.select();
            var ok = false;
            try { ok = document.execCommand("copy"); } catch (e) { ok = false; }
            document.body.removeChild(area);
            if (ok) { resolve(); } else { reject(new Error("copy failed")); }
        });
    }

    // Clipboard API first (127.0.0.1 is a secure context); fall back to execCommand if it is missing or refused.
    function copyText(text) {
        if (navigator.clipboard && window.isSecureContext) {
            return navigator.clipboard.writeText(text).catch(function () { return legacyCopy(text); });
        }
        return legacyCopy(text);
    }

    function initCopy() {
        document.addEventListener("click", function (event) {
            var btn = event.target.closest ? event.target.closest("[data-shake-copy]") : null;
            if (!btn) { return; }
            event.preventDefault();
            var text = btn.getAttribute("data-shake-copy");
            var label = btn.querySelector("[data-shake-copy-label]");
            var original = label ? label.textContent : null;
            copyText(text).then(function () {
                btn.classList.add("is-copied");
                if (label) { label.textContent = "Copied"; }
                var status = document.getElementById("shake-copy-status");
                if (status) { status.textContent = "Copied " + text; }
                window.clearTimeout(btn._shakeCopyTimer);
                btn._shakeCopyTimer = window.setTimeout(function () {
                    btn.classList.remove("is-copied");
                    if (label) { label.textContent = original; }
                }, 1500);
            }).catch(function () {
                if (label) { label.textContent = "Copy failed"; }
                window.setTimeout(function () { if (label) { label.textContent = original; } }, 1500);
            });
        });
    }

    // ------------------------------------------------------------------
    // 4. "/" focuses the list search field
    // ------------------------------------------------------------------
    function isTyping(el) {
        if (!el) { return false; }
        var tag = (el.tagName || "").toLowerCase();
        return tag === "input" || tag === "textarea" || tag === "select" || el.isContentEditable;
    }

    // ------------------------------------------------------------------
    // 7. Select a read-only value on focus (replaces the inline onfocus handler on the new API token).
    // ------------------------------------------------------------------
    function initSelectOnFocus() {
        document.addEventListener("focusin", function (event) {
            var el = event.target;
            if (el && el.matches && el.matches("[data-shake-select-on-focus]") && el.select) { el.select(); }
        });
    }

    function initSearchShortcut() {
        var input = document.querySelector("[data-shake-search-shortcut]");
        if (!input) { return; }
        document.addEventListener("keydown", function (event) {
            if (event.key === "/" && !event.ctrlKey && !event.metaKey && !event.altKey && !isTyping(document.activeElement)) {
                event.preventDefault();
                input.focus();
                if (input.select) { input.select(); }
            } else if (event.key === "Escape" && document.activeElement === input) {
                input.blur();
            }
        });
    }

    // ------------------------------------------------------------------
    // 5. Live client-side table filter ([data-shake-ledger])
    //    Rows:    [data-filter-row] with data-search="..." plus one data-<attr> per filter.
    //    Search:  [data-shake-filter-search]
    //    Selects: [data-shake-filter-select="<attr>"]   (value "ALL" = no filter)
    //    Pills:   [data-shake-pill="<attr>"][data-value] (one group per attr; "ALL" = no filter)
    //    Output:  [data-shake-visible-count], [data-shake-no-match], [data-shake-filter-reset]
    // ------------------------------------------------------------------
    function initLedger() {
        Array.prototype.forEach.call(document.querySelectorAll("[data-shake-ledger]"), function (ledger) {
            var rows = ledger.querySelectorAll("[data-filter-row]");
            var search = ledger.querySelector("[data-shake-filter-search]");
            var selects = ledger.querySelectorAll("[data-shake-filter-select]");
            var pills = ledger.querySelectorAll("[data-shake-pill]");
            var counter = ledger.querySelector("[data-shake-visible-count]");
            var noMatch = ledger.querySelector("[data-shake-no-match]");
            var reset = ledger.querySelector("[data-shake-filter-reset]");
            var pillState = {};

            function criteria() {
                var list = [];
                Array.prototype.forEach.call(selects, function (sel) {
                    if (sel.value !== "ALL") { list.push([sel.getAttribute("data-shake-filter-select"), sel.value]); }
                });
                Object.keys(pillState).forEach(function (attr) {
                    if (pillState[attr] !== "ALL") { list.push([attr, pillState[attr]]); }
                });
                return list;
            }

            function apply() {
                var q = search ? search.value.trim().toLowerCase() : "";
                var active = criteria();
                var shown = 0;
                Array.prototype.forEach.call(rows, function (row) {
                    var match = !q || (row.getAttribute("data-search") || "").indexOf(q) !== -1;
                    for (var i = 0; match && i < active.length; i += 1) {
                        match = row.getAttribute("data-" + active[i][0]) === active[i][1];
                    }
                    row.hidden = !match;
                    if (match) { shown += 1; }
                });
                if (counter) { counter.textContent = String(shown); }
                if (noMatch) { noMatch.hidden = shown !== 0; }
                if (reset) { reset.hidden = !(q || active.length); }
            }

            Array.prototype.forEach.call(pills, function (pill) {
                var attr = pill.getAttribute("data-shake-pill");
                if (!(attr in pillState)) { pillState[attr] = "ALL"; }
                if (pill.classList.contains("is-active")) { pillState[attr] = pill.getAttribute("data-value"); }
                pill.addEventListener("click", function () {
                    pillState[attr] = pill.getAttribute("data-value");
                    Array.prototype.forEach.call(pills, function (p) {
                        if (p.getAttribute("data-shake-pill") !== attr) { return; }
                        var on = p === pill;
                        p.classList.toggle("is-active", on);
                        p.setAttribute("aria-pressed", on ? "true" : "false");
                    });
                    apply();
                });
            });
            if (search) {
                search.addEventListener("input", apply);
                search.addEventListener("keydown", function (event) {
                    if (event.key === "Escape" && search.value) { event.stopPropagation(); search.value = ""; apply(); }
                });
            }
            Array.prototype.forEach.call(selects, function (sel) { sel.addEventListener("change", apply); });
            if (reset) {
                reset.addEventListener("click", function () {
                    if (search) { search.value = ""; }
                    Array.prototype.forEach.call(selects, function (sel) { sel.value = "ALL"; });
                    Array.prototype.forEach.call(pills, function (p) {
                        if (p.getAttribute("data-value") === "ALL") { p.click(); }
                    });
                    apply();
                });
            }
            ledger.classList.add("is-interactive");
            apply();
        });
    }

    // ------------------------------------------------------------------
    // 6. Upload dropzone, selected-file cards, and step highlight
    // ------------------------------------------------------------------
    function formatBytes(bytes) {
        if (bytes < 1024) { return bytes + " B"; }
        if (bytes < 1024 * 1024) { return (bytes / 1024).toFixed(1) + " KB"; }
        return (bytes / (1024 * 1024)).toFixed(1) + " MB";
    }

    function initUpload() {
        var form = document.querySelector("[data-shake-upload]");
        if (!form) { return; }
        var zone = form.querySelector("[data-shake-dropzone]");
        var input = zone ? zone.querySelector('input[type="file"]') : null;
        if (!zone || !input) { return; }
        var list = form.querySelector("[data-shake-file-list]");
        var summary = form.querySelector("[data-shake-file-summary]");
        var steps = document.querySelectorAll("[data-shake-step]");
        var canEditFiles = typeof window.DataTransfer === "function";

        function setStep(current) {
            Array.prototype.forEach.call(steps, function (step) {
                var n = parseInt(step.getAttribute("data-shake-step"), 10);
                step.classList.toggle("is-done", n < current);
                step.classList.toggle("is-current", n === current);
            });
        }

        function removeFile(index) {
            if (!canEditFiles) { input.value = ""; render(); return; }
            var dt = new DataTransfer();
            Array.prototype.forEach.call(input.files, function (file, i) { if (i !== index) { dt.items.add(file); } });
            input.files = dt.files;
            render();
        }

        function render() {
            var files = Array.prototype.slice.call(input.files || []);
            if (list) {
                list.innerHTML = "";
                files.forEach(function (file, i) {
                    var item = document.createElement("li");
                    item.className = "shake-file-card";
                    var isPdf = /\.pdf$/i.test(file.name);
                    var icon = document.createElement("i");
                    icon.className = "ti shake-file-card-icon " + (isPdf ? "ti-file-type-pdf" : "ti-file-x is-rejected");
                    icon.setAttribute("aria-hidden", "true");
                    var body = document.createElement("div");
                    body.className = "shake-file-card-body";
                    var name = document.createElement("div");
                    name.className = "shake-file-card-name";
                    name.textContent = file.name;           // textContent: file names are never parsed as HTML
                    name.title = file.name;
                    var meta = document.createElement("div");
                    meta.className = "shake-file-card-meta";
                    meta.textContent = formatBytes(file.size) + (isPdf ? " · PDF" : " · not a .pdf, will be rejected");
                    body.appendChild(name);
                    body.appendChild(meta);
                    var clear = document.createElement("button");
                    clear.type = "button";
                    clear.className = "btn btn-sm btn-outline-secondary btn-icon";
                    clear.setAttribute("aria-label", "Remove " + file.name);
                    clear.innerHTML = '<i class="ti ti-x" aria-hidden="true"></i>';
                    clear.addEventListener("click", function () { removeFile(i); });
                    item.appendChild(icon);
                    item.appendChild(body);
                    item.appendChild(clear);
                    list.appendChild(item);
                });
                list.hidden = files.length === 0;
            }
            if (summary) {
                var total = files.reduce(function (sum, f) { return sum + f.size; }, 0);
                summary.textContent = files.length
                    ? files.length + " file" + (files.length === 1 ? "" : "s") + " selected · " + formatBytes(total)
                    : "No files selected yet.";
            }
            zone.classList.toggle("has-files", files.length > 0);
            setStep(files.length ? 2 : 1);
        }

        input.addEventListener("change", render);
        ["dragenter", "dragover"].forEach(function (type) {
            zone.addEventListener(type, function (event) { event.preventDefault(); zone.classList.add("is-dragover"); });
        });
        ["dragleave", "drop"].forEach(function (type) {
            zone.addEventListener(type, function () { zone.classList.remove("is-dragover"); });
        });
        zone.addEventListener("drop", function (event) {
            event.preventDefault();
            if (event.dataTransfer && event.dataTransfer.files.length) {
                input.files = event.dataTransfer.files;
                render();
            }
        });
        form.addEventListener("submit", function () {
            if (input.files && input.files.length) {
                form.classList.add("is-extracting");
                setStep(2);
                Array.prototype.forEach.call(steps, function (step) {
                    if (step.getAttribute("data-shake-step") === "2") { step.classList.add("is-working"); }
                });
            }
        });
        render();
    }

    onReady(function () {
        initRail();
        initCopy();
        initSearchShortcut();
        initSelectOnFocus();
        initLedger();
        initUpload();
    });
})();
