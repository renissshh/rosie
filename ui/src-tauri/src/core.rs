//! Starting Rosie's Python core next to the orb (a "sidecar" process).
//!
//! At startup the orb checks whether the core already answers on 127.0.0.1:8765
//! (you may have started `rosie serve` yourself). If not, it starts one and stops it
//! again when the orb quits. The command is `rosie serve`, or the program named in the
//! `ROSIE_CORE` environment variable, e.g. `D:\Rosie\.venv\Scripts\rosie.exe`.

use std::net::{SocketAddr, TcpStream};
use std::process::{Child, Command, Stdio};
use std::time::Duration;

pub const CORE_ADDR: &str = "127.0.0.1:8765";

/// Is something listening on the core's address?
pub fn core_is_up(addr: &str, timeout: Duration) -> bool {
    match addr.parse::<SocketAddr>() {
        Ok(addr) => TcpStream::connect_timeout(&addr, timeout).is_ok(),
        Err(_) => false,
    }
}

/// The program to run: `ROSIE_CORE` if set (and not blank), else `rosie` on PATH.
pub fn core_program(env_value: Option<String>) -> String {
    env_value
        .map(|value| value.trim().trim_matches('"').to_string())
        .filter(|value| !value.is_empty())
        .unwrap_or_else(|| "rosie".to_string())
}

pub fn core_command(program: &str) -> Command {
    let mut command = Command::new(program);
    command
        .arg("serve")
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null());
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x0800_0000; // no black console window at login
        command.creation_flags(CREATE_NO_WINDOW);
    }
    command
}

/// Start the core unless one is already running. `Ok(None)` means "already up".
pub fn ensure_core() -> std::io::Result<Option<Child>> {
    if core_is_up(CORE_ADDR, Duration::from_millis(300)) {
        return Ok(None);
    }
    let program = core_program(std::env::var("ROSIE_CORE").ok());
    core_command(&program).spawn().map(Some)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::net::TcpListener;

    #[test]
    fn sees_a_listening_core() {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let addr = listener.local_addr().unwrap().to_string();
        assert!(core_is_up(&addr, Duration::from_millis(300)));
    }

    #[test]
    fn nothing_listening_means_down() {
        let port = TcpListener::bind("127.0.0.1:0")
            .unwrap()
            .local_addr()
            .unwrap()
            .port();
        // the listener is dropped here, so the port is free again
        assert!(!core_is_up(
            &format!("127.0.0.1:{port}"),
            Duration::from_millis(300)
        ));
        assert!(!core_is_up("not an address", Duration::from_millis(300)));
    }

    #[test]
    fn program_defaults_to_rosie_on_path() {
        assert_eq!(core_program(None), "rosie");
        assert_eq!(core_program(Some("   ".into())), "rosie");
    }

    #[test]
    fn program_from_env_keeps_spaces_and_drops_quotes() {
        let path = r#""C:\Program Files\Rosie\rosie.exe""#;
        assert_eq!(
            core_program(Some(path.into())),
            r"C:\Program Files\Rosie\rosie.exe"
        );
    }

    #[test]
    fn command_runs_serve() {
        let command = core_command("rosie");
        let args: Vec<_> = command.get_args().collect();
        assert_eq!(args, ["serve"]);
    }
}

/// When to restart a core that died: at most `max` restarts in any `window`, so a core
/// that crashes on start (bad config, missing Python) isn't restarted forever. The orb
/// then stays grey, and the tray's "Restart Rosie's core" tries again by hand.
pub struct RestartPolicy {
    pub max: usize,
    pub window: Duration,
    restarts: Vec<std::time::Instant>,
}

impl RestartPolicy {
    pub fn new(max: usize, window: Duration) -> Self {
        Self {
            max,
            window,
            restarts: Vec::new(),
        }
    }

    /// May we restart now? Records the restart if so.
    pub fn allow(&mut self, now: std::time::Instant) -> bool {
        let window = self.window;
        self.restarts.retain(|t| now.duration_since(*t) < window);
        if self.restarts.len() >= self.max {
            return false;
        }
        self.restarts.push(now);
        true
    }

    /// Forget past crashes (after a manual restart from the tray).
    pub fn reset(&mut self) {
        self.restarts.clear();
    }
}

#[cfg(test)]
mod restart_tests {
    use super::*;
    use std::time::Instant;

    #[test]
    fn allows_a_few_restarts_then_gives_up() {
        let mut policy = RestartPolicy::new(3, Duration::from_secs(600));
        let start = Instant::now();
        assert!(policy.allow(start));
        assert!(policy.allow(start + Duration::from_secs(10)));
        assert!(policy.allow(start + Duration::from_secs(20)));
        assert!(!policy.allow(start + Duration::from_secs(30)));
    }

    #[test]
    fn old_crashes_are_forgotten() {
        let mut policy = RestartPolicy::new(1, Duration::from_secs(600));
        let start = Instant::now();
        assert!(policy.allow(start));
        assert!(!policy.allow(start + Duration::from_secs(599)));
        assert!(policy.allow(start + Duration::from_secs(601)));
    }

    #[test]
    fn reset_allows_again() {
        let mut policy = RestartPolicy::new(1, Duration::from_secs(600));
        let start = Instant::now();
        policy.allow(start);
        policy.reset();
        assert!(policy.allow(start));
    }
}
