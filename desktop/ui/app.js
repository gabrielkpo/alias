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

function renderLoading(model) {
  const bar = $("bar-fill");
  setError("loading-error", model.phase === "failed" ? model.error : null);
  if (model.phase === "downloading" && model.total) {
    bar.classList.remove("unknown");
    bar.style.width = `${Math.min(100, (100 * model.done) / model.total)}%`;
    const left = timeLeft(model.done, model.total);
    $("progress-text").textContent =
      `${megabytes(model.done)} of ${megabytes(model.total)} MB${left}`;
  } else if (model.phase === "downloading") {
    bar.classList.add("unknown");
    $("progress-text").textContent = `${megabytes(model.done)} MB downloaded`;
  } else if (model.phase === "failed") {
    bar.classList.remove("unknown");
    $("progress-text").textContent = "The download stopped.";
  } else {
    bar.classList.add("unknown");
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

async function keyStored() {
  try {
    return (await invoke("key_status")).startsWith("A key is stored");
  } catch {
    return false;
  }
}

async function loadToken() {
  try {
    const token = await invoke("token");
    for (const field of document.querySelectorAll(".token")) field.textContent = token;
  } catch {
    for (const field of document.querySelectorAll(".token")) field.textContent = "Save a key first";
  }
}

let ticking = false; // one refresh at a time: asking the keychain takes seconds
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
    if (screen === "loading") show((await keyStored()) ? "home" : "step1");
    if (screen === "home") await renderHome(state);
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
