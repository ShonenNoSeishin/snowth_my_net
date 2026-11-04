// The Topology page: draws the layout the server computed. No request, no state of its own.
// Only DOM calls and textContent are used (the page's CSP allows no inline script or style).
(function () {
  "use strict";
  var holder = document.getElementById("topo");
  var dataBlock = document.getElementById("topo-data");
  if (!holder || !dataBlock) { return; }
  var data = JSON.parse(dataBlock.textContent);
  var L = data.labels;
  var NS = "http://www.w3.org/2000/svg";
  var svg = document.getElementById("topo-svg");
  var panel = document.getElementById("topo-panel");
  var tools = document.getElementById("topo-tools");
  var legend = document.getElementById("topo-legend");
  var search = document.getElementById("topo-q");
  var BOX = {w: 172, h: 50};

  function el(name, attrs, parent) {
    var node = document.createElementNS(NS, name);
    Object.keys(attrs || {}).forEach(function (k) { node.setAttribute(k, attrs[k]); });
    if (parent) { parent.appendChild(node); }
    return node;
  }
  function html(name, cls, text) {
    var node = document.createElement(name);
    if (cls) { node.className = cls; }
    if (text !== undefined) { node.textContent = text; }
    return node;
  }
  function clip(text, size) { return text.length > size ? text.slice(0, size - 1) + "…" : text; }

  var byId = {};
  data.nodes.forEach(function (n) { byId[n.id] = n; });
  var edges = data.edges.filter(function (e) { return byId[e.a] && byId[e.b]; });
  var incident = {};
  edges.forEach(function (e) {
    (incident[e.a] = incident[e.a] || []).push(e);
    (incident[e.b] = incident[e.b] || []).push(e);
  });

  // ---------------------------------------------------------------- drawing
  var root = el("g", {}, svg);
  var back = el("g", {}, root);      // the dotted line above the nodes with no link
  var wires = el("g", {}, root);
  var ends = el("g", {}, root);      // port names at both ends of a wire
  var boxes = el("g", {}, root);
  var showAll = false;

  var caption = el("text", {"class": "rule-label"});
  var isolated = data.nodes.filter(function (n) { return n.layer < 0; });
  if (isolated.length) {
    var top = Math.min.apply(null, isolated.map(function (n) { return n.y; })) - 70;
    var xs = data.nodes.map(function (n) { return n.x; });
    var rule = el("line", {"class": "rule", x1: Math.min.apply(null, xs) - BOX.w / 2, y1: top,
                           x2: Math.max.apply(null, xs) + BOX.w / 2, y2: top}, back);
    rule.setAttribute("aria-hidden", "true");
    caption.setAttribute("x", Math.min.apply(null, xs) - BOX.w / 2);
    caption.setAttribute("y", top - 8);
    back.appendChild(caption);
    caption.textContent = L.isolated;
  }

  function wireEnds(e) {
    var a = byId[e.a], b = byId[e.b];
    var dx = b.x - a.x, dy = b.y - a.y, len = Math.hypot(dx, dy) || 1;
    var ux = dx / len, uy = dy / len;
    var off = (e.i - (e.n - 1) / 2) * 12;          // parallel cables side by side
    var curved = a.layer === b.layer && Math.abs(dx) > data.grid.dx * 1.05;
    var pa = {x: a.x - uy * off, y: a.y + ux * off}, pb = {x: b.x - uy * off, y: b.y + ux * off};
    if (curved) {
      var sag = 54 + 10 * Math.abs(off);
      pa.y -= BOX.h / 2; pb.y -= BOX.h / 2;
      var mid = {x: (pa.x + pb.x) / 2, y: pa.y - sag};
      return {pa: pa, pb: pb, mid: mid, curved: true, ua: {x: 0, y: -1}, ub: {x: 0, y: -1}};
    }
    function edge(p, ux2, uy2) {                     // where the line leaves the box
      var sx = ux2 === 0 ? Infinity : (BOX.w / 2) / Math.abs(ux2);
      var sy = uy2 === 0 ? Infinity : (BOX.h / 2) / Math.abs(uy2);
      var s = Math.min(sx, sy);
      return {x: p.x + ux2 * s, y: p.y + uy2 * s};
    }
    var from = edge(pa, ux, uy), to = edge(pb, -ux, -uy);
    return {pa: from, pb: to, curved: false, ua: {x: ux, y: uy}, ub: {x: -ux, y: -uy}};
  }

  var wireEls = edges.map(function (e) {
    var path = el("path", {"class": "wire"}, wires);
    var title = el("title", {}, path);
    title.textContent = byId[e.a].label + " " + e.ap + " — " + byId[e.b].label + " " + e.bp +
      " · " + e.proto;
    var pa = el("text", {"class": "port", "text-anchor": "middle"}, ends);
    var pb = el("text", {"class": "port", "text-anchor": "middle"}, ends);
    pa.textContent = clip(e.ap, 14); pb.textContent = clip(e.bp, 14);
    path.addEventListener("click", function (ev) { ev.stopPropagation(); selectEdge(e); });
    return {e: e, path: path, pa: pa, pb: pb};
  });

  var nodeEls = data.nodes.map(function (n) {
    var cls = "node " + n.kind + (n.type ? " t-" + n.type : " t-none") +
      (n.endpoint ? " endpoint" : "") + (n.status && n.status !== "ok" ? " st-" + n.status : "");
    var g = el("g", {"class": cls, tabindex: "0", role: "button",
                     "aria-label": n.label + (n.ip ? " " + n.ip : "")}, boxes);
    el("rect", {"class": "box", x: -BOX.w / 2, y: -BOX.h / 2, width: BOX.w, height: BOX.h,
                rx: 8}, g);
    el("rect", {"class": "band", x: -BOX.w / 2, y: -BOX.h / 2, width: 7, height: BOX.h, rx: 3}, g);
    var name = el("text", {"class": "name", x: -BOX.w / 2 + 16, y: -3}, g);
    name.textContent = clip(n.label, 20);
    var sub = el("text", {"class": "sub", x: -BOX.w / 2 + 16, y: 14}, g);
    sub.textContent = n.kind === "external"
      ? (n.endpoint ? L.endpoint.split(" (")[0] : L.not_polled.split(":")[0])
      : (n.ip || n.typeLabel);
    var title = el("title", {}, g);
    title.textContent = n.label + (n.ip ? " · " + n.ip : "");
    g.addEventListener("pointerdown", function (ev) { startNodeDrag(ev, n); });
    g.addEventListener("pointerenter", function () { hover(n.id); });
    g.addEventListener("pointerleave", function () { hover(null); });
    g.addEventListener("focus", function () { hover(n.id); });
    g.addEventListener("blur", function () { hover(null); });
    g.addEventListener("keydown", function (ev) {
      if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); selectNode(n.id); }
    });
    return {n: n, g: g, name: name, sub: sub};
  });
  var elOf = {};
  nodeEls.forEach(function (x) { elOf[x.n.id] = x; });

  // ---------------------------------------------------------------- view
  var view = {x: 0, y: 0, k: 1};
  var textScale = 0;
  function scaleText() {
    // Zoomed out, a box is too small to read: its name grows (up to what a box can hold) and
    // the small line goes, so an overview still tells which device is which.
    var f = Math.min(2, Math.max(1, Math.round(8 / view.k) / 10));
    if (f === textScale) { return; }
    textScale = f;
    var chars = Math.floor((BOX.w - 24) / (13 * f * 0.58));
    nodeEls.forEach(function (x) {
      x.name.style.fontSize = (13 * f) + "px";
      x.name.textContent = clip(x.n.label, Math.max(6, Math.min(20, chars)));
      x.sub.style.display = f > 1.3 ? "none" : "";
      x.name.setAttribute("y", f > 1.3 ? 5 : -3);
    });
    caption.style.fontSize = (12 * f) + "px";
    wireEls.forEach(function (w) {
      w.pa.style.fontSize = w.pb.style.fontSize = (10.5 * Math.min(f, 1.7)) + "px";
    });
  }
  function render() {
    scaleText();
    root.setAttribute("transform", "translate(" + view.x + "," + view.y + ") scale(" + view.k + ")");
    nodeEls.forEach(function (x) {
      x.g.setAttribute("transform", "translate(" + x.n.x + "," + x.n.y + ")");
    });
    wireEls.forEach(function (w) {
      var p = wireEnds(w.e);
      var d = p.curved
        ? "M" + p.pa.x + "," + p.pa.y + " Q" + p.mid.x + "," + (p.mid.y - 30) + " " + p.pb.x +
          "," + p.pb.y
        : "M" + p.pa.x + "," + p.pa.y + " L" + p.pb.x + "," + p.pb.y;
      w.path.setAttribute("d", d);
      place(w.pa, p.pa, p.ua, p.curved);
      place(w.pb, p.pb, p.ub, p.curved);
    });
  }
  function place(text, point, dir, curved) {
    var gap = curved ? 0 : 30;
    text.setAttribute("x", point.x + dir.x * gap + (curved ? 0 : 0));
    text.setAttribute("y", point.y + dir.y * gap + (curved ? -6 : 4));
  }
  function size() { return {w: holder.clientWidth, h: holder.clientHeight}; }
  function fit() {
    var s = size();
    if (!data.nodes.length || !s.w) { return; }
    var x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    data.nodes.forEach(function (n) {
      x0 = Math.min(x0, n.x - BOX.w / 2); x1 = Math.max(x1, n.x + BOX.w / 2);
      y0 = Math.min(y0, n.y - BOX.h / 2 - 40); y1 = Math.max(y1, n.y + BOX.h / 2);
    });
    var w = x1 - x0 + 60, h = y1 - y0 + 60;
    var all = Math.min(1.4, Math.max(0.1, Math.min(s.w / w, s.h / h)));
    // A drawing too big to be read whole opens at a size that can be read, on the top of the
    // network; the fit button shows all of it.
    var floor = s.w < 700 ? 0.75 : 0.4;
    if (all >= floor || !fitting) {
      view.k = all;
      view.x = s.w / 2 - ((x0 + x1) / 2) * view.k;
      view.y = s.h / 2 - ((y0 + y1) / 2) * view.k;
    } else {
      var start = byId[data.root] || data.nodes[0];
      view.k = floor;
      view.x = s.w / 2 - start.x * view.k;
      view.y = 70 - (y0 + 40) * view.k;
    }
    render();
  }
  var fitting = true;
  function zoomAt(factor, cx, cy) {
    var k = Math.min(3, Math.max(0.1, view.k * factor));
    view.x = cx - (cx - view.x) * (k / view.k);
    view.y = cy - (cy - view.y) * (k / view.k);
    view.k = k; render();
  }
  function centreOn(n) {
    var s = size();
    if (view.k < 0.8) { view.k = 0.8; }
    // on a phone the details slide up over the lower half: keep the device above them
    var cy = (!panel.hidden && s.w < 700) ? s.h * 0.2 : s.h / 2;
    view.x = s.w / 2 - n.x * view.k; view.y = cy - n.y * view.k; render();
  }

  // ---------------------------------------------------------------- pointer: pan, zoom, move
  var pointers = {}, gesture = null, moved = false;
  function localPoint(ev) {
    var box = holder.getBoundingClientRect();
    return {x: ev.clientX - box.left, y: ev.clientY - box.top};
  }
  function startNodeDrag(ev, n) {
    ev.stopPropagation();
    pointers[ev.pointerId] = localPoint(ev);
    gesture = {kind: "node", n: n, sx: ev.clientX, sy: ev.clientY, moved: false};
    svg.setPointerCapture(ev.pointerId);
  }
  svg.addEventListener("pointerdown", function (ev) {
    pointers[ev.pointerId] = localPoint(ev);
    var ids = Object.keys(pointers);
    if (ids.length === 2) {
      var a = pointers[ids[0]], b = pointers[ids[1]];
      gesture = {kind: "pinch", dist: Math.hypot(a.x - b.x, a.y - b.y)};
    } else if (!gesture) {
      gesture = {kind: "pan", sx: ev.clientX, sy: ev.clientY, moved: false};
      holder.classList.add("dragging");
    }
    svg.setPointerCapture(ev.pointerId);
  });
  svg.addEventListener("pointermove", function (ev) {
    if (!gesture || !pointers[ev.pointerId]) { return; }
    var now = localPoint(ev);
    if (gesture.kind === "pinch") {
      pointers[ev.pointerId] = now;
      var ids = Object.keys(pointers);
      if (ids.length < 2) { return; }
      var a = pointers[ids[0]], b = pointers[ids[1]];
      var dist = Math.hypot(a.x - b.x, a.y - b.y);
      if (gesture.dist) { zoomAt(dist / gesture.dist, (a.x + b.x) / 2, (a.y + b.y) / 2); }
      gesture.dist = dist;
      return;
    }
    var dx = ev.clientX - gesture.sx, dy = ev.clientY - gesture.sy;
    if (!gesture.moved && Math.hypot(dx, dy) < 4) { return; }
    gesture.moved = true; moved = true;
    gesture.sx = ev.clientX; gesture.sy = ev.clientY;
    if (gesture.kind === "node") { gesture.n.x += dx / view.k; gesture.n.y += dy / view.k; }
    else { view.x += dx; view.y += dy; }
    render();
  });
  function release(ev) {
    delete pointers[ev.pointerId];
    if (gesture && gesture.kind === "node" && !gesture.moved) { selectNode(gesture.n.id); }
    if (!Object.keys(pointers).length) {
      var wasPan = gesture && gesture.kind === "pan" && !gesture.moved;
      gesture = null; holder.classList.remove("dragging");
      if (wasPan) { clear(); }
      setTimeout(function () { moved = false; }, 0);
    }
  }
  svg.addEventListener("pointerup", release);
  svg.addEventListener("pointercancel", release);
  svg.addEventListener("wheel", function (ev) {
    ev.preventDefault();
    var p = localPoint(ev);
    zoomAt(ev.deltaY < 0 ? 1.12 : 1 / 1.12, p.x, p.y);
  }, {passive: false});
  window.addEventListener("resize", function () { render(); });

  // ---------------------------------------------------------------- selection and highlight
  var selected = null, hovered = null;
  function relevant() {
    var focus = hovered || selected;
    var nodes = {}, wiresOn = {};
    if (!focus) { return null; }
    if (focus.charAt(0) === "e") {                     // a wire
      var e = edges[parseInt(focus.slice(1), 10)];
      nodes[e.a] = nodes[e.b] = true; wiresOn[focus] = true;
      return {nodes: nodes, wires: wiresOn};
    }
    nodes[focus] = true;
    (incident[focus] || []).forEach(function (e) {
      nodes[e.a] = nodes[e.b] = true; wiresOn["e" + edges.indexOf(e)] = true;
    });
    return {nodes: nodes, wires: wiresOn};
  }
  var query = "";
  var hits = null;
  function paint() {
    var on = relevant();
    nodeEls.forEach(function (x) {
      var id = x.n.id;
      x.g.classList.toggle("sel", selected === id);
      x.g.classList.toggle("dim", (!!on && !on.nodes[id]) || (!!hits && !hits.nodes[id]));
      x.g.classList.toggle("hit", !!hits && !!hits.nodes[id]);
    });
    wireEls.forEach(function (w, i) {
      var id = "e" + i;
      var lit = !!on && !!on.wires[id];
      w.path.classList.toggle("lit", lit || (!!hits && !!hits.wires[id]));
      w.path.classList.toggle("dim", (!!on && !lit) || (!!hits && !hits.wires[id]));
      var visible = showAll || lit || (!!hits && !!hits.wires[id]);
      w.pa.classList.toggle("show", visible); w.pb.classList.toggle("show", visible);
    });
  }
  function hover(id) { hovered = id; paint(); }
  function clear() {
    selected = null; panel.hidden = true; paint();
    try { history.replaceState(null, "", location.pathname + location.search); } catch (e) { /* */ }
  }
  function selectNode(id) {
    selected = id; showNode(byId[id]); paint();
    try { history.replaceState(null, "", "#" + id); } catch (e) { /* */ }
  }
  function selectEdge(e) {
    selected = "e" + edges.indexOf(e); showEdge(e); paint();
  }

  function row(list, label, value) {
    if (!value) { return; }
    list.appendChild(html("dt", "", label));
    list.appendChild(html("dd", "", value));
  }
  function link(text, href) {
    var a = html("a", "", text); a.href = href; return a;
  }
  function frame(title, sub) {
    panel.replaceChildren();
    var close = html("button", "close", "×");
    close.type = "button"; close.title = L.close; close.setAttribute("aria-label", L.close);
    close.addEventListener("click", clear);
    panel.appendChild(close);
    panel.appendChild(html("h2", "", title));
    if (sub) { panel.appendChild(html("p", "sub", sub)); }
    panel.hidden = false;
  }
  function neighbourItem(list, other, mine, theirs, proto) {
    var li = html("li");
    var button = html("button", "go", other.label);
    button.type = "button";
    button.addEventListener("click", function () { selectNode(other.id); centreOn(other); });
    li.appendChild(button);
    li.appendChild(html("span", "via", " " + mine + " ↔ " + theirs + " · " + proto));
    list.appendChild(li);
  }
  function showNode(n) {
    frame(n.label, n.kind === "external" ? (n.endpoint ? L.endpoint : L.not_polled) : n.typeLabel);
    var dl = html("dl");
    row(dl, L.ip, n.ip);
    row(dl, L.vendor, n.vendor);
    row(dl, L.model, n.model);
    row(dl, L.os, n.os);
    row(dl, L.status, n.statusLabel);
    if (n.ports) { row(dl, L.ports, L.ports_up.replace("{up}", n.up).replace("{ports}", n.ports)); }
    row(dl, L.seen, n.seen);
    panel.appendChild(dl);
    var near = incident[n.id] || [];
    if (near.length) {
      panel.appendChild(html("h3", "", L.neighbors + " (" + near.length + ")"));
      var ul = html("ul", "near");
      near.forEach(function (e) {
        var mine = e.a === n.id ? e.ap : e.bp, theirs = e.a === n.id ? e.bp : e.ap;
        neighbourItem(ul, byId[e.a === n.id ? e.b : e.a], mine, theirs, e.proto);
      });
      panel.appendChild(ul);
    }
    if (n.href) {
      var p = html("p", "open"); p.appendChild(link(L.open, n.href)); panel.appendChild(p);
    }
  }
  function showEdge(e) {
    frame(byId[e.a].label + " — " + byId[e.b].label, e.proto);
    var dl = html("dl");
    row(dl, byId[e.a].label, e.ap);
    row(dl, byId[e.b].label, e.bp);
    row(dl, L.seen, e.seen);
    panel.appendChild(dl);
  }

  // ---------------------------------------------------------------- search
  function runSearch() {
    query = search ? search.value.trim().toLowerCase() : "";
    if (!query) { hits = null; paint(); return 0; }
    var found = {nodes: {}, wires: {}}, count = 0;
    data.nodes.forEach(function (n) {
      var text = [n.label, n.ip, n.vendor, n.model, n.os, n.typeLabel].join(" ").toLowerCase();
      if (text.indexOf(query) >= 0) { found.nodes[n.id] = true; count++; }
    });
    edges.forEach(function (e, i) {
      if ((e.ap + " " + e.bp).toLowerCase().indexOf(query) >= 0) {
        found.wires["e" + i] = true; found.nodes[e.a] = found.nodes[e.b] = true; count++;
      }
    });
    hits = found; paint(); return count;
  }
  if (search) {
    search.addEventListener("input", runSearch);
    search.addEventListener("keydown", function (ev) {
      if (ev.key === "Enter" && hits) {
        var first = data.nodes.filter(function (n) { return hits.nodes[n.id]; })[0];
        if (first) { selectNode(first.id); centreOn(first); }
      }
      if (ev.key === "Escape") { search.value = ""; runSearch(); search.blur(); }
    });
  }
  document.addEventListener("keydown", function (ev) {
    var typing = /^(INPUT|SELECT|TEXTAREA)$/.test(document.activeElement.tagName);
    if (ev.key === "/" && !typing && search) { ev.preventDefault(); search.focus(); return; }
    if (typing || ev.ctrlKey || ev.metaKey || ev.altKey) { return; }
    var s = size(), step = 60;
    if (ev.key === "Escape") { clear(); }
    else if (ev.key === "+" || ev.key === "=") { zoomAt(1.2, s.w / 2, s.h / 2); }
    else if (ev.key === "-") { zoomAt(1 / 1.2, s.w / 2, s.h / 2); }
    else if (ev.key === "0") { fit(); }
    else if (document.activeElement === holder && ev.key.indexOf("Arrow") === 0) {
      ev.preventDefault();
      if (ev.key === "ArrowLeft") { view.x += step; }
      if (ev.key === "ArrowRight") { view.x -= step; }
      if (ev.key === "ArrowUp") { view.y += step; }
      if (ev.key === "ArrowDown") { view.y -= step; }
      render();
    }
  });

  // ---------------------------------------------------------------- tools and legend
  function tool(text, label, action) {
    var b = html("button", "", text);
    b.type = "button"; b.title = label; b.setAttribute("aria-label", label);
    b.addEventListener("click", action);
    tools.appendChild(b);
    return b;
  }
  tool("+", L.zoom_in, function () { var s = size(); zoomAt(1.25, s.w / 2, s.h / 2); });
  tool("−", L.zoom_out, function () { var s = size(); zoomAt(1 / 1.25, s.w / 2, s.h / 2); });
  tool("⤢", L.fit, function () { fitting = false; fit(); fitting = true; });
  var labelsButton = tool("⇄", L.port_names, function () {
    showAll = !showAll;
    labelsButton.setAttribute("aria-pressed", showAll ? "true" : "false");
    paint();
  });
  labelsButton.setAttribute("aria-pressed", "false");

  var types = {};
  data.nodes.forEach(function (n) {
    if (n.kind === "device") { types[n.type || "none"] = n.typeLabel || "—"; }
  });
  Object.keys(types).sort().forEach(function (t) {
    var item = html("span", "key t-" + t);
    item.appendChild(html("i"));
    item.appendChild(document.createTextNode(types[t]));
    legend.appendChild(item);
  });
  if (data.nodes.some(function (n) { return n.kind === "external"; })) {
    var ext = html("span", "key external");
    ext.appendChild(html("i"));
    ext.appendChild(document.createTextNode(L.not_polled.split(":")[0]));
    legend.appendChild(ext);
  }

  render();
  fit();
  var wanted = location.hash.slice(1);
  if (wanted && byId[wanted]) { selectNode(wanted); }
  paint();
})();
