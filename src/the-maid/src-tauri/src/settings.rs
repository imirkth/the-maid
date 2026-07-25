// ponytail: JSON file instead of tauri-plugin-store. serde_json already a dep, data isn't sensitive.
// Add tauri-plugin-store when encryption is actually needed.

use serde::{Deserialize, Serialize};
use std::fs;
use std::path::{Path, PathBuf};

#[derive(Serialize, Deserialize, Debug, Clone, Default)]
pub struct Settings {
    pub sandbox_folders: Vec<String>,
    pub first_run: bool,
    pub buckets: Vec<BucketEntry>,
}

#[derive(Serialize, Deserialize, Debug, Clone, Default)]
pub struct BucketEntry {
    pub id: String,
    pub name: String,
    pub path: String,
}

impl Settings {
    /// Load settings from ~/.the-maid/settings.json, or return defaults.
    pub fn load() -> Result<Self, String> {
        let path = settings_path()?;
        if !path.exists() {
            return Ok(Settings {
                sandbox_folders: default_folders(),
                first_run: true,
                buckets: vec![],
            });
        }
        let data = fs::read_to_string(&path)
            .map_err(|e| format!("Failed to read settings: {}", e))?;
        serde_json::from_str(&data)
            .map_err(|e| format!("Failed to parse settings: {}", e))
    }

    /// Save settings to ~/.the-maid/settings.json.
    pub fn save(&self) -> Result<(), String> {
        let path = settings_path()?;
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent)
                .map_err(|e| format!("Failed to create settings dir: {}", e))?;
        }
        let data = serde_json::to_string_pretty(self)
            .map_err(|e| format!("Failed to serialize settings: {}", e))?;
        fs::write(&path, data)
            .map_err(|e| format!("Failed to write settings: {}", e))
    }

    /// Mark first run complete.
    pub fn complete_first_run(&mut self) {
        self.first_run = false;
    }

    /// Add a sandbox folder if not already present.
    pub fn add_folder(&mut self, folder: &str) {
        if !self.sandbox_folders.iter().any(|f| f == folder) {
            self.sandbox_folders.push(folder.to_string());
        }
    }

    /// Remove a sandbox folder.
    pub fn remove_folder(&mut self, folder: &str) {
        self.sandbox_folders.retain(|f| f != folder);
    }

    /// Add a bucket.
    pub fn add_bucket(&mut self, name: &str, path: &str) {
        let id = format!("{}", self.buckets.len() + 1);
        self.buckets.push(BucketEntry {
            id,
            name: name.to_string(),
            path: path.to_string(),
        });
    }

    /// Remove a bucket by id.
    pub fn remove_bucket(&mut self, id: &str) {
        self.buckets.retain(|b| b.id != id);
    }
}

fn settings_path() -> Result<PathBuf, String> {
    let home = std::env::var("HOME")
        .or_else(|_| std::env::var("USERPROFILE"))
        .map_err(|_| "Cannot determine home directory")?;
    Ok(PathBuf::from(home).join(".the-maid").join("settings.json"))
}

fn default_folders() -> Vec<String> {
    vec![
        "Desktop".to_string(),
        "Downloads".to_string(),
        "Documents".to_string(),
        "Pictures".to_string(),
    ]
}

#[cfg(test)]
mod tests {
    use super::*;

    fn setup_temp_settings() -> PathBuf {
        let tmp = std::env::temp_dir().join(format!(
            "the-maid-test-{}",
            std::process::id()
        ));
        std::fs::create_dir_all(&tmp).unwrap();
        // ponytail: override HOME for test isolation
        std::env::set_var("HOME", &tmp);
        tmp
    }

    #[test]
    fn test_default_settings() {
        let tmp = setup_temp_settings();
        // No settings file → defaults
        let settings = Settings::load().unwrap();
        assert!(settings.first_run);
        assert_eq!(settings.sandbox_folders.len(), 4);
        assert!(settings.sandbox_folders.contains(&"Desktop".to_string()));
        assert!(settings.buckets.is_empty());
        std::fs::remove_dir_all(&tmp).ok();
    }

    #[test]
    fn test_save_and_load() {
        let tmp = setup_temp_settings();
        let mut settings = Settings::load().unwrap();
        settings.add_folder("Videos");
        settings.add_bucket("Work", "~/Documents/Work");
        settings.complete_first_run();
        settings.save().unwrap();

        let loaded = Settings::load().unwrap();
        assert!(!loaded.first_run);
        assert!(loaded.sandbox_folders.contains(&"Videos".to_string()));
        assert_eq!(loaded.buckets.len(), 1);
        assert_eq!(loaded.buckets[0].name, "Work");
        std::fs::remove_dir_all(&tmp).ok();
    }

    #[test]
    fn test_add_remove_folder() {
        let mut settings = Settings::default();
        settings.add_folder("Desktop");
        settings.add_folder("Desktop"); // dup ignored
        assert_eq!(settings.sandbox_folders.len(), 1);
        settings.remove_folder("Desktop");
        assert!(settings.sandbox_folders.is_empty());
    }

    #[test]
    fn test_add_remove_bucket() {
        let mut settings = Settings::default();
        settings.add_bucket("Receipts", "~/Documents/Receipts");
        settings.add_bucket("Photos", "~/Pictures");
        assert_eq!(settings.buckets.len(), 2);
        settings.remove_bucket("1");
        assert_eq!(settings.buckets.len(), 1);
        assert_eq!(settings.buckets[0].name, "Photos");
    }

    #[test]
    fn test_first_run_flag() {
        let mut settings = Settings::default();
        assert!(settings.first_run);
        settings.complete_first_run();
        assert!(!settings.first_run);
    }

    #[test]
    fn test_settings_file_path() {
        let path = settings_path().unwrap();
        assert!(path.to_string_lossy().contains(".the-maid"));
        assert!(path.to_string_lossy().contains("settings.json"));
    }
}