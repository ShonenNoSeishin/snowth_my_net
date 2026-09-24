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

  Array.prototype.forEach.call(table.tHead.rows[0].cells, function (th, index) {
    th.querySelector("button").addEventListener("click", function () {
      var ascending = th.getAttribute("aria-sort") !== "ascending";
      Array.prototype.forEach.call(table.tHead.rows[0].cells, function (other) {
        other.removeAttribute("aria-sort");
      });
      th.setAttribute("aria-sort", ascending ? "ascending" : "descending");
      rows.sort(function (a, b) {
        var x = a.cells[index].textContent.trim(), y = b.cells[index].textContent.trim();
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
        var text = row.textContent.toLowerCase();
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
