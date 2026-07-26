//! The Maid — shared library crate
//! Re-exports modules for testing without Tauri runtime.

pub mod lightning;
pub mod settings;
pub mod sidecar;

pub use sidecar::{SidecarManager, SidecarState};
