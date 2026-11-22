"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");

class Element {
  constructor(tag = "div") {
    this.tagName = tag;
    this.children = [];
    this.dataset = {};
    this.className = "";
    this.textContent = "";
    this.classList = { toggle: () => {} };
  }
  appendChild(child) { child.parent = this; this.children.push(child); return child; }
  replaceChildren(...children) { this.children = []; children.forEach(child => this.appendChild(child)); }
  get firstElementChild() { return this.children[0]; }
  remove() { if (this.parent) this.parent.children = this.parent.children.filter(item => item !== this); }
  setAttribute() {}
  addEventListener() {}
  get firstChild() { return this.children[0]; }
  showModal() {}
  close() {}
}
const elements = new Map();
const document = {
  getElementById(id) { if (!elements.has(id)) elements.set(id, new Element()); return elements.get(id); },
  createElement(tag) { return new Element(tag); },
  createElementNS(_namespace, tag) { return new Element(tag); }
};
const pending = [];
const fetch = url => new Promise(resolve => pending.push({ url, resolve }));
const source = fs.readFileSync(path.join(__dirname, "..", "web", "preview", "preview.js"), "utf8");
const context = vm.createContext({ document, fetch, Date, console });
vm.runInContext(source, context);
function complete(url, data) {
  const index = pending.findIndex(item => item.url === url);
  assert.notEqual(index, -1, `Requête absente : ${url}`);
  pending.splice(index, 1)[0].resolve({ ok: true, json: async () => data });
}
const tick = () => new Promise(resolve => setImmediate(resolve));
function text(element) { return element.textContent + element.children.map(text).join(" "); }
async function run() {
  // The initial render of the home page first asks for the shared labels, then the dashboard data.
  await tick();
  complete("/labels.json", { actions: { WAIT: "ATTENTE (aucune entrée)" }, roles: { quant: "Analyste quantitatif" } });
  await tick();
  complete("/dashboard", { events: [], latest_votes: {}, costs: {} });
  complete("/market/overview", { instruments: [] });
  complete("/market/candles", { candles: [], symbols: [] });
  complete("/autopilot", { mode: "off", alive: false, last_cycle: {}, cycles: 0, decisions_today: 0, shadow_outcomes: 0, errors: 0, costs: { total_usd: 0 } });
  complete("/autopilot/positions", { positions: [] });
  await tick();
  const agents = vm.runInContext('render("AI Agents")', context);
  const skills = vm.runInContext('render("Skills Library")', context);
  await tick();
  complete("/skills", [{ name: "Compétence visible", owner: "quant", state: "specification" }]);
  await skills;
  await tick();
  const content = document.getElementById("content");
  assert.match(text(content), /Compétence visible/);
  assert.match(text(content), /Analyste quantitatif/); // shared French label applied
  assert.doesNotMatch(text(content), /Chargement des données/);
  complete("/autopilot/analyses", [{ arm: "skills:graph", symbol: "ANCIENNE RÉPONSE", action: "WAIT", at: "2026-11-18T10:00:00+00:00", rationale: "" }]);
  await agents;
  await tick();
  assert.match(text(content), /Compétence visible/);
  assert.doesNotMatch(text(content), /ANCIENNE RÉPONSE/);
  const home = vm.runInContext('render("Command Center")', context);
  await tick();
  complete("/dashboard", { events: [], latest_votes: {}, costs: {} });
  complete("/market/overview", { instruments: [] });
  complete("/market/candles", { candles: [], symbols: [] });
  complete("/autopilot", { mode: "off", alive: false, last_cycle: {}, cycles: 0, decisions_today: 0, shadow_outcomes: 0, errors: 0, costs: { total_usd: 0 } });
  complete("/autopilot/positions", { positions: [] });
  await home;
  assert.doesNotMatch(text(content), /ANCIENNE RÉPONSE/);
  assert.match(text(content), /AUCUN CYCLE/);
  const message = vm.runInContext('friendly(new Error("Operator authentication required"))', context);
  assert.match(message, /Clé opérateur manquante ou incorrecte/);
  assert.match(vm.runInContext('friendly(new Error("autre chose"))', context), /autre chose/);
  assert.match(vm.runInContext('friendly(new Error("basket.positions must be between 2 and 50"))', context), /Réglage du panier refusé/);
  console.log("Navigation locale : réponses obsolètes ignorées.");
}
run().catch(error => { console.error(error); process.exitCode = 1; });
