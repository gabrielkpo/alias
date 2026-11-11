// Alias page: sends the pasted text to this server's /api/mask and shows the result.
// Text from the user and from the server is only ever inserted with textContent, never as HTML.
"use strict";

const LABELS = {
  PERSON: "Person",
  ADDRESS: "Address",
  EMAIL: "E-mail",
  PHONE: "Phone",
  IBAN: "IBAN",
  NATIONAL_ID: "National ID",
  BIRTH_DATE: "Birth date",
  IDENTIFIER: "Identifier",
};

// Fictitious values only (tests/README.md): reserved e-mail domain, phone range for fiction,
// specification IBAN, invented NIR.
const EXAMPLE = `Objet : remboursement du dossier n° 2024/00421

Madame, Monsieur,

Je soussigné Jean Dupont, né le 12/03/1985, domicilié 14 rue des Lilas, 69003 Lyon,
demande le remboursement de mes frais. Vous pouvez me joindre au 01 99 00 12 34 ou à
jean.dupont@example.com. Numéro de sécurité sociale : 1 85 05 78 006 084 91.
Merci de verser la somme sur le compte FR76 3000 6000 0112 3456 7890 189.

Jean Dupont`;

const $ = (id) => document.getElementById(id);
let last = null; // { masked, entities, report } of the latest answer

function show(element, visible) {
  element.hidden = !visible;
}

function setError(message) {
  $("error").textContent = message || "";
  show($("error"), Boolean(message));
}

async function checkHealth() {
  try {
    const response = await fetch("/health", { cache: "no-store" });
    const health = await response.json();
    const status = $("status");
    if (health.detector === "rules") {
      status.textContent =
        "Rules only: e-mails, phones, IBANs, IDs and announced birth dates. " +
        "Names and addresses need the model (start the server with --model).";
      status.classList.add("warn");
    } else {
      status.textContent = `Detector: ${health.detector} (version ${health.version}).`;
    }
    show($("demo"), Boolean(health.demo));
  } catch {
    $("status").textContent = "The server does not answer.";
  }
}

function highlight(text, entities) {
  const box = $("highlighted");
  box.replaceChildren();
  // The API counts positions in code points; JavaScript strings count UTF-16 units, which
  // differ after an emoji. Slice an array of code points instead.
  const chars = Array.from(text);
  const slice = (start, end) => chars.slice(start, end).join("");
  let cursor = 0;
  for (const entity of entities) {
    box.append(document.createTextNode(slice(cursor, entity.start)));
    const mark = document.createElement("mark");
    mark.className = `t-${entity.type}`;
    mark.title = `${LABELS[entity.type] || entity.type} → ${entity.alias}`;
    mark.append(document.createTextNode(slice(entity.start, entity.end)));
    const tag = document.createElement("span");
    tag.className = "tag";
    tag.textContent = entity.alias;
    mark.append(tag);
    box.append(mark);
    cursor = entity.end;
  }
  box.append(document.createTextNode(slice(cursor)));
}

function legend(report) {
  const box = $("legend");
  box.replaceChildren();
  for (const type of Object.keys(LABELS)) {
    if (!report[type]) continue;
    const chip = document.createElement("span");
    chip.className = `t-${type}`;
    chip.textContent = LABELS[type];
    box.append(chip);
  }
}

function table(report) {
  const body = $("report").querySelector("tbody");
  body.replaceChildren();
  const rows = Object.keys(LABELS).filter((type) => report[type]);
  rows.push("total");
  for (const type of rows) {
    const row = document.createElement("tr");
    const name = document.createElement("td");
    name.textContent = type === "total" ? "Total" : LABELS[type];
    const count = document.createElement("td");
    count.textContent = String(report[type] || 0);
    row.append(name, count);
    body.append(row);
  }
}

async function maskText() {
  const text = $("input").value;
  setError("");
  if (!text.trim()) {
    setError("Paste a text first.");
    return;
  }
  const button = $("mask");
  button.disabled = true;
  button.textContent = "Masking…";
  try {
    const response = await fetch("/api/mask", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ text }),
    });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) {
      setError(typeof body.detail === "string" ? body.detail : `Error ${response.status}.`);
      return;
    }
    last = body;
    highlight(text, body.entities);
    legend(body.report);
    $("masked").value = body.masked;
    table(body.report);
    $("copied").textContent = "";
    show($("results"), true);
  } catch {
    setError("The server does not answer.");
  } finally {
    button.disabled = false;
    button.textContent = "Mask";
  }
}

async function copyMasked() {
  let copied = true;
  try {
    await navigator.clipboard.writeText($("masked").value);
  } catch {
    $("masked").select();
    copied = document.execCommand("copy");
  }
  $("copied").textContent = copied ? "Copied." : "Not copied: select the text and copy it.";
}

function downloadReport() {
  if (!last) return;
  // Types, positions, aliases and counts: never the values.
  const report = {
    generated: new Date().toISOString(),
    counts: last.report,
    entities: last.entities,
  };
  const blob = new Blob([JSON.stringify(report, null, 2)], { type: "application/json" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = "alias-report.json";
  link.click();
  setTimeout(() => URL.revokeObjectURL(link.href), 1000);
}

function updateCount() {
  const n = $("input").value.length;
  $("count").textContent = n ? `${n.toLocaleString()} characters` : "";
}

document.addEventListener("DOMContentLoaded", () => {
  $("mask").addEventListener("click", maskText);
  $("example").addEventListener("click", () => {
    $("input").value = EXAMPLE;
    updateCount();
  });
  $("input").addEventListener("input", updateCount);
  $("input").addEventListener("keydown", (event) => {
    if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) maskText();
  });
  $("copy").addEventListener("click", copyMasked);
  $("download").addEventListener("click", downloadReport);
  checkHealth();
});
