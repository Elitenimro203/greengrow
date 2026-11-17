// ============================================================
// GreenGrow — Tableau de bord
// ============================================================
// Du JavaScript simple, sans bibliothèque ni étape de compilation : ce que
// tu lis ici est exactement ce que le navigateur exécute.
//
// Trois règles suivies partout dans ce fichier :
//   1. La page ne contient AUCUNE donnée : elle demande tout à l'API, avec
//      le cookie de session. Sans connexion, l'API répond 401 et on affiche
//      le formulaire.
//   2. Tout texte venu du serveur est écrit avec textContent, jamais avec
//      innerHTML. Si un nom de bac contenait "<script>...", il s'afficherait
//      tel quel au lieu d'être exécuté (protection contre le XSS).
//   3. L'interface cache les boutons interdits à un lecteur, mais ce n'est
//      que du confort : la vraie vérification est faite par l'API.
// ============================================================
"use strict";

const REFRESH_MS = 5000;
const $ = (id) => document.getElementById(id);

const state = {
  user: null,
  bacs: [],
  selected: null,
  timer: null,
  watching: null, // identifiant de la commande dont on attend la réponse
  duration: 10,
  charts: {}, // dernières données dessinées, pour redessiner si la fenêtre change de taille
};

// ---------- Appels à l'API ----------

class ApiError extends Error {
  constructor(status, detail) {
    super(detail);
    this.status = status;
  }
}

async function api(path, options = {}) {
  const init = { method: options.method || "GET", headers: {}, credentials: "same-origin" };
  if (options.body !== undefined) {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(options.body);
  }
  const response = await fetch(path, init);
  if (response.status === 204) return null;
  let data = null;
  try {
    data = await response.json();
  } catch (e) {
    /* réponse sans JSON */
  }
  if (!response.ok) {
    const detail = data && typeof data.detail === "string" ? data.detail : "Erreur " + response.status;
    throw new ApiError(response.status, detail);
  }
  return data;
}

// ---------- Petits outils d'affichage ----------

const SVG = "http://www.w3.org/2000/svg";

function el(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined && text !== null) node.textContent = text;
  if (className) node.className = className;
  return node;
}

function svg(tag, attrs, text) {
  const node = document.createElementNS(SVG, tag);
  for (const key in attrs) node.setAttribute(key, attrs[key]);
  if (text !== undefined) node.textContent = text;
  return node;
}

function icon(name) {
  const node = svg("svg", { "aria-hidden": "true" });
  node.appendChild(svg("use", { href: "#i-" + name }));
  return node;
}

function clear(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
}

// Le serveur parle en UTC ; le navigateur convertit à l'heure locale.
function clock(date, withSeconds) {
  const options = { hour: "2-digit", minute: "2-digit" };
  if (withSeconds) options.second = "2-digit";
  return new Date(date).toLocaleTimeString("fr-FR", options);
}

function ago(iso) {
  const seconds = Math.max(0, Math.round((Date.now() - Date.parse(iso)) / 1000));
  if (seconds < 10) return "à l'instant";
  if (seconds < 60) return "il y a " + seconds + " s";
  if (seconds < 3600) return "il y a " + Math.round(seconds / 60) + " min";
  if (seconds < 86400) return "il y a " + Math.round(seconds / 3600) + " h";
  return "le " + new Date(iso).toLocaleDateString("fr-FR", { day: "numeric", month: "short" });
}

function num(value, digits) {
  return value.toLocaleString("fr-FR", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

const COMMANDS = { pump_on: "Arrosage", pump_off: "Arrêt de la pompe", reset_fault: "Sortie du mode sécurité" };
const STATUS = {
  sent: ["en attente du bac…", "wait"],
  executed: ["exécutée", "ok"],
  rejected: ["refusée par le bac", "ko"],
  expired: ["sans réponse du bac", "ko"],
};
const REASONS = {
  reservoir_empty: "réservoir vide",
  fault: "bac en mode sécurité",
  daily_limit: "limite d'arrosages par jour atteinte",
  already_watering: "un arrosage est déjà en cours",
  expired: "commande arrivée trop tard",
  duplicate: "commande déjà reçue",
  no_clock: "le bac n'a pas encore l'heure",
  expiry_too_far: "heure limite invalide",
  unknown_type: "commande inconnue du bac",
};
// type d'événement -> [texte, couleur du point]
const EVENTS = {
  watering_started: ["Arrosage démarré", "info"],
  watering_stopped_target: ["Arrosage terminé : humidité atteinte", "ok"],
  watering_stopped_max_duration: ["Arrosage arrêté : durée maximale", "info"],
  watering_stopped_reservoir_empty: ["Arrosage interrompu : réservoir vide", "ko"],
  watering_stopped_manual: ["Arrosage arrêté à la main", "info"],
  fault_no_moisture_rise: ["Mode sécurité : le sol ne s'humidifie pas", "ko"],
  fault_sensor: ["Mode sécurité : capteur en panne", "ko"],
  fault_cleared: ["Sortie du mode sécurité", "ok"],
  daily_limit_reached: ["Limite d'arrosages par jour atteinte", "wait"],
  reservoir_empty: ["Réservoir vide", "ko"],
  reservoir_ok: ["Réservoir rempli", "ok"],
};

// ---------- Graphiques ----------
// Dessinés à la main en SVG : une courbe et son aire, une grille discrète,
// la zone idéale, les moments où la pompe tournait, et la valeur exacte au
// survol. Aucune bibliothèque : rien à télécharger depuis un autre site.

function niceTicks(min, max, count) {
  const raw = (max - min) / count;
  const power = Math.pow(10, Math.floor(Math.log10(raw)));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * power).find((s) => s >= raw) || raw;
  const ticks = [];
  for (let v = Math.ceil(min / step) * step; v <= max + 1e-9; v += step) ticks.push(Math.round(v * 100) / 100);
  return ticks;
}

function drawChart(id, points, options) {
  state.charts[id] = { points: points, options: options };
  const target = $(id);
  const tooltip = target.parentNode.querySelector(".tooltip");
  clear(target);
  tooltip.hidden = true;

  const W = Math.max(280, target.clientWidth), H = 200;
  const left = 34, right = 46, top = 12, bottom = 24;
  target.setAttribute("viewBox", "0 0 " + W + " " + H);
  if (points.length < 2) {
    target.appendChild(svg("text", { x: W / 2, y: H / 2, "text-anchor": "middle", class: "empty-text" }, "En attente des premières mesures…"));
    return;
  }

  const refs = (options.zone ? [options.zone.low, options.zone.high] : []).concat(options.limit != null ? [options.limit] : []);
  const values = points.map((p) => p.v).concat(refs);
  let min = Math.min.apply(null, values), max = Math.max.apply(null, values);
  const pad = Math.max(1, (max - min) * 0.12);
  min = Math.max(options.floor != null ? options.floor : -Infinity, min - pad);
  max = Math.min(options.ceil != null ? options.ceil : Infinity, max + pad);
  const t0 = points[0].t, t1 = points[points.length - 1].t;
  const x = (t) => left + ((t - t0) / Math.max(1, t1 - t0)) * (W - left - right);
  const y = (v) => top + (1 - (v - min) / (max - min)) * (H - top - bottom);
  const base = H - bottom;

  // Zone idéale (entre le seuil bas et le seuil haut)
  if (options.zone) {
    const zTop = y(options.zone.high), zBottom = y(options.zone.low);
    target.appendChild(svg("rect", { class: "zone", x: left, y: zTop, width: W - left - right, height: zBottom - zTop }));
    target.appendChild(svg("line", { class: "zone-edge", x1: left, x2: W - right, y1: zTop, y2: zTop }));
    target.appendChild(svg("line", { class: "zone-edge", x1: left, x2: W - right, y1: zBottom, y2: zBottom }));
  }
  // Grille et graduations
  for (const tick of niceTicks(min, max, 4)) {
    target.appendChild(svg("line", { class: "grid-line", x1: left, x2: W - right, y1: y(tick), y2: y(tick) }));
    target.appendChild(svg("text", { class: "axis", x: left - 8, y: y(tick) + 4, "text-anchor": "end" }, num(tick, tick % 1 ? 1 : 0)));
  }
  const xTicks = W < 420 ? 2 : 4;
  for (let i = 0; i <= xTicks; i++) {
    const t = t0 + ((t1 - t0) * i) / xTicks;
    const anchor = i === 0 ? "start" : i === xTicks ? "end" : "middle";
    target.appendChild(svg("text", { class: "axis", x: x(t), y: H - 6, "text-anchor": anchor }, clock(t, t1 - t0 < 180000)));
  }
  // Moments où la pompe tournait
  for (let i = 0; i < points.length - 1; i++) {
    if (points[i].pump) {
      target.appendChild(svg("rect", {
        class: "pump", x: x(points[i].t), y: top, width: Math.max(1, x(points[i + 1].t) - x(points[i].t)), height: base - top,
      }));
    }
  }
  // Limite à ne pas dépasser (température maximale)
  if (options.limit != null) {
    target.appendChild(svg("line", { class: "limit", x1: left, x2: W - right, y1: y(options.limit), y2: y(options.limit) }));
    target.appendChild(svg("text", { class: "ref-label", x: left + 6, y: y(options.limit) - 5 }, options.limitLabel));
  }
  // Aire + courbe
  const line = points.map((p, i) => (i ? "L" : "M") + x(p.t).toFixed(1) + " " + y(p.v).toFixed(1)).join(" ");
  target.appendChild(svg("path", { class: "area", d: line + " L" + x(t1).toFixed(1) + " " + base + " L" + x(t0).toFixed(1) + " " + base + " Z" }));
  target.appendChild(svg("path", { class: "line", d: line }));
  // Dernier point, avec sa valeur écrite à côté
  const last = points[points.length - 1];
  target.appendChild(svg("circle", { class: "end-dot", cx: x(last.t), cy: y(last.v), r: 4.5 }));
  target.appendChild(svg("text", { class: "end-label", x: x(last.t) + 9, y: y(last.v) + 4 }, num(last.v, options.digits) + options.unit));

  // Survol : une ligne verticale se cale sur la mesure la plus proche.
  const cross = svg("line", { class: "cross", y1: top, y2: base, visibility: "hidden" });
  const dot = svg("circle", { class: "end-dot", r: 4.5, visibility: "hidden" });
  target.appendChild(cross);
  target.appendChild(dot);
  const hit = svg("rect", { x: left, y: top, width: W - left - right, height: base - top, fill: "transparent" });
  target.appendChild(hit);

  function show(event) {
    const box = target.getBoundingClientRect();
    const px = ((event.clientX - box.left) / box.width) * W;
    let nearest = points[0];
    for (const p of points) if (Math.abs(x(p.t) - px) < Math.abs(x(nearest.t) - px)) nearest = p;
    const cx = x(nearest.t);
    cross.setAttribute("x1", cx);
    cross.setAttribute("x2", cx);
    cross.setAttribute("visibility", "visible");
    dot.setAttribute("cx", cx);
    dot.setAttribute("cy", y(nearest.v));
    dot.setAttribute("visibility", "visible");
    clear(tooltip);
    tooltip.appendChild(el("strong", num(nearest.v, options.digits) + options.unit));
    tooltip.appendChild(el("span", clock(nearest.t, true) + (nearest.pump ? " · pompe en marche" : "")));
    tooltip.hidden = false;
    const ratio = cx / W;
    tooltip.style.left = ratio * 100 + "%";
    tooltip.style.transform = "translateX(" + (ratio > 0.6 ? "calc(-100% - 10px)" : "10px") + ")";
  }
  function hide() {
    cross.setAttribute("visibility", "hidden");
    dot.setAttribute("visibility", "hidden");
    tooltip.hidden = true;
  }
  hit.addEventListener("pointermove", show);
  hit.addEventListener("pointerdown", show);
  hit.addEventListener("pointerleave", hide);
}

function drawSpark(id, values) {
  const target = $(id);
  clear(target);
  if (values.length < 2) return;
  const W = Math.max(60, target.clientWidth), H = 26;
  target.setAttribute("viewBox", "0 0 " + W + " " + H);
  const min = Math.min.apply(null, values), max = Math.max.apply(null, values);
  const x = (i) => 3 + (i / (values.length - 1)) * (W - 8);
  const y = (v) => 4 + (1 - (v - min) / Math.max(1, max - min)) * (H - 8);
  target.appendChild(svg("polyline", { points: values.map((v, i) => x(i).toFixed(1) + "," + y(v).toFixed(1)).join(" ") }));
  target.appendChild(svg("circle", { cx: x(values.length - 1), cy: y(values[values.length - 1]), r: 3 }));
}

let resizeTimer = null;
window.addEventListener("resize", () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => {
    for (const id in state.charts) drawChart(id, state.charts[id].points, state.charts[id].options);
  }, 150);
});

// ---------- Connexion ----------

function showLogin(message) {
  stopRefresh();
  state.user = null;
  $("app-view").hidden = true;
  $("login-view").hidden = false;
  $("login-error").textContent = message || "";
  $("login-password").value = "";
}

async function showApp(user) {
  state.user = user;
  $("login-view").hidden = true;
  $("app-view").hidden = false;
  $("user-name").textContent = user.nom;
  $("user-role").textContent = user.role === "owner" ? "Propriétaire" : "Lecture seule";
  $("controls").hidden = user.role !== "owner";
  await refresh();
  startRefresh();
}

$("login-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  $("login-error").textContent = "";
  try {
    const user = await api("/api/auth/login", {
      method: "POST",
      body: { email: $("login-email").value, password: $("login-password").value },
    });
    await showApp(user);
  } catch (error) {
    $("login-error").textContent = error instanceof ApiError ? error.message : "Serveur injoignable";
  }
});

$("logout").addEventListener("click", async () => {
  try {
    await api("/api/auth/logout", { method: "POST" });
  } catch (e) {
    /* même en cas d'erreur, on revient au formulaire */
  }
  showLogin();
});

$("theme-toggle").addEventListener("click", () => {
  const root = document.documentElement;
  const dark = root.dataset.theme ? root.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
  root.dataset.theme = dark ? "light" : "dark";
  try {
    localStorage.setItem("greengrow-theme", root.dataset.theme);
  } catch (e) {
    /* pas grave : le choix vaut pour cette visite */
  }
});

// ---------- Rafraîchissement ----------
// Toutes les 5 secondes, la page redemande l'état à l'API ("polling").
// C'est la façon la plus simple d'avoir un affichage à jour ; on s'arrête
// quand l'onglet est caché pour ne pas solliciter le serveur pour rien.

function startRefresh() {
  stopRefresh();
  state.timer = setInterval(() => {
    if (!document.hidden) refresh();
  }, REFRESH_MS);
}

function stopRefresh() {
  if (state.timer) clearInterval(state.timer);
  state.timer = null;
}

document.addEventListener("visibilitychange", () => {
  if (!document.hidden && state.user) refresh();
});

async function refresh() {
  try {
    state.bacs = await api("/api/bacs");
    if (!state.bacs.some((b) => b.bac_id === state.selected)) {
      state.selected = state.bacs.length ? state.bacs[0].bac_id : null;
    }
    renderBacList();
    $("bac-empty").hidden = state.bacs.length > 0;
    $("bac-detail").hidden = !state.selected;
    if (state.selected) await refreshBac(state.bacs.find((b) => b.bac_id === state.selected));
    $("refresh-dot").className = "live-dot";
    $("refresh-note").textContent = "À jour à " + clock(Date.now(), true) + " · actualisation automatique toutes les 5 secondes";
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) {
      showLogin("Ta session a expiré, reconnecte-toi.");
    } else {
      $("refresh-dot").className = "live-dot stale";
      $("refresh-note").textContent = "Serveur injoignable, nouvel essai dans 5 secondes";
    }
  }
}

function renderBacList() {
  const list = $("bac-list");
  clear(list);
  for (const bac of state.bacs) {
    const tab = el("button", null, "bac-tab");
    tab.type = "button";
    tab.appendChild(el("span", null, "dot" + (bac.online ? " on" : "")));
    tab.appendChild(el("span", bac.nom));
    tab.setAttribute("aria-current", bac.bac_id === state.selected ? "true" : "false");
    tab.addEventListener("click", () => {
      state.selected = bac.bac_id;
      state.watching = null;
      setFeedback("");
      refresh();
    });
    list.appendChild(tab);
  }
}

async function refreshBac(bac) {
  const id = encodeURIComponent(bac.bac_id);
  const [readings, alerts, commands, events] = await Promise.all([
    api("/api/readings/" + id + "?limit=120"),
    api("/api/alerts/" + id + "?active=true"),
    api("/api/bacs/" + id + "/commands?limit=10"),
    api("/api/events/" + id + "?limit=15"),
  ]);
  if (bac.bac_id !== state.selected) return; // l'utilisateur a changé de bac entre-temps

  const latest = readings[0] || null;
  renderHeader(bac);
  renderBanner(bac, latest, alerts);
  renderMoisture(bac, latest);
  renderTiles(bac, latest, readings, events);
  renderCharts(bac, readings);
  renderTable(readings);
  renderAlerts(alerts);
  renderActivity(commands, events);
  renderControls(bac, commands);
}

function renderHeader(bac) {
  $("bac-name").textContent = bac.nom;
  const culture = bac.culture.charAt(0).toUpperCase() + bac.culture.slice(1);
  $("bac-meta").textContent = culture + " · " + (bac.last_seen_at ? "dernier signe de vie " + ago(bac.last_seen_at) : "jamais connecté");
  $("bac-status").textContent = bac.online ? "En ligne" : "Hors ligne";
  $("bac-status").className = "pill" + (bac.online ? " on" : "");
}

// La phrase du haut : l'information la plus importante d'abord.
function renderBanner(bac, latest, alerts) {
  let kind = "", name = "check", title = "Tout va bien", text = "Le sol est dans la zone idéale.";
  if (!bac.online) {
    kind = "off"; name = "offline"; title = "Bac hors ligne";
    text = bac.last_seen_at ? "Aucune nouvelle depuis " + ago(bac.last_seen_at).replace("il y a ", "") + ". Les valeurs affichées sont les dernières reçues." : "Ce bac ne s'est encore jamais connecté.";
  } else if (alerts.length) {
    kind = "bad"; name = "alert"; title = alerts[0].message;
    text = alerts.length > 1 ? "Et " + (alerts.length - 1) + " autre(s) alerte(s) en cours." : "Alerte ouverte " + ago(alerts[0].opened_at) + ".";
  } else if (latest && latest.pump_active) {
    kind = "info"; name = "drop"; title = "Arrosage en cours"; text = "La pompe tourne en ce moment.";
  } else if (!latest) {
    kind = "off"; name = "leaf"; title = "En attente des premières mesures"; text = "Le bac est connecté, ses mesures arrivent.";
  } else if (latest.moisture_percent > bac.moisture_high) {
    kind = "warn"; name = "drop"; title = "Sol très humide"; text = "L'humidité dépasse la zone idéale, aucun arrosage nécessaire.";
  }
  $("banner").className = "banner " + kind;
  $("banner-use").setAttribute("href", "#i-" + name);
  $("banner-title").textContent = title;
  $("banner-text").textContent = text;
}

function renderMoisture(bac, latest) {
  $("v-moisture").textContent = latest ? num(latest.moisture_percent, 0) : "–";
  $("moisture-updated").textContent = latest ? "Mesuré " + ago(latest.measured_at) : "";
  $("meter-zone").style.left = bac.moisture_low + "%";
  $("meter-zone").style.width = bac.moisture_high - bac.moisture_low + "%";
  const marker = $("meter-marker");
  marker.hidden = !latest;
  if (latest) {
    marker.style.left = Math.min(100, Math.max(0, latest.moisture_percent)) + "%";
    const out = latest.moisture_percent < bac.moisture_low || latest.moisture_percent > bac.moisture_high;
    marker.className = "meter-marker" + (out ? " out" : "");
  }
  const scale = $("meter-scale");
  clear(scale);
  for (const value of [0, bac.moisture_low, bac.moisture_high, 100]) {
    const mark = el("span", num(value, 0));
    mark.style.left = value + "%";
    scale.appendChild(mark);
  }
  let caption = "Zone idéale : de " + num(bac.moisture_low, 0) + " à " + num(bac.moisture_high, 0) + " %.";
  if (latest && latest.moisture_percent < bac.moisture_low) caption += " Le sol est trop sec.";
  else if (latest && latest.moisture_percent > bac.moisture_high) caption += " Le sol est très humide.";
  $("meter-caption").textContent = caption;
  $("meter").setAttribute("aria-label", latest ? "Humidité du sol " + num(latest.moisture_percent, 0) + " %. " + caption : caption);
}

function renderTiles(bac, latest, readings, events) {
  $("v-temp").textContent = latest ? num(latest.temperature_celsius, 1) : "–";
  $("temp-note").textContent = !latest ? "" :
    latest.temperature_celsius > bac.temp_max ? "Au-dessus du maximum (" + num(bac.temp_max, 0) + " °C)" : "Maximum conseillé : " + num(bac.temp_max, 0) + " °C";
  $("v-air").textContent = latest ? num(latest.humidity_air_percent, 0) : "–";
  drawSpark("spark-air", readings.slice(0, 40).reverse().map((r) => r.humidity_air_percent));
  $("v-pump").textContent = !latest ? "–" : latest.pump_active ? "En marche" : "À l'arrêt";
  const lastWatering = events.find((e) => e.type === "watering_started");
  $("pump-note").textContent = lastWatering ? "Dernier arrosage " + ago(lastWatering.occurred_at) : "Aucun arrosage enregistré";
}

function renderCharts(bac, readings) {
  // L'API renvoie les mesures de la plus récente à la plus ancienne.
  const ordered = readings.slice().reverse();
  $("chart-temp").classList.add("heat");
  drawChart("chart-moisture", ordered.map((r) => ({ t: Date.parse(r.measured_at), v: r.moisture_percent, pump: r.pump_active })), {
    zone: { low: bac.moisture_low, high: bac.moisture_high }, unit: " %", digits: 0, floor: 0, ceil: 100,
  });
  drawChart("chart-temp", ordered.map((r) => ({ t: Date.parse(r.measured_at), v: r.temperature_celsius, pump: false })), {
    limit: bac.temp_max, limitLabel: "Maximum conseillé " + num(bac.temp_max, 0) + " °C", unit: " °C", digits: 1,
  });
}

function renderTable(readings) {
  const rows = $("readings-table");
  clear(rows);
  for (const r of readings.slice(0, 12)) {
    const row = el("tr");
    row.appendChild(el("td", clock(r.measured_at, true)));
    row.appendChild(el("td", num(r.moisture_percent, 0) + " %", "num"));
    row.appendChild(el("td", num(r.temperature_celsius, 1) + " °C", "num"));
    row.appendChild(el("td", num(r.humidity_air_percent, 0) + " %", "num"));
    row.appendChild(el("td", r.pump_active ? "En marche" : "À l'arrêt"));
    rows.appendChild(row);
  }
}

function renderAlerts(alerts) {
  const list = $("alerts");
  clear(list);
  $("alert-count").textContent = alerts.length;
  $("alert-count").className = "count" + (alerts.length ? " has" : "");
  if (!alerts.length) {
    const none = el("li", null, "none");
    none.appendChild(icon("check"));
    none.appendChild(el("span", "Aucune alerte en cours"));
    list.appendChild(none);
    return;
  }
  for (const alert of alerts) {
    const item = el("li");
    item.appendChild(icon("alert"));
    const body = el("div", alert.message);
    body.appendChild(el("small", "Depuis " + clock(alert.opened_at) + " (" + ago(alert.opened_at) + ")"));
    item.appendChild(body);
    list.appendChild(item);
  }
}

function commandLabel(command) {
  const label = COMMANDS[command.type] || command.type;
  return command.type === "pump_on" ? label + " de " + command.params.duration_s + " s" : label;
}

function commandStatus(command) {
  const text = (STATUS[command.status] || [command.status])[0];
  return command.reason ? text + " : " + (REASONS[command.reason] || command.reason) : text;
}

// Commandes et événements du bac, mélangés dans l'ordre du temps.
function renderActivity(commands, events) {
  const items = [];
  for (const c of commands) {
    items.push({ at: c.created_at, text: "Commande : " + commandLabel(c), detail: commandStatus(c), kind: (STATUS[c.status] || ["", ""])[1] });
  }
  for (const e of events) {
    if (e.type === "cmd_ack") continue; // déjà visible sur la ligne de la commande
    const known = EVENTS[e.type] || [e.type, ""];
    items.push({ at: e.occurred_at, text: known[0], detail: "", kind: known[1] });
  }
  items.sort((a, b) => Date.parse(b.at) - Date.parse(a.at));

  const list = $("activity");
  clear(list);
  if (!items.length) {
    list.appendChild(el("li", "Rien à signaler pour l'instant.", "none"));
    return;
  }
  for (const item of items.slice(0, 10)) {
    const row = el("li", null, item.kind);
    row.appendChild(el("span", item.text));
    const when = el("time", clock(item.at));
    when.title = new Date(item.at).toLocaleString("fr-FR");
    row.appendChild(when);
    if (item.detail) row.appendChild(el("small", item.detail.charAt(0).toUpperCase() + item.detail.slice(1)));
    list.appendChild(row);
  }
}

// ---------- Arrosage manuel ----------

function setFeedback(text, kind) {
  const box = $("command-feedback");
  clear(box);
  box.className = "feedback" + (kind && kind !== "wait" ? " " + kind : "");
  if (!text) return;
  if (kind === "wait") box.appendChild(el("span", null, "spinner"));
  else if (kind === "ok") box.appendChild(icon("check"));
  else if (kind === "ko") box.appendChild(icon("alert"));
  box.appendChild(el("span", text));
}

function renderControls(bac, commands) {
  if (state.watching) {
    const watched = commands.find((c) => c.id === state.watching);
    if (watched) {
      const said = { sent: "en attente du bac…", executed: "commande exécutée", rejected: "commande refusée par le bac", expired: "pas de réponse du bac" };
      let text = commandLabel(watched) + " : " + (said[watched.status] || watched.status);
      if (watched.reason) text += " (" + (REASONS[watched.reason] || watched.reason) + ")";
      setFeedback(text, (STATUS[watched.status] || ["", ""])[1]);
      if (watched.status !== "sent") state.watching = null;
    }
  } else if (!bac.online) {
    setFeedback("Bac hors ligne : les commandes sont désactivées.");
  } else if ($("command-feedback").textContent.indexOf("hors ligne") !== -1) {
    setFeedback("");
  }
  for (const button of document.querySelectorAll("[data-command]")) button.disabled = !bac.online || !!state.watching;
}

function selectDuration(seconds) {
  state.duration = seconds;
  for (const chip of document.querySelectorAll("[data-duration]")) {
    chip.setAttribute("aria-checked", Number(chip.dataset.duration) === seconds ? "true" : "false");
  }
}
for (const chip of document.querySelectorAll("[data-duration]")) {
  chip.addEventListener("click", () => selectDuration(Number(chip.dataset.duration)));
}
selectDuration(state.duration);

for (const button of document.querySelectorAll("[data-command]")) {
  button.addEventListener("click", async () => {
    const type = button.dataset.command;
    const body = { type: type };
    if (type === "pump_on") body.duration_s = state.duration;
    for (const other of document.querySelectorAll("[data-command]")) other.disabled = true;
    setFeedback("Envoi de la commande…", "wait");
    try {
      const command = await api("/api/bacs/" + encodeURIComponent(state.selected) + "/commands", { method: "POST", body: body });
      state.watching = command.id;
      setFeedback(commandLabel(command) + " : en attente du bac…", "wait");
      // On n'attend pas les 5 secondes : on redemande vite la réponse du bac.
      setTimeout(refresh, 700);
      setTimeout(refresh, 2500);
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) return showLogin("Ta session a expiré, reconnecte-toi.");
      setFeedback(error instanceof ApiError ? error.message : "Serveur injoignable", "ko");
      for (const other of document.querySelectorAll("[data-command]")) other.disabled = false;
    }
  });
}

// ---------- Démarrage ----------

(async function start() {
  try {
    await showApp(await api("/api/auth/me"));
  } catch (error) {
    showLogin();
  }
})();
