// Alias, the macOS app: runs Alias Bridge (the standalone `alias-pii` executable shipped next to
// this one) in the background while the app is open, and gives the window its commands: the
// bridge's health, whether it still runs and its last log lines, restarting it, whether a Mistral
// key is in the keychain, the local token, and setting or deleting the key. The key goes to
// `alias-pii key set --stdin` on a pipe, never on a command line; the bridge restarts after a
// change so it uses the new key. The commands are async, so
// running the bundled executable (seconds, as it unpacks itself) never freezes the window.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::collections::VecDeque;
use std::io::{Read, Write};
use std::net::{SocketAddr, TcpStream};
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::{Arc, Mutex};
use std::time::Duration;

use tauri::{Manager, RunEvent, State};

const BRIDGE: &str = "127.0.0.1:8001";
const LOG_LINES: usize = 40;

/// The running bridge, so it can be restarted and stopped with the app, and the last lines of its
/// error output (states and counts, never the text it masks), to show why it stopped.
struct Bridge {
    child: Mutex<Option<Child>>,
    /// A new buffer for each start, so a previous bridge still writing never mixes in its lines.
    log: Mutex<Arc<Mutex<VecDeque<String>>>>,
}

/// What the window shows about the bridge process.
#[derive(serde::Serialize)]
struct BridgeState {
    running: bool,
    exit_code: Option<i32>,
    last_lines: Vec<String>,
}

/// The bundled `alias-pii` executable (Tauri's externalBin sits next to the app's executable).
fn executable() -> Result<PathBuf, String> {
    let app = std::env::current_exe().map_err(|e| e.to_string())?;
    let folder = app.parent().ok_or("no folder for the app's executable")?;
    Ok(folder.join("alias-pii"))
}

/// Stops the bridge with SIGTERM, not SIGKILL: the one-file executable is a launcher that runs the
/// bridge as its own child and passes SIGTERM on to it, while SIGKILL would stop the launcher only
/// and leave the bridge running. SIGKILL is the fallback after five seconds.
fn stop(child: &mut Option<Child>) {
    if let Some(mut running) = child.take() {
        // Already exited (and maybe reaped by bridge_state): its pid may belong to another process.
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

/// Reads the bridge's error output until it closes, keeping its last lines. A progress bar
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

fn start(bridge: &Bridge) -> Result<(), String> {
    let mut child = bridge.child.lock().map_err(|e| e.to_string())?;
    stop(&mut child);
    let log = Arc::new(Mutex::new(VecDeque::new()));
    *bridge.log.lock().map_err(|e| e.to_string())? = Arc::clone(&log);
    let mut spawned = Command::new(executable()?)
        .arg("serve")
        .stdin(Stdio::null())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|e| format!("the bridge did not start: {e}"))?;
    if let Some(stderr) = spawned.stderr.take() {
        std::thread::spawn(move || keep_lines(stderr, &log));
    }
    *child = Some(spawned);
    Ok(())
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

/// Whether the bridge process still runs, its exit code if it stopped, and its last log lines.
#[tauri::command]
async fn bridge_state(bridge: State<'_, Bridge>) -> Result<BridgeState, String> {
    let (running, exit_code) = {
        let mut child = bridge.child.lock().map_err(|e| e.to_string())?;
        match child.as_mut().map(Child::try_wait) {
            Some(Ok(None)) => (true, None),
            Some(Ok(Some(status))) => (false, status.code()),
            _ => (false, None),
        }
    };
    let log = Arc::clone(&*bridge.log.lock().map_err(|e| e.to_string())?);
    let last_lines = match log.lock() {
        Ok(lines) => lines.iter().skip(lines.len().saturating_sub(8)).cloned().collect(),
        Err(_) => Vec::new(),
    };
    Ok(BridgeState { running, exit_code, last_lines })
}

#[tauri::command]
async fn restart_bridge(bridge: State<'_, Bridge>) -> Result<(), String> {
    start(&bridge)
}

#[tauri::command]
async fn key_status() -> Result<String, String> {
    run(&["key", "status"], None)
}

#[tauri::command]
async fn token() -> Result<String, String> {
    run(&["key", "token"], None)
}

#[tauri::command]
async fn set_key(key: String, bridge: State<'_, Bridge>) -> Result<String, String> {
    let key = key.trim();
    if key.is_empty() {
        return Err("no key given".into());
    }
    let message = run(&["key", "set", "--stdin"], Some(key))?;
    start(&bridge)?;
    Ok(message)
}

#[tauri::command]
async fn delete_key(bridge: State<'_, Bridge>) -> Result<String, String> {
    let message = run(&["key", "delete"], None)?;
    start(&bridge)?;
    Ok(message)
}

fn main() {
    tauri::Builder::default()
        .manage(Bridge { child: Mutex::new(None), log: Mutex::new(Arc::default()) })
        .setup(|app| {
            start(&app.state::<Bridge>()).map_err(Box::<dyn std::error::Error>::from)?;
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            health,
            bridge_state,
            restart_bridge,
            key_status,
            token,
            set_key,
            delete_key
        ])
        .build(tauri::generate_context!())
        .expect("the app could not start")
        .run(|app, event| {
            if let RunEvent::Exit = event {
                if let Ok(mut child) = app.state::<Bridge>().child.lock() {
                    stop(&mut child);
                }
            }
        });
}
