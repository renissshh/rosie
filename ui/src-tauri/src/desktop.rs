//! Living on the desktop: tray menu, Ctrl+Space, start at login.
//!
//! - Tray: Open Command Deck / Start at login (tick) / Restart Rosie's core / Quit.
//! - Ctrl+Space anywhere in Windows sends "hotkey" to the orb, which acts like a click.
//! - Start at login: Tauri's autostart plugin writes a per-user entry
//!   (HKCU\...\Run on Windows, so no admin rights). Release builds turn it on once,
//!   on the first run; after that the tray tick is yours to change.

use std::path::Path;

use tauri::menu::{CheckMenuItem, Menu, MenuItem, PredefinedMenuItem};
use tauri::tray::TrayIconBuilder;
use tauri::{AppHandle, Emitter, Manager};
use tauri_plugin_autostart::ManagerExt;
use tauri_plugin_global_shortcut::{Code, Modifiers, Shortcut};

pub const MENU_DECK: &str = "deck";
pub const MENU_AUTOSTART: &str = "autostart";
pub const MENU_RESTART: &str = "restart-core";
pub const MENU_QUIT: &str = "quit";
pub const AUTOSTART_MARKER: &str = "autostart-set";

#[derive(Debug, PartialEq, Eq)]
pub enum TrayAction {
    OpenDeck,
    ToggleAutostart,
    RestartCore,
    Quit,
}

pub fn tray_action(id: &str) -> Option<TrayAction> {
    match id {
        MENU_DECK => Some(TrayAction::OpenDeck),
        MENU_AUTOSTART => Some(TrayAction::ToggleAutostart),
        MENU_RESTART => Some(TrayAction::RestartCore),
        MENU_QUIT => Some(TrayAction::Quit),
        _ => None,
    }
}

pub fn hotkey() -> Shortcut {
    Shortcut::new(Some(Modifiers::CONTROL), Code::Space)
}

/// First run = the marker file isn't there yet. Creates it, so this is true once.
pub fn first_run(config_dir: &Path) -> bool {
    let marker = config_dir.join(AUTOSTART_MARKER);
    if marker.exists() {
        return false;
    }
    let _ = std::fs::create_dir_all(config_dir);
    std::fs::write(&marker, "Rosie enabled start-at-login once; the tray tick decides now.\n").is_ok()
}

pub fn show_deck(app: &AppHandle) {
    if let Some(deck) = app.get_webview_window("deck") {
        let _ = deck.show();
        let _ = deck.unminimize();
        let _ = deck.set_focus();
    }
}

pub fn press_hotkey(app: &AppHandle) {
    let _ = app.emit_to("orb", "hotkey", ());
}

pub fn enable_autostart_on_first_run(app: &AppHandle) {
    if cfg!(debug_assertions) {
        return; // never register a dev build at login
    }
    if let Ok(dir) = app.path().app_config_dir() {
        if first_run(&dir) {
            let _ = app.autolaunch().enable();
        }
    }
}

pub fn build_tray(app: &AppHandle, restart_core: fn(&AppHandle)) -> tauri::Result<()> {
    let at_login = app.autolaunch().is_enabled().unwrap_or(false);
    let deck = MenuItem::with_id(app, MENU_DECK, "Open Command Deck", true, Some("Ctrl+Space"))?;
    let autostart = CheckMenuItem::with_id(app, MENU_AUTOSTART, "Start at login", true, at_login, None::<&str>)?;
    let restart = MenuItem::with_id(app, MENU_RESTART, "Restart Rosie's core", true, None::<&str>)?;
    let quit = MenuItem::with_id(app, MENU_QUIT, "Quit Rosie", true, None::<&str>)?;
    let separator = PredefinedMenuItem::separator(app)?;
    let menu = Menu::with_items(app, &[&deck, &autostart, &restart, &separator, &quit])?;
    let toggle = autostart.clone();

    let mut tray = TrayIconBuilder::with_id("rosie")
        .tooltip("Rosie")
        .menu(&menu)
        .on_menu_event(move |app, event| match tray_action(event.id().as_ref()) {
            Some(TrayAction::OpenDeck) => show_deck(app),
            Some(TrayAction::ToggleAutostart) => {
                let launcher = app.autolaunch();
                let on = launcher.is_enabled().unwrap_or(false);
                let _ = if on { launcher.disable() } else { launcher.enable() };
                let _ = toggle.set_checked(launcher.is_enabled().unwrap_or(!on));
            }
            Some(TrayAction::RestartCore) => restart_core(app),
            Some(TrayAction::Quit) => app.exit(0),
            None => {}
        });
    if let Some(icon) = app.default_window_icon() {
        tray = tray.icon(icon.clone());
    }
    tray.build(app)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn every_menu_id_has_an_action() {
        assert_eq!(tray_action(MENU_DECK), Some(TrayAction::OpenDeck));
        assert_eq!(tray_action(MENU_AUTOSTART), Some(TrayAction::ToggleAutostart));
        assert_eq!(tray_action(MENU_RESTART), Some(TrayAction::RestartCore));
        assert_eq!(tray_action(MENU_QUIT), Some(TrayAction::Quit));
        assert_eq!(tray_action("something-else"), None);
    }

    #[test]
    fn hotkey_is_ctrl_space() {
        let key = hotkey();
        assert!(key.matches(Modifiers::CONTROL, Code::Space));
        assert!(!key.matches(Modifiers::ALT, Code::Space));
    }

    #[test]
    fn first_run_is_true_exactly_once() {
        let dir = std::env::temp_dir().join(format!("rosie-test-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        assert!(first_run(&dir));
        assert!(!first_run(&dir));
        assert!(dir.join(AUTOSTART_MARKER).is_file());
        let _ = std::fs::remove_dir_all(&dir);
    }
}
