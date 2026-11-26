// No console window behind the orb in release builds on Windows.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    rosie_ui_lib::run()
}
