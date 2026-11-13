// Alias, the macOS app. It runs the standalone `alias-pii` executable shipped next to this one:
// first `alias-pii fetch --progress`, which downloads the detection model once and reports its
// progress as JSON lines, then `alias-pii serve`, the bridge, while the app is open. The window
// follows both through the `state` command and sets or deletes the Mistral key, which goes to
// `alias-pii key set --stdin --check` on a pipe (never on a command line) and is stored only if
// Mistral accepts it; the bridge restarts after a change so it uses the new key. Commands are
// async, so running the bundled executable (seconds, as it unpacks itself) never freezes the
// window.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::collections::VecDeque;
use std::io::{BufRead, BufReader, Read, Write};
use std::net::{SocketAddr, TcpStream};
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Duration;

use serde::Serialize;
use tauri::{AppHandle, Manager, RunEvent, State};

const BRIDGE: &str = "127.0.0.1:8001";
const LOG_LINES: usize = 40;

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
fn spawn_logged(alias: &Alias, args: &[&str], stdout: Stdio) -> Result<(Child, Log), String> {
    let log: Log = Arc::default();
    *alias.log.lock().map_err(|e| e.to_string())? = Arc::clone(&log);
    let mut child = Command::new(executable()?)
        .args(args)
        .stdin(Stdio::null())
        .stdout(stdout)
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|e| format!("Alias could not start its bridge program: {e}"))?;
    if let Some(stderr) = child.stderr.take() {
        let lines = Arc::clone(&log);
        std::thread::spawn(move || keep_lines(stderr, &lines));
    }
    Ok((child, log))
}

fn start_bridge(alias: &Alias) -> Result<(), String> {
    let mut bridge = alias.bridge.lock().map_err(|e| e.to_string())?;
    stop(&mut bridge);
    if alias.exiting.load(Ordering::SeqCst) {
        return Ok(());
    }
    let (child, _) = spawn_logged(alias, &["serve"], Stdio::null())?;
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
    let (mut child, log) = match spawn_logged(&alias, &["fetch", "--progress"], Stdio::piped()) {
        Ok(started) => started,
        Err(error) => return set_model(&alias, Model::failed(error)),
    };
    let stdout = child.stdout.take();
    if let Ok(mut fetch) = alias.fetch.lock() {
        *fetch = Some(child);
    }
    let (mut ready, mut error) = (false, None);
    let lines = stdout.into_iter().flat_map(|out| BufReader::new(out).lines().map_while(Result::ok));
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

#[tauri::command]
async fn key_status() -> Result<String, String> {
    run(&["key", "status"], None)
}

#[tauri::command]
async fn token() -> Result<String, String> {
    run(&["key", "token"], None)
}

/// Stores the key if Mistral accepts it, then restarts the bridge so it uses the key.
#[tauri::command]
async fn set_key(key: String, alias: State<'_, Alias>) -> Result<String, String> {
    let key = key.trim();
    if key.is_empty() {
        return Err("Paste a key first.".into());
    }
    let message = run(&["key", "set", "--stdin", "--check"], Some(key))?;
    if model_ready(&alias) {
        start_bridge(&alias)?;
    }
    Ok(message)
}

#[tauri::command]
async fn delete_key(alias: State<'_, Alias>) -> Result<String, String> {
    let message = run(&["key", "delete"], None)?;
    if model_ready(&alias) {
        start_bridge(&alias)?;
    }
    Ok(message)
}

fn main() {
    tauri::Builder::default()
        .manage(Alias {
            fetch: Mutex::new(None),
            bridge: Mutex::new(None),
            log: Mutex::new(Arc::default()),
            model: Mutex::new(Model::at("checking")),
            exiting: AtomicBool::new(false),
        })
        .setup(|app| {
            let handle = app.handle().clone();
            std::thread::spawn(move || prepare(handle));
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            health, state, retry, key_status, token, set_key, delete_key
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
                }
            }
        });
}
