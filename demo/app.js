// Alias demo page: loads the tokenizer and the ONNX model from Hugging Face once (the browser
// caches them), then masks the pasted text locally with alias.js. The text is never sent: the
// only requests are for the model files and the ONNX runtime, and the page's CSP allows no other
// host. Text is only ever inserted with textContent, never as HTML.
import {
  AutoModelForTokenClassification,
  AutoTokenizer,
  Tensor,
  env,
} from "https://cdn.jsdelivr.net/npm/@huggingface/transformers@4.3.1/dist/transformers.min.js";
import { TAGS, detect, mask, restore } from "./alias.js";

const MODEL = "Gabrielkph/alias-mmbert-small";
// The model version the demo was tested with: a tag on the model repository, so a later upload
// of new weights cannot change the demo without a new release of it.
const MODEL_REVISION = "v1.0";
const VERSION = "0.2.0"; // x-release-please-version
// What the first visit downloads: the ONNX model (563 MB) and the tokenizer (34 MB).
const EXPECTED_BYTES = 597e6;

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

// What an LLM could answer to "Summarise this document" about the masked example: written with
// the aliases the example gets, so the restore step can be tried without an LLM.
const EXAMPLE_ANSWER = `Résumé : [PERSON_1], né le [BIRTH_DATE_1] et domicilié [ADDRESS_1], demande le remboursement de ses frais pour le dossier n° [IDENTIFIER_1].

- Versement demandé sur le compte [IBAN_1].
- Numéro de sécurité sociale indiqué : [NATIONAL_ID_1].
- Contact : [PHONE_1] ou [EMAIL_1].`;

const $ = (id) => document.getElementById(id);
let detector = null; // { tokenize, predict, bos, eos } once the model is loaded
let last = null;

function show(element, visible) {
  element.hidden = !visible;
}

function setError(message) {
  $("error").textContent = message || "";
  show($("error"), Boolean(message));
}

function setStatus(message) {
  $("status").textContent = message;
}

async function load() {
  env.allowLocalModels = false;
  const files = new Map(); // file -> [loaded, total]
  let started = null;
  const progress = (info) => {
    if (info.status !== "progress" || !info.total) return;
    files.set(info.file, [info.loaded, info.total]);
    const [loaded, known] = [...files.values()].reduce((a, b) => [a[0] + b[0], a[1] + b[1]]);
    // The tokenizer comes first: until the model file starts, its size is not known yet.
    const total = Math.max(known, EXPECTED_BYTES);
    started ??= performance.now();
    const seconds = (performance.now() - started) / 1000;
    const bar = $("progress");
    show(bar, true);
    bar.value = loaded / total;
    let left = "";
    if (seconds > 3 && loaded > 0) {
      const minutes = Math.ceil(((total - loaded) / (loaded / seconds)) / 60);
      left = minutes <= 1 ? ", about a minute left" : `, about ${minutes} minutes left`;
    }
    setStatus(
      `Downloading the model, first visit only: ${Math.round(loaded / 1e6)} / ` +
        `${Math.round(total / 1e6)} MB${left}. The browser keeps it: next visits start at once.`,
    );
  };
  setStatus("Loading the model…");
  const tokenizer = await AutoTokenizer.from_pretrained(MODEL, {
    revision: MODEL_REVISION,
    progress_callback: progress,
  });
  const model = await AutoModelForTokenClassification.from_pretrained(MODEL, {
    revision: MODEL_REVISION,
    dtype: "fp32", // int8 destroys this model's precision (docs/TRAINING.md)
    device: "wasm",
    progress_callback: progress,
  });
  const labels = model.config.id2label;
  if (TAGS.some((tag, i) => labels[i] !== tag)) throw new Error("unexpected model labels");

  const encode = (text) => {
    if (tokenizer._tokenizer?.encode) {
      const { ids, tokens } = tokenizer._tokenizer.encode(text, { add_special_tokens: false });
      return { ids, tokens };
    }
    const tokens = tokenizer.tokenize(text);
    return { ids: tokenizer.convert_tokens_to_ids(tokens), tokens };
  };
  const predict = async (ids) => {
    const shape = [1, ids.length];
    const inputIds = new Tensor("int64", BigInt64Array.from(ids, BigInt), shape);
    const mask = new Tensor("int64", new BigInt64Array(ids.length).fill(1n), shape);
    const { logits } = await model({ input_ids: inputIds, attention_mask: mask });
    const [, length, classes] = logits.dims;
    const data = logits.data;
    const tags = [];
    for (let t = 0; t < length; t++) {
      let best = 0;
      for (let c = 1; c < classes; c++) {
        if (data[t * classes + c] > data[t * classes + best]) best = c;
      }
      tags.push(best);
    }
    return tags;
  };
  detector = {
    tokenize: encode,
    predict,
    bos: tokenizer.convert_tokens_to_ids("<bos>"),
    eos: tokenizer.convert_tokens_to_ids("<eos>"),
  };
  show($("progress"), false);
  setStatus("Ready. Detector: rules + mmBERT-small, running in this browser.");
  $("mask").disabled = false;
}

function highlight(text, entities) {
  const box = $("highlighted");
  box.replaceChildren();
  let cursor = 0;
  for (const entity of entities) {
    box.append(document.createTextNode(text.slice(cursor, entity.start)));
    const mark = document.createElement("mark");
    mark.className = `t-${entity.type}`;
    mark.title = `${LABELS[entity.type] || entity.type} → ${entity.alias}`;
    mark.append(document.createTextNode(text.slice(entity.start, entity.end)));
    const tag = document.createElement("span");
    tag.className = "tag";
    tag.textContent = entity.alias;
    mark.append(tag);
    box.append(mark);
    cursor = entity.end;
  }
  box.append(document.createTextNode(text.slice(cursor)));
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
  if (!detector) return;
  if (!text.trim()) {
    setError("Paste a text first.");
    return;
  }
  const button = $("mask");
  button.disabled = true;
  button.textContent = "Masking…";
  await new Promise((resolve) => setTimeout(resolve, 20)); // let the button repaint
  try {
    const started = performance.now();
    const result = mask(text, await detect(text, detector));
    last = result;
    highlight(text, result.entities);
    legend(result.report);
    $("masked").value = result.masked;
    table(result.report);
    $("copied").textContent = "";
    show($("results"), true);
    // A new masked text: the previous answer and its restored version no longer apply.
    $("answer").value = "";
    $("restored").value = "";
    $("restore-report").textContent = "";
    show($("restored"), false);
    show($("copy-restored"), false);
    show($("back"), true);
    // The example answer only fits the example, and only if every alias it uses was given.
    const fits = [...EXAMPLE_ANSWER.matchAll(/\[[A-Z_]+_\d+\]/g)].every((m) =>
      result.aliases.includes(m[0]),
    );
    show($("example-answer"), text === EXAMPLE && fits);
    setStatus(`Masked in ${((performance.now() - started) / 1000).toFixed(1)} s, in this browser.`);
  } catch (error) {
    console.error(error);
    setError("The detector failed on this text.");
  } finally {
    button.disabled = false;
    button.textContent = "Mask";
  }
}

function restoreAnswer() {
  if (!last) return;
  const answer = $("answer").value;
  const report = $("restore-report");
  if (!answer.trim()) {
    report.textContent = "Paste the LLM's answer first.";
    return;
  }
  const back = restore(answer, last);
  $("restored").value = back.text;
  show($("restored"), true);
  show($("copy-restored"), true);
  $("copied-restored").textContent = "";
  const parts = [`${back.restored.length} alias(es) replaced by their value.`];
  if (back.missing.length) parts.push(`Not in the answer: ${back.missing.join(", ")}.`);
  if (back.unknown.length) {
    parts.push(`Left as they are (not from this text): ${back.unknown.join(", ")}.`);
  }
  report.textContent = parts.join(" ");
}

async function copyRestored() {
  let copied = true;
  try {
    await navigator.clipboard.writeText($("restored").value);
  } catch {
    $("restored").select();
    copied = document.execCommand("copy");
  }
  $("copied-restored").textContent = copied ? "Copied." : "Not copied: select the text and copy it.";
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
  // Types, positions (UTF-16 units), aliases and counts: never the values.
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

$("version").textContent = `Alias v${VERSION}, model ${MODEL_REVISION}.`;
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
$("restore").addEventListener("click", restoreAnswer);
$("example-answer").addEventListener("click", () => {
  $("answer").value = EXAMPLE_ANSWER;
});
$("copy-restored").addEventListener("click", copyRestored);
load().catch((error) => {
  console.error(error);
  show($("progress"), false);
  setStatus("The model could not be loaded in this browser. Try a recent Chrome, Edge or Firefox.");
  $("status").classList.add("warn");
});
