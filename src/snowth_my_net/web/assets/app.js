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
    var field = cell.querySelector("input[name]");
    return (field ? field.value : cell.textContent).trim();
  }

  function rowText(row) {
    var written = Array.prototype.map.call(row.querySelectorAll("input[name]"), function (i) {
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
