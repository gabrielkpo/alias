// The window of the Alias app: polls the bridge's health, shows whether a Mistral key is stored,
// sets or deletes it and shows the local token. Every action goes through the app's Rust
// commands (window.__TAURI__.core.invoke); texts are set with textContent only.
const invoke = window.__TAURI__.core.invoke;
const $ = (id) => document.getElementById(id);

function say(text) {
  $("message").textContent = text;
}

async function refreshHealth() {
  try {
    const health = JSON.parse(await invoke("health"));
    $("state").textContent = `Running (detector: ${health.detector}).`;
    $("state").className = "state ok";
  } catch {
    $("state").textContent = "Starting… (or stopped)";
    $("state").className = "state";
  }
}

async function refreshKey() {
  try {
    const status = await invoke("key_status");
    const stored = status.startsWith("A key is stored");
    $("key-state").textContent = stored ? "A key is saved." : "No key saved.";
    $("token-section").hidden = !stored;
    if (stored) $("token").textContent = await invoke("token");
  } catch (error) {
    $("key-state").textContent = `Keychain unavailable: ${error}`;
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
    say(`The key was not saved: ${error}`);
  }
  await refreshKey();
});

$("delete").addEventListener("click", async () => {
  try {
    await invoke("delete_key");
    say("Key deleted; the bridge restarts.");
  } catch (error) {
    say(`Failed: ${error}`);
  }
  await refreshKey();
});

$("copy").addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText($("token").textContent);
    say("Token copied.");
  } catch {
    say("Copy failed: select the token by hand.");
  }
});

refreshHealth();
refreshKey();
setInterval(refreshHealth, 2000);
