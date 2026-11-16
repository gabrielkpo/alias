// The window of the Alias app. First launch: a loading screen while the detection model
// downloads, then three setup steps (how Alias works, the Mistral key, connecting tools); after
// that, the everyday screen. Every action goes through the app's Rust commands
// (window.__TAURI__.core.invoke); texts are set with textContent only.
const invoke = window.__TAURI__.core.invoke;
const $ = (id) => document.getElementById(id);

let screen = "loading";
let keyBack = "step1"; // where Back goes from the key step, and where a saved key leads after
let samples = []; // [seconds, bytes] of the download, for the time left

function show(id) {
  screen = id;
  for (const section of document.querySelectorAll(".screen")) section.hidden = section.id !== id;
  window.scrollTo(0, 0);
  if (id === "step3" || id === "home") loadToken();
  if (id === "step2") {
    $("key-result").textContent = "";
    $("key").focus();
  }
}

// A failure shows one short line; the full text stays one click away.
function brief(text) {
  const lines = String(text).split("\n").map((line) => line.trim()).filter(Boolean);
  const line = lines.at(-1) || "No details.";
  return line.length > 160 ? `${line.slice(0, 160)}…` : line;
}

function setError(id, text) {
  const box = $(id);
  box.hidden = text === null;
  if (text === null) return;
  box.querySelector(".error-text").textContent = brief(text);
  box.querySelector("pre").textContent = String(text);
}

let messageTimer;
function say(text) {
  $("message").textContent = text;
  clearTimeout(messageTimer);
  messageTimer = setTimeout(() => ($("message").textContent = ""), 4000);
}

const megabytes = (bytes) => Math.round(bytes / 1e6);

function timeLeft(done, total) {
  const now = Date.now() / 1000;
  samples.push([now, done]);
  samples = samples.filter(([time]) => now - time <= 30);
  const [firstTime, firstDone] = samples[0];
  if (now - firstTime < 5 || done <= firstDone) return "";
  const seconds = (total - done) / ((done - firstDone) / (now - firstTime));
  if (seconds < 60) return " · less than a minute left";
  return ` · about ${Math.round(seconds / 60)} min left`;
}

// The progress bar is a row of squares that light up from light to deep blue.
const PIXELS = 32;
const COLORS = ["#A9BDEB", "#8AA4E3", "#6A8AD6", "#4C6EC0", "#3557A6"]; // Alias blues, all visible on dark
for (let i = 0; i < PIXELS; i += 1) {
  const pixel = document.createElement("span");
  pixel.style.setProperty("--on", COLORS[Math.floor((i * COLORS.length) / PIXELS)]);
  pixel.style.animationDelay = `${(i % 8) * 0.08}s`;
  $("pixels").append(pixel);
}

function setPixels(fraction) {
  const lit = Math.round(fraction * PIXELS);
  [...$("pixels").children].forEach((pixel, i) => pixel.classList.toggle("lit", i < lit));
}

function renderLoading(model) {
  setError("loading-error", model.phase === "failed" ? model.error : null);
  const waiting = model.phase === "checking" || (model.phase === "downloading" && !model.total);
  $("pixels").classList.toggle("waiting", waiting);
  if (model.phase === "downloading" && model.total) {
    setPixels(Math.min(1, model.done / model.total));
    const left = timeLeft(model.done, model.total);
    $("progress-text").textContent =
      `${megabytes(model.done)} / ${megabytes(model.total)} MB${left}`;
  } else if (model.phase === "downloading") {
    setPixels(0);
    $("progress-text").textContent = `${megabytes(model.done)} MB downloaded`;
  } else if (model.phase === "failed") {
    setPixels(0);
    $("progress-text").textContent = "The download stopped.";
  } else {
    setPixels(0);
    $("progress-text").textContent = "Looking for the model…";
  }
}

function setStatus(kind, label, detail) {
  $("status").className = `status ${kind}`;
  $("status-text").textContent = label;
  $("status-detail").textContent = detail;
}

async function renderHome(state) {
  let health = null;
  try {
    health = JSON.parse(await invoke("health"));
  } catch {
    // Not answering yet, or stopped: the process state says which.
  }
  if (health) {
    setStatus(
      "ok",
      "Protecting",
      "Your tools' requests go through Alias: names, addresses and identifiers are masked " +
        "before they reach Mistral.",
    );
    setError("bridge-error", null);
  } else if (state.bridge_running) {
    setStatus("starting", "Starting", "The bridge is starting; it takes a few seconds.");
    setError("bridge-error", null);
  } else {
    const code = state.exit_code === null ? "" : ` (exit code ${state.exit_code})`;
    setStatus("stopped", "Stopped", `The bridge stopped${code}: your tools can't reach Mistral.`);
    setError("bridge-error", state.last_lines.join("\n") || "It wrote nothing before stopping.");
  }
}

// The key as the app knows it, from memory: {stored, error}. The keychain is not asked again.
async function keyState() {
  try {
    return await invoke("key_status");
  } catch (error) {
    return { stored: false, error: String(error) };
  }
}

function renderKey(key) {
  setError("key-error", key.error || null);
  $("key-detail").hidden = Boolean(key.error);
  $("key-detail").textContent = key.stored
    ? "Saved in the macOS keychain. Your tools never need it."
    : "No key saved: Alias passes on the key each tool sends.";
  $("replace").textContent = key.stored ? "Replace the key" : "Add a key";
  $("delete").hidden = !key.stored;
}

async function loadToken() {
  let token = "Add a key first";
  try {
    token = await invoke("token");
  } catch {
    // No key, so no token yet: the field says so.
  }
  for (const field of document.querySelectorAll(".token")) field.textContent = token;
}

let ticking = false; // one refresh at a time
async function tick() {
  if (ticking) return;
  ticking = true;
  try {
    const state = await invoke("state");
    if (state.model.phase !== "ready") {
      if (screen !== "loading") show("loading");
      renderLoading(state.model);
      return;
    }
    if (screen === "loading") {
      const key = await keyState();
      show(key.stored || key.error ? "home" : "step1");
    }
    if (screen === "home") {
      renderKey(await keyState());
      await renderHome(state);
    }
  } catch {
    // The next refresh tries again.
  } finally {
    ticking = false;
  }
}

$("key-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const key = $("key").value;
  $("key-save").disabled = true;
  $("key-result").className = "result";
  $("key-result").textContent = "Checking the key with Mistral…";
  try {
    await invoke("set_key", { key });
    $("key").value = "";
    $("key-result").className = "result ok";
    $("key-result").textContent = "Mistral accepted the key. It is saved.";
    setTimeout(() => show(keyBack === "home" ? "home" : "step3"), 900);
  } catch (error) {
    $("key-result").className = "result bad";
    $("key-result").textContent = brief(error);
  } finally {
    $("key-save").disabled = false;
  }
});

$("step2-back").addEventListener("click", () => show(keyBack));

$("finish").addEventListener("click", () => {
  keyBack = "home";
  show("home");
});

$("replace").addEventListener("click", () => {
  keyBack = "home";
  show("step2");
});

let deleteArmed;
$("delete").addEventListener("click", async () => {
  if (!deleteArmed) {
    $("delete").textContent = "Click again to delete";
    deleteArmed = setTimeout(() => {
      deleteArmed = undefined;
      $("delete").textContent = "Delete the key";
    }, 4000);
    return;
  }
  clearTimeout(deleteArmed);
  deleteArmed = undefined;
  $("delete").textContent = "Delete the key";
  try {
    await invoke("delete_key");
    say("Key deleted.");
    keyBack = "home";
    show("step2");
  } catch (error) {
    say(brief(error));
  }
});

$("keychain-retry").addEventListener("click", async () => {
  try {
    renderKey(await invoke("retry_keychain"));
    await loadToken();
  } catch (error) {
    setError("key-error", error);
  }
});

$("restart").addEventListener("click", async () => {
  try {
    await invoke("retry");
    say("The bridge restarts.");
  } catch (error) {
    setError("bridge-error", error);
  }
});

$("retry-download").addEventListener("click", async () => {
  samples = [];
  try {
    await invoke("retry");
  } catch (error) {
    setError("loading-error", error);
  }
});

for (const button of document.querySelectorAll("[data-go]")) {
  button.addEventListener("click", () => {
    if (button.dataset.go === "step1") keyBack = "step1";
    show(button.dataset.go);
  });
}

async function copy(text) {
  try {
    await navigator.clipboard.writeText(text);
    say("Copied.");
  } catch {
    say("Copy failed: select the text by hand.");
  }
}

for (const button of document.querySelectorAll("[data-copy]")) {
  button.addEventListener("click", () => copy($(button.dataset.copy).textContent));
}
for (const button of document.querySelectorAll("[data-copy-token]")) {
  button.addEventListener("click", () => copy(document.querySelector(".token").textContent));
}

tick();
setInterval(tick, 1000);
