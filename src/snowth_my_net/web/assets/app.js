// Light or dark, remembered in this browser only. Runs before anything else paints.
(function () {
  var root = document.documentElement;
  var saved = null;
  try { saved = localStorage.getItem("snowth_theme"); } catch (error) { saved = null; }
  if (saved === "dark" || saved === "light") { root.dataset.theme = saved; }
  var button = document.getElementById("theme");
  if (!button) { return; }
  button.addEventListener("click", function () {
    var dark = root.dataset.theme
      ? root.dataset.theme === "dark"
      : window.matchMedia("(prefers-color-scheme: dark)").matches;
    root.dataset.theme = dark ? "light" : "dark";
    try { localStorage.setItem("snowth_theme", root.dataset.theme); } catch (error) { /* private */ }
  });
})();

// Filter and sort the table already rendered by the server. No request, no state.
(function () {
  var table = document.getElementById("rows");
  if (!table) { return; }
  var body = table.tBodies[0];
  var rows = Array.prototype.slice.call(body.rows);
  var collator = new Intl.Collator(undefined, {numeric: true, sensitivity: "base"});
  var input = document.getElementById("q");
  var count = document.getElementById("count");
  var total = rows.length;

  // A cell holding a form holds its text in an input: filter and sort must look there too.
  function cellText(cell) {
    var field = cell.querySelector("input[name=name]");
    return (field ? field.value : cell.textContent).trim();
  }

  function rowText(row) {
    var written = Array.prototype.map.call(row.querySelectorAll("input[name=name]"), function (i) {
      return i.value;
    }).join(" ");
    return (row.textContent + " " + written).toLowerCase();
  }

  Array.prototype.forEach.call(table.tHead.rows[0].cells, function (th, index) {
    th.querySelector("button").addEventListener("click", function () {
      var ascending = th.getAttribute("aria-sort") !== "ascending";
      Array.prototype.forEach.call(table.tHead.rows[0].cells, function (other) {
        other.removeAttribute("aria-sort");
      });
      th.setAttribute("aria-sort", ascending ? "ascending" : "descending");
      rows.sort(function (a, b) {
        var x = cellText(a.cells[index]), y = cellText(b.cells[index]);
        if (x === "" || y === "") { return x === y ? 0 : (x === "" ? 1 : -1); }
        return (ascending ? 1 : -1) * collator.compare(x, y);
      });
      rows.forEach(function (row) { body.appendChild(row); });
    });
  });

  if (input) {
    input.addEventListener("input", function () {
      var words = input.value.toLowerCase().split(/\s+/).filter(Boolean);
      var shown = 0;
      rows.forEach(function (row) {
        var text = rowText(row);
        var visible = words.every(function (word) { return text.indexOf(word) !== -1; });
        row.hidden = !visible;
        if (visible) { shown += 1; }
      });
      count.textContent = shown === total ? count.dataset.all || count.textContent
                                          : shown + " / " + total;
    });
    count.dataset.all = count.textContent;
    document.addEventListener("keydown", function (event) {
      if (event.key === "/" && document.activeElement !== input) {
        event.preventDefault();
        input.focus();
      }
    });
  }
})();

// Names written straight in the table. The forms work on their own (a submit reloads the page);
// this only saves them where the reader is, without losing their filter, their sort or their
// place in a long list.
(function () {
  var forms = document.querySelectorAll("form.cell");
  if (!forms.length || !window.fetch) { return; }
  Array.prototype.forEach.call(forms, function (form) {
    var field = form.querySelector('input[name="name"]');
    var saved = field.value;

    function save() {
      if (field.value === saved) { return; }
      var body = new URLSearchParams(new FormData(form));
      form.classList.remove("saved", "bad");
      fetch(form.action, {
        method: "POST",
        headers: {"Accept": "application/json",
                  "Content-Type": "application/x-www-form-urlencoded"},
        body: body.toString(),
        credentials: "same-origin"
      }).then(function (response) {
        return response.json().then(function (data) { return {ok: response.ok, data: data}; });
      }).then(function (answer) {
        if (!answer.ok) { throw new Error(answer.data.error || "refused"); }
        field.value = answer.data.name;        // as it was stored: trimmed, one line
        saved = field.value;
        field.removeAttribute("title");
        form.classList.add("saved");
        setTimeout(function () { form.classList.remove("saved"); }, 1200);
      }).catch(function (error) {
        form.classList.add("bad");
        field.title = String(error.message || error);
      });
    }

    form.addEventListener("submit", function (event) { event.preventDefault(); save(); });
    field.addEventListener("blur", save);
    field.addEventListener("keydown", function (event) {
      if (event.key === "Escape") { field.value = saved; field.blur(); }
    });
  });
})();

// Reading a table: the full text of what was cut, columns one can resize, and a choice of which
// ones to show. All of it lives in this browser (localStorage), per page, and the page works
// without any of it.
(function () {
  var table = document.getElementById("rows");
  if (!table || !table.tHead) { return; }
  var head = table.tHead.rows[0];
  var page = location.pathname;

  function key(name) { return "snowth_" + name + "_" + page; }

  function remember(name, value) {
    try { localStorage.setItem(key(name), JSON.stringify(value)); } catch (error) { /* private */ }
  }

  function recall(name, fallback) {
    try {
      var saved = localStorage.getItem(key(name));
      return saved ? JSON.parse(saved) : fallback;
    } catch (error) { return fallback; }
  }

  function columnOf(cell) {                       // "col-vendor" -> "vendor"
    var found = String(cell.className).match(/col-([a-z_]+)/);
    return found ? found[1] : null;
  }

  var names = Array.prototype.map.call(head.cells, columnOf);

  // --- The whole value of a cell that had to be cut, on hover. Only when it is really cut, so
  //     a tooltip never appears over something already fully readable.
  function markTruncated() {
    Array.prototype.forEach.call(table.tBodies[0].rows, function (row) {
      Array.prototype.forEach.call(row.cells, function (cell) {
        if (cell.querySelector("input, details")) { return; }   // it holds its own content
        var cut = cell.scrollWidth > cell.clientWidth + 1;
        if (cut && !cell.dataset.kept) {
          cell.dataset.kept = cell.getAttribute("title") || "";
          cell.title = cell.textContent.trim();
        } else if (!cut && cell.dataset.kept !== undefined) {
          if (cell.dataset.kept) { cell.title = cell.dataset.kept; }
          else { cell.removeAttribute("title"); }
          delete cell.dataset.kept;
        }
      });
    });
  }

  // --- Widths, dragged on the edge of a heading and kept for next time.
  function applyWidth(index, px) {
    var width = px + "px";
    head.cells[index].style.width = width;
    head.cells[index].style.maxWidth = width;
    Array.prototype.forEach.call(table.tBodies[0].rows, function (row) {
      if (row.cells[index]) { row.cells[index].style.maxWidth = width; }
    });
  }

  var widths = recall("widths", {});
  names.forEach(function (name, index) {
    if (name && widths[name]) { applyWidth(index, widths[name]); }
    var grab = document.createElement("span");
    grab.className = "grab";
    grab.setAttribute("aria-hidden", "true");
    head.cells[index].appendChild(grab);
    grab.addEventListener("pointerdown", function (event) {
      event.preventDefault();
      event.stopPropagation();
      var startX = event.clientX;
      var startWidth = head.cells[index].getBoundingClientRect().width;

      function move(moved) {
        var px = Math.max(40, Math.round(startWidth + moved.clientX - startX));
        applyWidth(index, px);
        if (name) { widths[name] = px; }
      }

      function done() {
        document.removeEventListener("pointermove", move);
        document.removeEventListener("pointerup", done);
        remember("widths", widths);
        markTruncated();
      }

      document.addEventListener("pointermove", move);
      document.addEventListener("pointerup", done);
    });
  });

  // --- Which columns to show.
  var chooser = document.getElementById("cols");
  if (!chooser) { return; }
  var hidden = recall("hidden", []);

  function show(index, visible) {
    head.cells[index].hidden = !visible;
    Array.prototype.forEach.call(table.tBodies[0].rows, function (row) {
      if (row.cells[index]) { row.cells[index].hidden = !visible; }
    });
  }

  var pick = chooser.querySelector(".pick");
  var reset = chooser.querySelector(".reset");
  names.forEach(function (name, index) {
    if (!name) { return; }
    var label = document.createElement("label");
    var box = document.createElement("input");
    box.type = "checkbox";
    box.checked = hidden.indexOf(name) === -1;
    box.addEventListener("change", function () {
      hidden = hidden.filter(function (other) { return other !== name; });
      if (!box.checked) { hidden.push(name); }
      remember("hidden", hidden);
      show(index, box.checked);
      markTruncated();
    });
    label.appendChild(box);
    label.appendChild(document.createTextNode(
      " " + head.cells[index].textContent.trim()));
    pick.insertBefore(label, reset);          // the button stays last in the panel
    show(index, box.checked);
  });
  reset.addEventListener("click", function () {
    names.forEach(function (name, index) {
      head.cells[index].style.width = "";
      head.cells[index].style.maxWidth = "";
      Array.prototype.forEach.call(table.tBodies[0].rows, function (row) {
        if (row.cells[index]) { row.cells[index].style.maxWidth = ""; }
      });
    });
    widths = {};
    remember("widths", widths);
    markTruncated();
  });
  chooser.hidden = false;

  markTruncated();
  window.addEventListener("resize", markTruncated);
})();

// The device and root choosers are plain GET forms; choosing is enough to submit them.
(function () {
  ["device", "root"].forEach(function (id) {
    var select = document.getElementById(id);
    if (select && select.form) {
      select.addEventListener("change", function () {
        if (select.value) { select.form.submit(); }
      });
    }
  });
})();
