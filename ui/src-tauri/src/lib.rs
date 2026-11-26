//! Rosie's desktop shell: one small, transparent, always-on-top window (the orb).
//!
//! The window itself is described in `tauri.conf.json`; here we place it in the
//! bottom-right corner of the screen it opens on, above the taskbar, and start
//! Rosie's Python core next to it (see `core.rs`).

pub mod core;

use std::process::Child;
use std::sync::Mutex;

use tauri::{Manager, PhysicalPosition, PhysicalSize, RunEvent};

/// The core process the orb started (None if it was already running).
struct CoreProcess(Mutex<Option<Child>>);

/// Gap between the orb window and the screen edges, in logical pixels.
pub const MARGIN: f64 = 24.0;
/// Room left for the Windows taskbar at the bottom, in logical pixels.
pub const TASKBAR: f64 = 48.0;

/// Top-left corner that puts a `window` in the bottom-right of a `screen`.
///
/// Everything is in physical pixels; `scale` is the screen's DPI factor (1.5 on a
/// 150% laptop display), so the margins look the same on every screen.
pub fn bottom_right(
    screen_pos: PhysicalPosition<i32>,
    screen: PhysicalSize<u32>,
    window: PhysicalSize<u32>,
    scale: f64,
) -> PhysicalPosition<i32> {
    let right = (MARGIN * scale).round() as i32;
    let bottom = ((MARGIN + TASKBAR) * scale).round() as i32;
    let x = screen_pos.x + screen.width as i32 - window.width as i32 - right;
    let y = screen_pos.y + screen.height as i32 - window.height as i32 - bottom;
    PhysicalPosition::new(x.max(screen_pos.x), y.max(screen_pos.y))
}

fn place_orb(app: &tauri::App) -> tauri::Result<()> {
    let Some(window) = app.get_webview_window("orb") else {
        return Ok(());
    };
    if let Some(monitor) = window.current_monitor()? {
        let spot = bottom_right(
            *monitor.position(),
            *monitor.size(),
            window.outer_size()?,
            monitor.scale_factor(),
        );
        window.set_position(spot)?;
    }
    Ok(())
}

pub fn run() {
    let app = tauri::Builder::default()
        .setup(|app| {
            place_orb(app)?;
            let child = core::ensure_core().unwrap_or_else(|err| {
                // The orb still opens and keeps retrying; it shows "core offline".
                eprintln!("could not start Rosie's core: {err}");
                None
            });
            app.manage(CoreProcess(Mutex::new(child)));
            Ok(())
        })
        .on_window_event(|window, event| {
            // Closing the Command Deck only hides it; the orb opens it again.
            if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                if window.label() == "deck" {
                    api.prevent_close();
                    let _ = window.hide();
                }
            }
        })
        .build(tauri::generate_context!())
        .expect("Rosie's window failed to start");
    app.run(|handle, event| {
        if let RunEvent::Exit = event {
            // Only stop the core if the orb started it.
            if let Some(mut child) = handle.state::<CoreProcess>().0.lock().unwrap().take() {
                let _ = child.kill();
                let _ = child.wait();
            }
        }
    });
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn orb_sits_bottom_right_above_the_taskbar() {
        let spot = bottom_right(
            PhysicalPosition::new(0, 0),
            PhysicalSize::new(1920, 1080),
            PhysicalSize::new(200, 200),
            1.0,
        );
        assert_eq!(spot, PhysicalPosition::new(1920 - 200 - 24, 1080 - 200 - 72));
    }

    #[test]
    fn margins_scale_with_dpi() {
        let spot = bottom_right(
            PhysicalPosition::new(0, 0),
            PhysicalSize::new(2880, 1620),
            PhysicalSize::new(300, 300),
            1.5,
        );
        assert_eq!(spot, PhysicalPosition::new(2880 - 300 - 36, 1620 - 300 - 108));
    }

    #[test]
    fn second_monitor_offsets_are_kept() {
        let spot = bottom_right(
            PhysicalPosition::new(1920, 0),
            PhysicalSize::new(1280, 720),
            PhysicalSize::new(200, 200),
            1.0,
        );
        assert_eq!(spot.x, 1920 + 1280 - 200 - 24);
    }

    #[test]
    fn never_off_screen_on_a_tiny_display() {
        let spot = bottom_right(
            PhysicalPosition::new(0, 0),
            PhysicalSize::new(100, 100),
            PhysicalSize::new(200, 200),
            1.0,
        );
        assert_eq!(spot, PhysicalPosition::new(0, 0));
    }
}
