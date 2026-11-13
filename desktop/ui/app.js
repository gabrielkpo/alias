// The window of the Alias app: shows whether the bridge runs (and why it stopped), sets or
// deletes the Mistral key and shows the local token. Every action goes through the app's Rust
// commands (window.__TAURI__.core.invoke); texts are set with textContent only.
const invoke = window.__TAURI__.core.invoke;
const $ = (id) => document.getElementById(id);

// A failure shows one short line; the full text stays one click away.
function brief(text) {
  const lines = String(text).split("\n").map((line) => line.trim()).filter(Boolean);
  const line = lines.at(-1) || "No details.";
  return line.length > 140 ? `${line.slice(0, 140)}…` : line;
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

function setStatus(kind, label, detail) {
  $("status").className = `status ${kind}`;
  $("status-text").textContent = label;
  $("status-detail").textContent = detail;
}

async function refreshBridge() {
  let health = null;
  try {
    health = JSON.parse(await invoke("health"));
  } catch {
    // Not answering yet, or stopped: bridge_state says which.
  }
  let state = { running: true, exit_code: null, last_lines: [] };
  try {
    state = await invoke("bridge_state");
  } catch {
    // Keep the default: the health answer alone decides.
  }
  $("restart").hidden = true;
  if (health) {
    const model = health.detector === "rules+model";
    setStatus(
      "ok",
      "Running",
      model
        ? "Names, addresses and identifiers are masked (rules + model)."
        : "Rules only: names and addresses are not masked.",
    );
    setError("bridge-error", null);
  } else if (state.running) {
    const last = state.last_lines.at(-1);
    const progress = last && last.match(/(\d{1,3})%\|/); // the download's progress bar
    setStatus(
      "starting",
      "Starting",
      progress
        ? `Downloading the model (once): ${progress[1]}%`
        : last
          ? brief(last)
          : "The first launch downloads the model (about 600 MB) once.",
    );
    setError("bridge-error", null);
  } else {
    const code = state.exit_code === null ? "" : ` (exit code ${state.exit_code})`;
    setStatus("stopped", "Stopped", `The bridge stopped${code}.`);
    setError("bridge-error", state.last_lines.join("\n") || "It wrote nothing before stopping.");
    $("restart").hidden = false;
  }
}

async function refreshKey() {
  try {
    const stored = (await invoke("key_status")).startsWith("A key is stored");
    $("key-badge").textContent = stored ? "Saved" : "Not set";
    $("key-badge").className = stored ? "badge ok" : "badge";
    $("key").placeholder = stored ? "Paste a new key to replace it" : "Paste your Mistral key";
    $("delete").hidden = !stored;
    $("token-card").hidden = !stored;
    if (stored) $("token").textContent = await invoke("token");
    setError("key-error", null);
  } catch (error) {
    $("key-badge").textContent = "Unavailable";
    $("key-badge").className = "badge";
    setError("key-error", error);
  }
}

$("key-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const key = $("key").value;
  $("key").value = "";
  try {
    await invoke("set_key", { key });
    say("Key saved; the bridge restarts.");
  } catch (error) {
    setError("key-error", error);
  }
  await refreshKey();
  await refreshBridge();
});

$("delete").addEventListener("click", async () => {
  try {
    await invoke("delete_key");
    say("Key deleted; the bridge restarts.");
  } catch (error) {
    setError("key-error", error);
  }
  await refreshKey();
  await refreshBridge();
});

$("restart").addEventListener("click", async () => {
  try {
    await invoke("restart_bridge");
    say("The bridge restarts.");
  } catch (error) {
    setError("bridge-error", error);
  }
  await refreshBridge();
});

for (const button of document.querySelectorAll("[data-copy]")) {
  button.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText($(button.dataset.copy).textContent);
      say("Copied.");
    } catch {
      say("Copy failed: select the text by hand.");
    }
  });
}

refreshBridge();
refreshKey();
setInterval(refreshBridge, 2000);
