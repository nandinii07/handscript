//! HandScript desktop shell.
//!
//! This is a thin native window around the existing static frontend
//! (`../frontend`, loaded via `frontendDist` in tauri.conf.json) - see that
//! folder's own JS for the actual application. The one thing a plain static
//! site cannot do for itself is start its own backend, so that is the only
//! job this file has: launch the existing Flask backend (`app/main.py`,
//! unmodified) as a child process before the window opens, and stop it when
//! the app quits, so the user never has to open a terminal.
//!
//! This intentionally runs the backend from the checked-out repository
//! (`repo_root()`, resolved at compile time) rather than bundling a Python
//! interpreter and FontForge inside the .app - see repo_root()'s doc comment
//! for why. Rebuilding the app (`./desktop-build.sh`) after moving the repo,
//! or after `pip install -r app/requirements.txt` changes, picks this up
//! automatically; nothing here is cached beyond the build.

use std::io::ErrorKind;
use std::net::{SocketAddr, TcpStream};
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::time::Duration;

use tauri::Manager;

const BACKEND_PORT: u16 = 8000;

/// Owns the backend child process, if this instance of the app started one.
///
/// `we_started_it` matters: if a backend was already listening on
/// BACKEND_PORT when the app launched (the user ran it manually, or a
/// previous crashed run left one behind, or Docker's already up), this app
/// must not kill it on quit - it was not this app's to stop.
struct Backend {
    child: Option<Child>,
    we_started_it: bool,
}

impl Backend {
    fn stop(&mut self) {
        if !self.we_started_it {
            return;
        }
        if let Some(mut child) = self.child.take() {
            log::info!("stopping HandScript backend (pid {})", child.id());
            let _ = child.kill();
            let _ = child.wait();
        }
    }
}

struct BackendState(Mutex<Backend>);

/// The checked-out project's root directory - the parent of `src-tauri/`.
///
/// `CARGO_MANIFEST_DIR` is a compile-time constant (the directory containing
/// this crate's Cargo.toml), so this resolves to wherever the repo actually
/// lives on the machine this was built on - no bundled copy, no install step.
/// This is what "run the existing backend, don't rebuild it" means in
/// practice: `app/`, `handwrite/`, `.venv/` and every native tool already
/// set up for local development (see README.md "Local setup") are reused
/// as-is, exactly as the browser-based frontend already relied on them being
/// there. The tradeoff is that this binary is tied to this checkout's path;
/// moving the repo means rebuilding (`./desktop-build.sh`), not reinstalling.
fn repo_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .expect("src-tauri always has a parent directory")
        .to_path_buf()
}

fn home_dir() -> PathBuf {
    PathBuf::from(std::env::var("HOME").unwrap_or_else(|_| "/tmp".to_string()))
}

/// Where this app keeps the things a normal macOS app keeps outside its own
/// bundle: job data survives an app update, logs are somewhere the user (or
/// a support request) can actually find them.
fn app_support_dir() -> PathBuf {
    home_dir().join("Library/Application Support/HandScript")
}

fn log_dir() -> PathBuf {
    home_dir().join("Library/Logs/HandScript")
}

fn backend_already_listening() -> bool {
    let addr: SocketAddr = ([127, 0, 0, 1], BACKEND_PORT).into();
    TcpStream::connect_timeout(&addr, Duration::from_millis(300)).is_ok()
}

/// Launch `app.main:app` under gunicorn, exactly the way Dockerfile's own
/// CMD does (one worker, eight gthread threads - see the Dockerfile's
/// comment on why: job metadata lives in SQLite and font builds already run
/// on their own thread pool, so a single process is the right shape here
/// too, not a resource cut).
fn spawn_backend() -> std::io::Result<Child> {
    let root = repo_root();
    let venv_python = root.join(".venv/bin/python3");
    let python: PathBuf = if venv_python.exists() {
        venv_python
    } else {
        // Fallback for a checkout with no venv yet - same interpreter
        // resolution a user typing `python3` at a terminal would get.
        PathBuf::from("python3")
    };

    let jobs_dir = app_support_dir().join("jobs");
    std::fs::create_dir_all(&jobs_dir)?;
    let logs_dir = log_dir();
    std::fs::create_dir_all(&logs_dir)?;
    let log_file = std::fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(logs_dir.join("backend.log"))?;
    let stdout = Stdio::from(log_file.try_clone()?);
    let stderr = Stdio::from(log_file);

    // A Mac app launched from Finder (as opposed to a terminal) does not
    // inherit a login shell's PATH, so Homebrew's own bin directories - where
    // potrace and fontforge actually live - are not on it by default. This
    // is the one thing that would otherwise make `GET /health` correctly,
    // honestly report build_tools_available: false from inside the bundled
    // app while the exact same backend works fine started from a terminal.
    let inherited_path = std::env::var("PATH").unwrap_or_default();
    let path = format!("/opt/homebrew/bin:/usr/local/bin:{inherited_path}");

    Command::new(python)
        .args([
            "-m",
            "gunicorn",
            "--workers",
            "1",
            "--threads",
            "8",
            "--worker-class",
            "gthread",
            "--bind",
            &format!("127.0.0.1:{BACKEND_PORT}"),
            "--timeout",
            "180",
            "app.main:app",
        ])
        .current_dir(&root)
        .env("PATH", path)
        .env("HANDWRITE_JOB_ROOT", &jobs_dir)
        .env("PYTHONUNBUFFERED", "1")
        .stdin(Stdio::null())
        .stdout(stdout)
        .stderr(stderr)
        .spawn()
}

fn start_backend_if_needed(state: &BackendState) {
    let mut backend = state.0.lock().unwrap();

    if backend_already_listening() {
        // Something (a previous run, Docker, a terminal) is already serving
        // this port. Use it rather than failing to bind a second process on
        // the same port - and since this app did not start it, this app
        // must not stop it on quit either.
        log::info!(
            "a backend is already listening on 127.0.0.1:{BACKEND_PORT}; not starting a second one"
        );
        backend.we_started_it = false;
        return;
    }

    match spawn_backend() {
        Ok(child) => {
            log::info!("started HandScript backend (pid {})", child.id());
            backend.child = Some(child);
            backend.we_started_it = true;
        }
        Err(error) => {
            // Not fatal to the app itself: the window still opens and shows
            // the existing "We could not reach the server" state the
            // frontend already handles - this just means that state is the
            // one the user will see. Logged so it is diagnosable rather than
            // silent.
            let hint = if error.kind() == ErrorKind::NotFound {
                " (no Python interpreter found - see README.md \"Local setup\")"
            } else {
                ""
            };
            log::error!("failed to start the HandScript backend: {error}{hint}");
        }
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_fs::init())
        .manage(BackendState(Mutex::new(Backend {
            child: None,
            we_started_it: false,
        })))
        .setup(|app| {
            if cfg!(debug_assertions) {
                app.handle().plugin(
                    tauri_plugin_log::Builder::default()
                        .level(log::LevelFilter::Info)
                        .build(),
                )?;
            }

            start_backend_if_needed(app.state::<BackendState>().inner());
            Ok(())
        })
        .on_window_event(|window, event| {
            // This app has exactly one window (the frontend navigates
            // between pages within it, the way a browser tab does - see
            // frontend/js/*.js). Closing it is "done with the app" from the
            // user's point of view, so treat it as a full quit: stop the
            // backend, then actually exit instead of leaving a windowless
            // process (and its backend) running invisibly in the background.
            if let tauri::WindowEvent::CloseRequested { .. } = event {
                window
                    .state::<BackendState>()
                    .0
                    .lock()
                    .unwrap()
                    .stop();
                window.app_handle().exit(0);
            }
        })
        .build(tauri::generate_context!())
        .expect("error while building the HandScript application");

    app.run(|app_handle, event| {
        // Belt-and-braces alongside the window-close handler above: covers
        // Cmd+Q / Quit from the Dock, and any other path to RunEvent::Exit
        // that does not go through CloseRequested first. Backend::stop() is
        // idempotent (Option::take()), so running both costs nothing.
        if let tauri::RunEvent::ExitRequested { .. } | tauri::RunEvent::Exit = event {
            app_handle
                .state::<BackendState>()
                .0
                .lock()
                .unwrap()
                .stop();
        }
    });
}
