/*
 * HomeHoard Card — a self-contained Lovelace card for the HomeHoard integration.
 *
 * Shipped and auto-registered by the integration (no manual resource needed).
 * Usage:
 *   type: custom:homehoard-card
 *   # optional:
 *   title: HomeHoard
 *   app_path: /hassio/ingress/b3264f33_homehoard   # for Open / Scan buttons
 *   prefix: sensor.homehoard_                       # entity id prefix
 *
 * Quick actions call the homehoard.* services with return_response, so no
 * input_text / script helpers are required.
 */
const VERSION = "1.0.0";

class HomeHoardCard extends HTMLElement {
  setConfig(config) {
    this._config = config || {};
    this._prefix = this._config.prefix || "sensor.homehoard_";
    this._appPath = this._config.app_path || "/hassio/ingress/b3264f33_homehoard";
    this._built = false;
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._built) this._build();
    this._update();
  }

  getCardSize() { return 12; }

  // ---- helpers -------------------------------------------------------------
  _s(key) { return this._hass?.states?.[this._prefix + key]; }
  _num(key, fallback = "—") {
    const e = this._s(key);
    return e && e.state !== "unknown" && e.state !== "unavailable" ? e.state : fallback;
  }
  _attr(key, attr) { return this._s(key)?.attributes?.[attr] || []; }

  async _callResponse(service, data) {
    try {
      const res = await this._hass.connection.sendMessagePromise({
        type: "call_service", domain: "homehoard", service,
        service_data: data, return_response: true,
      });
      return res?.response?.speech || "Done.";
    } catch (err) {
      return "Error: " + (err?.message || err?.error || "service call failed");
    }
  }

  _nav(path) {
    history.pushState(null, "", path);
    window.dispatchEvent(new CustomEvent("location-changed"));
  }

  // ---- build (once) --------------------------------------------------------
  _build() {
    this._built = true;
    const root = this.attachShadow({ mode: "open" });
    root.innerHTML = `
      <style>
        ha-card { padding: 16px; }
        .head { display:flex; align-items:center; gap:8px; margin-bottom:12px; }
        .head h2 { margin:0; font-size:1.3rem; flex:1; }
        .dot { width:10px; height:10px; border-radius:50%; background:var(--error-color); }
        .dot.on { background:var(--success-color, #4caf50); }
        .tiles { display:grid; grid-template-columns:repeat(auto-fit,minmax(90px,1fr)); gap:8px; margin-bottom:16px; }
        .tile { background:var(--secondary-background-color); border-radius:12px; padding:10px; text-align:center; }
        .tile .v { font-size:1.35rem; font-weight:600; color:var(--primary-text-color); }
        .tile .l { font-size:0.72rem; color:var(--secondary-text-color); text-transform:uppercase; letter-spacing:.03em; }
        .section { margin-top:14px; }
        .section h3 { margin:0 0 8px; font-size:0.95rem; color:var(--primary-text-color); }
        .row { display:flex; gap:8px; flex-wrap:wrap; align-items:center; }
        input { flex:1; min-width:120px; padding:8px 10px; border-radius:8px; border:1px solid var(--divider-color);
                background:var(--card-background-color); color:var(--primary-text-color); font-size:0.95rem; }
        button { padding:8px 12px; border-radius:8px; border:none; cursor:pointer; font-size:0.9rem;
                 background:var(--primary-color); color:var(--text-primary-color, #fff); }
        button.sec { background:var(--secondary-background-color); color:var(--primary-text-color); }
        .answer { margin-top:8px; font-size:0.9rem; color:var(--primary-text-color); min-height:1.2em;
                  padding:8px 10px; background:var(--secondary-background-color); border-radius:8px; display:none; }
        .answer.show { display:block; }
        ul { margin:0; padding:0; list-style:none; }
        li { padding:6px 0; border-bottom:1px solid var(--divider-color); font-size:0.92rem; color:var(--primary-text-color);
             display:flex; gap:6px; align-items:center; }
        li:last-child { border-bottom:none; }
        .muted { color:var(--secondary-text-color); }
        .badge { font-size:0.72rem; padding:1px 6px; border-radius:10px; background:var(--secondary-background-color); }
        .badge.warn { background:var(--error-color); color:#fff; }
        .grow { flex:1; }
        a.link { color:var(--primary-color); text-decoration:none; font-size:0.88rem; }
      </style>
      <ha-card>
        <div class="head">
          <span class="dot" id="dot"></span>
          <h2 id="title">HomeHoard</h2>
          <a class="link" id="open" href="#">Open app →</a>
        </div>

        <div class="tiles" id="tiles"></div>

        <div class="section">
          <h3>Find something</h3>
          <div class="row">
            <input id="q" placeholder="Item, bin, or location…" />
            <button id="locate">Where is it?</button>
            <button class="sec" id="contents">What's inside?</button>
          </div>
          <div class="answer" id="ans_find"></div>
        </div>

        <div class="section">
          <h3>Lend &amp; return</h3>
          <div class="row">
            <input id="item" placeholder="Item name…" />
            <button id="out">Check out</button>
            <button class="sec" id="in">Check in</button>
          </div>
          <div class="answer" id="ans_lend"></div>
        </div>

        <div class="section">
          <div class="row">
            <button class="sec" id="scanout">📷 Scan to check out</button>
            <button class="sec" id="scanin">📷 Scan to check in</button>
          </div>
        </div>

        <div class="section">
          <h3>Checked out <span class="badge" id="out_count">0</span></h3>
          <ul id="checked"></ul>
        </div>

        <div class="section">
          <h3>Recently added</h3>
          <ul id="recent"></ul>
        </div>

        <div class="section">
          <h3>Locations</h3>
          <ul id="locations"></ul>
        </div>
      </ha-card>
    `;

    const $ = (id) => root.getElementById(id);
    $("title").textContent = this._config.title || "HomeHoard";
    $("open").addEventListener("click", (e) => { e.preventDefault(); this._nav(this._appPath); });
    $("scanout").addEventListener("click", () => this._nav(this._appPath + "/#/scan?action=checkout"));
    $("scanin").addEventListener("click", () => this._nav(this._appPath + "/#/scan?action=checkin"));

    const answer = (node, text) => { node.textContent = text; node.classList.add("show"); };
    $("locate").addEventListener("click", async () =>
      answer($("ans_find"), await this._callResponse("locate", { query: $("q").value })));
    $("contents").addEventListener("click", async () =>
      answer($("ans_find"), await this._callResponse("contents", { query: $("q").value })));
    $("out").addEventListener("click", async () =>
      answer($("ans_lend"), await this._callResponse("check_out", { name: $("item").value })));
    $("in").addEventListener("click", async () =>
      answer($("ans_lend"), await this._callResponse("check_in", { name: $("item").value })));

    this._$ = $;
  }

  // ---- update (each hass change) ------------------------------------------
  _update() {
    if (!this._$) return;
    const $ = this._$;

    const online = this._s("online") || this._hass.states["binary_sensor.homehoard_online"];
    $("dot").className = "dot" + (online && online.state === "on" ? " on" : "");

    const tiles = [
      ["Items", this._num("total_items")],
      ["Value", this._fmtValue(this._num("total_value", null))],
      ["Checked out", this._num("checked_out")],
      ["Warranties 30d", this._num("warranties_expiring_30d")],
      ["Maint. overdue", this._num("maintenance_overdue")],
    ];
    $("tiles").innerHTML = tiles
      .map(([l, v]) => `<div class="tile"><div class="v">${v}</div><div class="l">${l}</div></div>`)
      .join("");

    const checked = this._attr("checked_out", "items");
    $("out_count").textContent = checked.length;
    $("checked").innerHTML = checked.length
      ? checked.map((i) =>
          `<li><span>${this._esc(i.name)}</span>${i.to ? `<span class="muted">→ ${this._esc(i.to)}</span>` : ""}` +
          `${i.overdue ? `<span class="badge warn">overdue</span>` : ""}</li>`).join("")
      : `<li class="muted">Nothing is checked out.</li>`;

    const recent = this._attr("total_items", "recent");
    $("recent").innerHTML = recent.length
      ? recent.map((i) =>
          `<li><span>${this._esc(i.name)}</span><span class="grow"></span>` +
          `<span class="muted">${this._esc(i.where || "")}</span>` +
          `${i.checkedOut ? `<span class="badge">out</span>` : ""}</li>`).join("")
      : `<li class="muted">No items yet.</li>`;

    const locs = this._attr("locations", "locations");
    $("locations").innerHTML = locs.length
      ? locs.map((l) =>
          `<li>📍 <span>${this._esc(l.name)}</span><span class="grow"></span>` +
          `<span class="muted">${l.itemCount} items · ${l.binCount} bins</span></li>`).join("")
      : `<li class="muted">No locations yet.</li>`;
  }

  _fmtValue(v) {
    if (v === null || v === undefined) return "—";
    const n = Number(v);
    return isNaN(n) ? v : n.toLocaleString(undefined, { maximumFractionDigits: 0 });
  }
  _esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"]/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  }
}

customElements.define("homehoard-card", HomeHoardCard);

window.customCards = window.customCards || [];
window.customCards.push({
  type: "homehoard-card",
  name: "HomeHoard Card",
  description: "Inventory overview, quick actions, checkouts, recent items & locations.",
  preview: true,
  documentationURL: "https://github.com/Amantux/homehoard",
});

console.info(`%c HOMEHOARD-CARD %c v${VERSION} `,
  "color:#fff;background:#4f46e5;border-radius:4px 0 0 4px;padding:2px 6px",
  "color:#4f46e5;background:#eceafe;border-radius:0 4px 4px 0;padding:2px 6px");
