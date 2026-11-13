// Alias, the macOS app. It runs the standalone `alias-pii` executable shipped next to this one:
// first `alias-pii fetch --progress`, which downloads the detection model once and reports its
// progress as JSON lines, then `alias-pii serve`, the bridge, while the app is open. The window
// follows both through the `state` command. The app alone uses the macOS keychain: one item
// of its own holds the Mistral key and the local token, read once per launch and kept in memory.
// The bridge gets both on a pipe (`serve --secrets-stdin`) and never touches the keychain, so
// macOS has one program to ask about, the app, which created the item. A new key is checked with
// Mistral first (`alias-pii key check --stdin`, on a pipe, never on a command line); the bridge
// restarts after a change so it uses the new key. Commands are async, so running the bundled
// executable (seconds, as it unpacks itself) never freezes the window.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::collections::VecDeque;
use std::io::{BufRead, BufReader, Read, Write};
use std::net::{SocketAddr, TcpStream};
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Duration;

use serde::{Deserialize, Serialize};
use tauri::{AppHandle, Manager, RunEvent, State};

const BRIDGE: &str = "127.0.0.1:8001";
const LOG_LINES: usize = 40;
/// The app's keychain item (not the command line's `alias-pii` items).
const KEYCHAIN_SERVICE: &str = "Alias";
const KEYCHAIN_ACCOUNT: &str = "bridge";

/// What the app's keychain item holds: the Mistral key and the local token tools send instead.
#[derive(Clone, Serialize, Deserialize)]
struct Secrets {
    key: String,
    token: String,
}

/// The keychain item as last read: not read yet, absent, read, or unreadable (and why).
#[derive(Clone)]
enum Keychain {
    Unread,
    Missing,
    Stored(Secrets),
    Unreadable(String),
}

/// What the window shows about the key.
#[derive(Serialize)]
struct KeyState {
    stored: bool,
    error: Option<String>,
}

/// The last lines a process wrote on its error output (states and counts, never masked text).
type Log = Arc<Mutex<VecDeque<String>>>;

/// Where the detection model stands: "checking", "downloading", "ready" or "failed".
#[derive(Clone, Serialize)]
struct Model {
    phase: &'static str,
    done: u64,
    total: Option<u64>,
    error: Option<String>,
}

impl Model {
    fn at(phase: &'static str) -> Self {
        Model { phase, done: 0, total: None, error: None }
    }

    fn failed(error: String) -> Self {
        Model { error: Some(error), ..Model::at("failed") }
    }
}

/// What the window shows: the model, and whether the bridge process runs (else why it stopped).
#[derive(Serialize)]
struct AppState {
    model: Model,
    bridge_running: bool,
    exit_code: Option<i32>,
    last_lines: Vec<String>,
}

/// The app's processes. Each start gets a new log, so an earlier process still writing never
/// mixes its lines into the current one's.
struct Alias {
    fetch: Mutex<Option<Child>>,
    bridge: Mutex<Option<Child>>,
    log: Mutex<Log>,
    model: Mutex<Model>,
    /// Set when the app quits, so a download finishing at that moment starts no bridge.
    exiting: AtomicBool,
    keychain: Mutex<Keychain>,
}

fn keychain_entry() -> Result<keyring::Entry, String> {
    keyring::Entry::new(KEYCHAIN_SERVICE, KEYCHAIN_ACCOUNT).map_err(|e| e.to_string())
}

/// Reads the app's keychain item into memory (the only read of a launch, unless the user asks
/// to try again after refusing access).
fn load_keychain(alias: &Alias) -> Keychain {
    fn read_item() -> Result<String, KeychainError> {
        let entry = keychain_entry()?;
        Ok(entry.get_password()?)
    }
    let read = match read_item() {
        Ok(text) => match serde_json::from_str::<Secrets>(&text) {
            Ok(secrets) => Keychain::Stored(secrets),
            Err(_) => {
                Keychain::Unreadable("The keychain item is damaged: save the key again.".into())
            }
        },
        Err(KeychainError::Missing) => Keychain::Missing,
        Err(KeychainError::Other(error)) => {
            Keychain::Unreadable(format!("Alias could not read the macOS keychain: {error}"))
        }
    };
    if let Ok(mut current) = alias.keychain.lock() {
        *current = read.clone();
    }
    read
}

/// A keychain failure: no item yet, or anything else (access refused, keychain locked…).
enum KeychainError {
    Missing,
    Other(String),
}

impl From<keyring::Error> for KeychainError {
    fn from(error: keyring::Error) -> Self {
        match error {
            keyring::Error::NoEntry => KeychainError::Missing,
            other => KeychainError::Other(other.to_string()),
        }
    }
}

impl From<String> for KeychainError {
    fn from(error: String) -> Self {
        KeychainError::Other(error)
    }
}

/// 32 random bytes as hex: the local token tools send as their API key.
fn new_token() -> Result<String, String> {
    let mut bytes = [0u8; 32];
    std::fs::File::open("/dev/urandom")
        .and_then(|mut random| random.read_exact(&mut bytes))
        .map_err(|e| e.to_string())?;
    Ok(bytes.iter().map(|b| format!("{b:02x}")).collect())
}

fn stored_secrets(alias: &Alias) -> Option<Secrets> {
    match alias.keychain.lock().ok()?.clone() {
        Keychain::Stored(secrets) => Some(secrets),
        _ => None,
    }
}

/// The bundled `alias-pii` executable (Tauri's externalBin sits next to the app's executable).
fn executable() -> Result<PathBuf, String> {
    let app = std::env::current_exe().map_err(|e| e.to_string())?;
    let folder = app.parent().ok_or("no folder for the app's executable")?;
    Ok(folder.join("alias-pii"))
}

/// Stops a process with SIGTERM, not SIGKILL: the one-file executable is a launcher that runs the
/// real process as its own child and passes SIGTERM on to it, while SIGKILL would stop the
/// launcher only. SIGKILL is the fallback after five seconds.
fn stop(child: &mut Option<Child>) {
    if let Some(mut running) = child.take() {
        // Already exited (and maybe reaped by `state`): its pid may belong to another process.
        if let Ok(Some(_)) = running.try_wait() {
            return;
        }
        if let Ok(pid) = libc::pid_t::try_from(running.id()) {
            // SAFETY: kill(2) on the pid of a child this process started and has not reaped yet.
            unsafe { libc::kill(pid, libc::SIGTERM) };
            for _ in 0..50 {
                if let Ok(Some(_)) = running.try_wait() {
                    return;
                }
                std::thread::sleep(Duration::from_millis(100));
            }
        }
        let _ = running.kill();
        let _ = running.wait();
    }
}

/// Reads a process's error output until it closes, keeping its last lines. A progress bar
/// rewrites its line with `\r`, so `\r` ends a line too.
fn keep_lines(mut from: impl Read, log: &Mutex<VecDeque<String>>) {
    let mut buffer = [0u8; 4096];
    let mut line = Vec::new();
    loop {
        let read = match from.read(&mut buffer) {
            Ok(0) | Err(_) => break,
            Ok(read) => read,
        };
        for &byte in &buffer[..read] {
            if byte != b'\n' && byte != b'\r' {
                line.push(byte);
                continue;
            }
            let text = String::from_utf8_lossy(&line).trim().to_string();
            line.clear();
            if text.is_empty() {
                continue;
            }
            if let Ok(mut lines) = log.lock() {
                if lines.len() == LOG_LINES {
                    lines.pop_front();
                }
                lines.push_back(text);
            }
        }
    }
}

/// Starts `alias-pii` with `args` in the background, its error output kept in a new log that
/// becomes the app's current one.
fn spawn_logged(
    alias: &Alias,
    args: &[&str],
    stdout: Stdio,
    input: Option<String>,
) -> Result<(Child, Log), String> {
    let log: Log = Arc::default();
    *alias.log.lock().map_err(|e| e.to_string())? = Arc::clone(&log);
    let mut child = Command::new(executable()?)
        .args(args)
        .stdin(if input.is_some() { Stdio::piped() } else { Stdio::null() })
        .stdout(stdout)
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|e| format!("Alias could not start its bridge program: {e}"))?;
    if let Some(stderr) = child.stderr.take() {
        let lines = Arc::clone(&log);
        std::thread::spawn(move || keep_lines(stderr, &lines));
    }
    if let (Some(text), Some(mut stdin)) = (input, child.stdin.take()) {
        stdin.write_all(format!("{text}\n").as_bytes()).map_err(|e| e.to_string())?;
    }
    Ok((child, log))
}

fn start_bridge(alias: &Alias) -> Result<(), String> {
    let mut bridge = alias.bridge.lock().map_err(|e| e.to_string())?;
    stop(&mut bridge);
    if alias.exiting.load(Ordering::SeqCst) {
        return Ok(());
    }
    // The key and token on a pipe, or `{}` without a key (tools then send their own key).
    let secrets = match stored_secrets(alias) {
        Some(secrets) => serde_json::to_string(&secrets).map_err(|e| e.to_string())?,
        None => "{}".into(),
    };
    let args = ["serve", "--secrets-stdin"];
    let (child, _) = spawn_logged(alias, &args, Stdio::null(), Some(secrets))?;
    *bridge = Some(child);
    Ok(())
}

fn set_model(alias: &Alias, model: Model) {
    if let Ok(mut current) = alias.model.lock() {
        *current = model;
    }
}

/// Downloads the model if it is not on the disk yet, then starts the bridge. Runs on its own
/// thread; the window follows it through `state`.
fn prepare(app: AppHandle) {
    let alias = app.state::<Alias>();
    set_model(&alias, Model::at("checking"));
    let fetch = spawn_logged(&alias, &["fetch", "--progress"], Stdio::piped(), None);
    let (mut child, log) = match fetch {
        Ok(started) => started,
        Err(error) => return set_model(&alias, Model::failed(error)),
    };
    let stdout = child.stdout.take();
    if let Ok(mut fetch) = alias.fetch.lock() {
        *fetch = Some(child);
    }
    let (mut ready, mut error) = (false, None);
    let lines =
        stdout.into_iter().flat_map(|out| BufReader::new(out).lines().map_while(Result::ok));
    for line in lines {
        let Ok(value) = serde_json::from_str::<serde_json::Value>(&line) else {
            continue;
        };
        if value.get("ready").and_then(|v| v.as_bool()) == Some(true) {
            ready = true;
        } else if let Some(text) = value.get("error").and_then(|v| v.as_str()) {
            error = Some(text.to_string());
        } else if let Some(done) = value.get("done").and_then(|v| v.as_u64()) {
            let total = value.get("total").and_then(|v| v.as_u64());
            set_model(&alias, Model { phase: "downloading", done, total, error: None });
        }
    }
    if let Ok(mut fetch) = alias.fetch.lock() {
        if let Some(mut finished) = fetch.take() {
            let _ = finished.wait();
        }
    }
    if !ready {
        let last = log.lock().ok().and_then(|lines| lines.back().cloned());
        let reason = error.or(last).unwrap_or_else(|| "The download stopped.".into());
        return set_model(&alias, Model::failed(reason));
    }
    load_keychain(&alias);
    // The bridge first, so the window never sees a ready model without a bridge process.
    match start_bridge(&alias) {
        Ok(()) => set_model(&alias, Model::at("ready")),
        Err(error) => set_model(&alias, Model::failed(error)),
    }
}

fn model_ready(alias: &Alias) -> bool {
    alias.model.lock().map(|m| m.phase == "ready").unwrap_or(false)
}

/// Runs `alias-pii` with `args`, optionally writing `input` on its standard input.
fn run(args: &[&str], input: Option<&str>) -> Result<String, String> {
    let mut child = Command::new(executable()?)
        .args(args)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|e| e.to_string())?;
    let mut stdin = child.stdin.take().ok_or("no standard input")?;
    if let Some(text) = input {
        stdin.write_all(format!("{text}\n").as_bytes()).map_err(|e| e.to_string())?;
    }
    drop(stdin);
    let output = child.wait_with_output().map_err(|e| e.to_string())?;
    let text = |bytes: &[u8]| String::from_utf8_lossy(bytes).trim().to_string();
    if output.status.success() {
        Ok(text(&output.stdout))
    } else {
        Err(text(&output.stderr))
    }
}

/// The bridge's `/health` answer (JSON text), read over a plain socket: the bridge refuses
/// requests from a web page, which the window is.
#[tauri::command]
async fn health() -> Result<String, String> {
    let address: SocketAddr = BRIDGE.parse().map_err(|_| "bad address")?;
    let mut stream =
        TcpStream::connect_timeout(&address, Duration::from_secs(2)).map_err(|e| e.to_string())?;
    stream.set_read_timeout(Some(Duration::from_secs(3))).map_err(|e| e.to_string())?;
    let request = format!("GET /health HTTP/1.1\r\nHost: {BRIDGE}\r\nConnection: close\r\n\r\n");
    stream.write_all(request.as_bytes()).map_err(|e| e.to_string())?;
    let mut answer = String::new();
    stream.read_to_string(&mut answer).map_err(|e| e.to_string())?;
    let body = answer.split("\r\n\r\n").nth(1).ok_or("no answer from the bridge")?;
    Ok(body.to_string())
}

/// The model's state, whether the bridge process still runs, its exit code and last log lines.
#[tauri::command]
async fn state(alias: State<'_, Alias>) -> Result<AppState, String> {
    let model = alias.model.lock().map_err(|e| e.to_string())?.clone();
    let (bridge_running, exit_code) = {
        let mut bridge = alias.bridge.lock().map_err(|e| e.to_string())?;
        match bridge.as_mut().map(Child::try_wait) {
            Some(Ok(None)) => (true, None),
            Some(Ok(Some(status))) => (false, status.code()),
            _ => (false, None),
        }
    };
    let log = Arc::clone(&*alias.log.lock().map_err(|e| e.to_string())?);
    let last_lines = match log.lock() {
        Ok(lines) => lines.iter().skip(lines.len().saturating_sub(8)).cloned().collect(),
        Err(_) => Vec::new(),
    };
    Ok(AppState { model, bridge_running, exit_code, last_lines })
}

/// Starts again what failed: the download if the model is missing, else the bridge.
#[tauri::command]
async fn retry(app: AppHandle, alias: State<'_, Alias>) -> Result<(), String> {
    if model_ready(&alias) {
        return start_bridge(&alias);
    }
    let busy = alias.fetch.lock().map(|f| f.is_some()).unwrap_or(true);
    if !busy {
        std::thread::spawn(move || prepare(app));
    }
    Ok(())
}

/// Whether a key is stored, from memory (the keychain is not asked again).
#[tauri::command]
async fn key_status(alias: State<'_, Alias>) -> Result<KeyState, String> {
    let keychain = alias.keychain.lock().map_err(|e| e.to_string())?.clone();
    Ok(match keychain {
        Keychain::Stored(_) => KeyState { stored: true, error: None },
        Keychain::Unreadable(error) => KeyState { stored: false, error: Some(error) },
        Keychain::Missing | Keychain::Unread => KeyState { stored: false, error: None },
    })
}

#[tauri::command]
async fn token(alias: State<'_, Alias>) -> Result<String, String> {
    stored_secrets(&alias).map(|s| s.token).ok_or_else(|| "Add a key first.".into())
}

/// Reads the keychain item again (after the user refused access, or unlocked the keychain),
/// then restarts the bridge with what it found.
#[tauri::command]
async fn retry_keychain(alias: State<'_, Alias>) -> Result<KeyState, String> {
    load_keychain(&alias);
    if model_ready(&alias) {
        start_bridge(&alias)?;
    }
    key_status(alias).await
}

/// Stores the key if Mistral accepts it, keeping the local token tools already use, then
/// restarts the bridge so it uses the key.
#[tauri::command]
async fn set_key(key: String, alias: State<'_, Alias>) -> Result<String, String> {
    let key = key.trim();
    if key.is_empty() {
        return Err("Paste a key first.".into());
    }
    run(&["key", "check", "--stdin"], Some(key))?;
    let token = match stored_secrets(&alias) {
        Some(secrets) => secrets.token,
        None => new_token()?,
    };
    let secrets = Secrets { key: key.to_string(), token };
    let text = serde_json::to_string(&secrets).map_err(|e| e.to_string())?;
    keychain_entry()?
        .set_password(&text)
        .map_err(|e| format!("Alias could not save the key in the macOS keychain: {e}"))?;
    *alias.keychain.lock().map_err(|e| e.to_string())? = Keychain::Stored(secrets);
    if model_ready(&alias) {
        start_bridge(&alias)?;
    }
    Ok("Mistral accepted the key. It is saved.".into())
}

#[tauri::command]
async fn delete_key(alias: State<'_, Alias>) -> Result<String, String> {
    match keychain_entry()?.delete_credential() {
        Ok(()) | Err(keyring::Error::NoEntry) => {}
        Err(error) => return Err(format!("Alias could not delete the key: {error}")),
    }
    *alias.keychain.lock().map_err(|e| e.to_string())? = Keychain::Missing;
    if model_ready(&alias) {
        start_bridge(&alias)?;
    }
    Ok("Key deleted.".into())
}

fn main() {
    tauri::Builder::default()
        .manage(Alias {
            fetch: Mutex::new(None),
            bridge: Mutex::new(None),
            log: Mutex::new(Arc::default()),
            model: Mutex::new(Model::at("checking")),
            exiting: AtomicBool::new(false),
            keychain: Mutex::new(Keychain::Unread),
        })
        .setup(|app| {
            let handle = app.handle().clone();
            std::thread::spawn(move || prepare(handle));
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            health,
            state,
            retry,
            key_status,
            token,
            retry_keychain,
            set_key,
            delete_key
        ])
        .build(tauri::generate_context!())
        .expect("the app could not start")
        .run(|app, event| {
            if let RunEvent::Exit = event {
                let alias = app.state::<Alias>();
                alias.exiting.store(true, Ordering::SeqCst);
                if let Ok(mut fetch) = alias.fetch.lock() {
                    stop(&mut fetch);
                }
                if let Ok(mut bridge) = alias.bridge.lock() {
                    stop(&mut bridge);
                };
            }
        });
}
