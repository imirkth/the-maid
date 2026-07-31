// ponytail: JSON file instead of tauri-plugin-store. serde_json already a dep, data isn't sensitive.
// Add tauri-plugin-store when encryption is actually needed.

use serde::{Deserialize, Serialize};
use std::fs;
use std::path::PathBuf;

#[derive(Serialize, Deserialize, Debug, Clone, Default)]
pub struct Settings {
    pub sandbox_folders: Vec<String>,
    pub first_run: bool,
    pub buckets: Vec<BucketEntry>,
    pub features: FeatureFlags,
    pub setup_complete: bool,
    pub face_cluster: FaceClusterSettings,
}

#[derive(Serialize, Deserialize, Debug, Clone, Default)]
pub struct FeatureFlags {
    pub pdf_ocr: bool,
    pub face_clustering: bool,
    pub general_files: bool,
}

#[derive(Serialize, Deserialize, Debug, Clone, Default)]
pub struct FaceClusterSettings {
    pub eps: f64,
    pub min_samples: usize,
}

impl FaceClusterSettings {
    pub fn new() -> Self {
        FaceClusterSettings {
            eps: 0.4,
            min_samples: 2,
        }
    }
}

#[derive(Serialize, Deserialize, Debug, Clone, Default)]
pub struct BucketEntry {
    pub id: String,
    pub name: String,
    pub path: String,
}

impl Default for Settings {
    fn default() -> Self {
        Self::new()
    }
}

impl Settings {
    /// Create settings with defaults for a first-run user.
    pub fn new() -> Self {
        Settings {
            sandbox_folders: default_folders(),
            first_run: true,
            buckets: vec![],
            features: FeatureFlags::default(),
            setup_complete: false,
            face_cluster: FaceClusterSettings::new(),
        }
    }

    /// Load settings from ~/.the-maid/settings.json, or return defaults.
    pub fn load() -> Result<Self, String> {
        let path = settings_path()?;
        if !path.exists() {
            return Ok(Self::new());
        }
        let data =
            fs::read_to_string(&path).map_err(|e| format!("Failed to read settings: {}", e))?;
        serde_json::from_str(&data).map_err(|e| format!("Failed to parse settings: {}", e))
    }

    /// Save settings atomically to avoid corrupting the file on crash.
    pub fn save(&self) -> Result<(), String> {
        let path = settings_path()?;
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent)
                .map_err(|e| format!("Failed to create settings dir: {}", e))?;
        }
        let data = serde_json::to_string_pretty(self)
            .map_err(|e| format!("Failed to serialize settings: {}", e))?;
        let tmp = path.with_extension("json.tmp");
        fs::write(&tmp, data).map_err(|e| format!("Failed to write settings temp: {}", e))?;
        fs::rename(&tmp, &path)
            .map_err(|e| format!("Failed to commit settings: {}", e))?;
        // ponytail: restrict settings file to owner on Unix
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            let perms = std::fs::Permissions::from_mode(0o600);
            let _ = fs::set_permissions(&path, perms);
        }
        Ok(())
    }

    /// Mark first run complete.
    pub fn complete_first_run(&mut self) {
        self.first_run = false;
    }

    /// Mark setup wizard complete — enables scanning.
    pub fn complete_setup(&mut self) {
        self.setup_complete = true;
        self.first_run = false;
    }

    /// Set feature flags from setup wizard.
    pub fn set_features(&mut self, pdf_ocr: bool, face_clustering: bool, general_files: bool) {
        self.features = FeatureFlags {
            pdf_ocr,
            face_clustering,
            general_files,
        };
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

    /// Add a bucket. IDs are never reused so removing and re-adding cannot collide.
    pub fn add_bucket(&mut self, name: &str, path: &str) {
        let next_id = self
            .buckets
            .iter()
            .filter_map(|b| b.id.parse::<usize>().ok())
            .max()
            .unwrap_or(0)
            + 1;
        self.buckets.push(BucketEntry {
            id: next_id.to_string(),
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

    use std::sync::atomic::{AtomicU64, Ordering};

    static TEST_COUNTER: AtomicU64 = AtomicU64::new(0);

    fn setup_temp_settings() -> PathBuf {
        let count = TEST_COUNTER.fetch_add(1, Ordering::SeqCst);
        let tmp =
            std::env::temp_dir().join(format!("the-maid-test-{}-{}", std::process::id(), count));
        // Clean up any leftover from previous run
        std::fs::remove_dir_all(&tmp).ok();
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
    fn test_default_impl_matches_new() {
        let from_default = Settings::default();
        let from_new = Settings::new();
        assert_eq!(from_default.sandbox_folders, from_new.sandbox_folders);
        assert_eq!(from_default.first_run, from_new.first_run);
        assert_eq!(from_default.buckets, from_new.buckets);
        assert_eq!(from_default.features.pdf_ocr, from_new.features.pdf_ocr);
    }

    #[test]
    fn test_add_bucket_no_id_reuse() {
        let mut settings = Settings::default();
        settings.add_bucket("A", "~/A");
        settings.add_bucket("B", "~/B");
        settings.remove_bucket("1");
        settings.add_bucket("C", "~/C");
        assert_eq!(settings.buckets.len(), 2);
        let ids: Vec<&str> = settings.buckets.iter().map(|b| b.id.as_str()).collect();
        assert!(ids.contains(&"2"));
        assert!(ids.contains(&"3"));
    }

    #[test]
    fn test_save_atomic_leaves_no_temp_file() {
        let tmp = setup_temp_settings();
        let mut settings = Settings::load().unwrap();
        settings.complete_first_run();
        settings.save().unwrap();

        let settings_file = settings_path().unwrap();
        let temp_file = settings_file.with_extension("json.tmp");
        assert!(settings_file.exists());
        assert!(!temp_file.exists());
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
        let mut settings = Settings::new();
        assert!(settings.first_run);
        settings.complete_first_run();
        assert!(!settings.first_run);
    }

    #[test]
    fn test_setup_complete_flag() {
        let mut settings = Settings::new();
        assert!(!settings.setup_complete);
        assert!(settings.first_run);
        settings.complete_setup();
        assert!(settings.setup_complete);
        assert!(!settings.first_run);
    }

    #[test]
    fn test_face_cluster_defaults() {
        let settings = Settings::new();
        assert!((settings.face_cluster.eps - 0.4).abs() < f64::EPSILON);
        assert_eq!(settings.face_cluster.min_samples, 2);
    }

    #[test]
    fn test_face_cluster_roundtrip() {
        let tmp = setup_temp_settings();
        let mut settings = Settings::load().unwrap();
        settings.face_cluster.eps = 0.25;
        settings.face_cluster.min_samples = 5;
        settings.save().unwrap();

        let loaded = Settings::load().unwrap();
        assert!((loaded.face_cluster.eps - 0.25).abs() < f64::EPSILON);
        assert_eq!(loaded.face_cluster.min_samples, 5);
        std::fs::remove_dir_all(&tmp).ok();
    }

    #[test]
    fn test_set_features() {
        let mut settings = Settings::new();
        assert!(!settings.features.pdf_ocr);
        assert!(!settings.features.face_clustering);
        assert!(!settings.features.general_files);
        settings.set_features(true, false, true);
        assert!(settings.features.pdf_ocr);
        assert!(!settings.features.face_clustering);
        assert!(settings.features.general_files);
    }

    #[test]
    fn test_settings_file_path() {
        let path = settings_path().unwrap();
        assert!(path.to_string_lossy().contains(".the-maid"));
        assert!(path.to_string_lossy().contains("settings.json"));
    }
}
