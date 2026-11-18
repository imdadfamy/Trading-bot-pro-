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
function text(element) { return element.textContent + element.children.map(text).join(" "); }
async function run() {
  const agents = vm.runInContext('render("AI Agents")', context);
  const skills = vm.runInContext('render("Skills Library")', context);
  complete("/skills", [{ name: "Compétence visible", owner: "quant", state: "specification" }]);
  await skills;
  const content = document.getElementById("content");
  assert.match(text(content), /Compétence visible/);
  assert.doesNotMatch(text(content), /Chargement des données/);
  complete("/agents", [{ agent: "ANCIENNE RÉPONSE", action: "WAIT" }]);
  await agents;
  assert.match(text(content), /Compétence visible/);
  assert.doesNotMatch(text(content), /ANCIENNE RÉPONSE/);
  complete("/dashboard", {});
  complete("/market/candles", { candles: [] });
  await Promise.resolve();
  assert.doesNotMatch(text(content), /ANCIENNE RÉPONSE/);
  console.log("Navigation locale : réponses obsolètes ignorées.");
}
run().catch(error => { console.error(error); process.exitCode = 1; });
