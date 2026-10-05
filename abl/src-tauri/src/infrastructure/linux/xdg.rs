use std::{
    collections::BTreeMap,
    ffi::{OsStr, OsString},
    fs,
    io,
    os::unix::fs::{MetadataExt, PermissionsExt},
    path::{Path, PathBuf},
};

use crate::infrastructure::profile::{create_private_dir, ProfileStoragePaths};

const APP_DIR: &str = "p2pkanban";

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum XdgError {
    MissingHome,
    InvalidProfileName,
    PersistentPath(io::ErrorKind),
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum RuntimeStatus {
    Available(PathBuf),
    Missing,
    Unsafe,
    Unwritable,
}

impl RuntimeStatus {
    pub fn activation_available(&self) -> bool {
        matches!(self, Self::Available(_))
    }
}

#[derive(Debug, Clone)]
pub struct XdgEnvironment {
    values: BTreeMap<String, OsString>,
}

impl XdgEnvironment {
    pub fn current() -> Self {
        let values = std::env::vars_os()
            .filter_map(|(key, value)| key.into_string().ok().map(|key| (key, value)))
            .collect();
        Self { values }
    }

    #[cfg(test)]
    pub fn from_pairs(values: impl IntoIterator<Item = (&'static str, PathBuf)>) -> Self {
        Self {
            values: values
                .into_iter()
                .map(|(key, value)| (key.to_owned(), value.into_os_string()))
                .collect(),
        }
    }

    fn value(&self, key: &str) -> Option<&OsStr> {
        self.values.get(key).map(OsString::as_os_str)
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DesktopPaths {
    pub data_root: PathBuf,
    pub config_root: PathBuf,
    pub state_root: PathBuf,
    pub cache_root: PathBuf,
    pub profile: ProfileStoragePaths,
    pub settings: PathBuf,
    pub release_channel: PathBuf,
    pub logs: PathBuf,
    pub crash: PathBuf,
    pub last_run: PathBuf,
    pub webview_cache: PathBuf,
    pub downloads: PathBuf,
    runtime_base: Option<PathBuf>,
    profile_name: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PreparedDesktopPaths {
    pub paths: DesktopPaths,
    pub runtime_status: RuntimeStatus,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ProfileDiagnostics {
    pub data_root: PathBuf,
    pub config_root: PathBuf,
    pub state_root: PathBuf,
    pub cache_root: PathBuf,
    pub profile_database: PathBuf,
    pub runtime_activation_available: bool,
}

fn absolute_env(env: &XdgEnvironment, key: &str) -> Option<PathBuf> {
    let path = PathBuf::from(env.value(key)?);
    path.is_absolute().then_some(path)
}

fn home(env: &XdgEnvironment) -> Result<PathBuf, XdgError> {
    absolute_env(env, "HOME").ok_or(XdgError::MissingHome)
}

fn xdg_or_default(
    env: &XdgEnvironment,
    key: &str,
    default_suffix: &[&str],
) -> Result<PathBuf, XdgError> {
    if let Some(path) = absolute_env(env, key) {
        return Ok(path);
    }
    let mut path = home(env)?;
    for segment in default_suffix {
        path.push(segment);
    }
    Ok(path)
}

fn valid_profile_name(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 64
        && value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'_'))
}

impl DesktopPaths {
    pub fn resolve(env: &XdgEnvironment, profile_name: &str) -> Result<Self, XdgError> {
        if !valid_profile_name(profile_name) {
            return Err(XdgError::InvalidProfileName);
        }
        let data_root = xdg_or_default(env, "XDG_DATA_HOME", &[".local", "share"])?.join(APP_DIR);
        let config_root = xdg_or_default(env, "XDG_CONFIG_HOME", &[".config"])?.join(APP_DIR);
        let state_root = xdg_or_default(env, "XDG_STATE_HOME", &[".local", "state"])?.join(APP_DIR);
        let cache_root = xdg_or_default(env, "XDG_CACHE_HOME", &[".cache"])?.join(APP_DIR);
        let runtime_base = absolute_env(env, "XDG_RUNTIME_DIR");
        let profile_root = data_root.join("profiles").join(profile_name);
        Ok(Self {
            profile: ProfileStoragePaths::new(profile_root),
            settings: config_root.join("settings.json"),
            release_channel: config_root.join("release-channel.json"),
            logs: state_root.join("logs"),
            crash: state_root.join("crash"),
            last_run: state_root.join("last-run.json"),
            webview_cache: cache_root.join("webview-cache"),
            downloads: cache_root.join("downloads"),
            data_root,
            config_root,
            state_root,
            cache_root,
            runtime_base,
            profile_name: profile_name.to_owned(),
        })
    }

    pub fn prepare(self) -> Result<PreparedDesktopPaths, XdgError> {
        for path in [
            &self.data_root,
            &self.config_root,
            &self.state_root,
            &self.cache_root,
            &self.logs,
            &self.crash,
            &self.webview_cache,
            &self.downloads,
        ] {
            create_private_dir(path).map_err(|err| XdgError::PersistentPath(err.kind()))?;
        }
        self.profile
            .prepare()
            .map_err(|err| XdgError::PersistentPath(err.kind()))?;
        let runtime_status = prepare_runtime(self.runtime_base.as_deref(), &self.profile_name);
        Ok(PreparedDesktopPaths { paths: self, runtime_status })
    }
}

impl PreparedDesktopPaths {
    pub fn activation_socket(&self) -> Option<PathBuf> {
        match &self.runtime_status {
            RuntimeStatus::Available(root) => Some(root.join("instances").join(format!("{}.sock", self.paths.profile_name))),
            _ => None,
        }
    }

    pub fn diagnostics(&self) -> ProfileDiagnostics {
        ProfileDiagnostics {
            data_root: self.paths.data_root.clone(),
            config_root: self.paths.config_root.clone(),
            state_root: self.paths.state_root.clone(),
            cache_root: self.paths.cache_root.clone(),
            profile_database: self.paths.profile.database().to_path_buf(),
            runtime_activation_available: self.runtime_status.activation_available(),
        }
    }
}

fn prepare_runtime(base: Option<&Path>, _profile_name: &str) -> RuntimeStatus {
    let Some(base) = base else {
        return RuntimeStatus::Missing;
    };
    let metadata = match fs::symlink_metadata(base) {
        Ok(metadata) => metadata,
        Err(_) => return RuntimeStatus::Missing,
    };
    if metadata.file_type().is_symlink()
        || !metadata.is_dir()
        || metadata.uid() != unsafe { libc::geteuid() }
        || (metadata.permissions().mode() & 0o077) != 0
    {
        return RuntimeStatus::Unsafe;
    }
    let app_root = base.join(APP_DIR);
    let instances = app_root.join("instances");
    if create_private_dir(&app_root).and_then(|_| create_private_dir(&instances)).is_err() {
        return RuntimeStatus::Unwritable;
    }
    RuntimeStatus::Available(app_root)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::{
        os::unix::fs::PermissionsExt,
        sync::atomic::{AtomicU64, Ordering},
    };

    static NEXT: AtomicU64 = AtomicU64::new(1);

    fn temp_root(name: &str) -> PathBuf {
        let n = NEXT.fetch_add(1, Ordering::Relaxed);
        std::env::temp_dir().join(format!("p2pkanban-a06-xdg-{name}-{}-{n}", std::process::id()))
    }

    #[test]
    fn explicit_xdg_paths_match_baseline_layout() {
        let root = temp_root("explicit");
        let runtime = root.join("runtime");
        fs::create_dir_all(&runtime).unwrap();
        fs::set_permissions(&runtime, fs::Permissions::from_mode(0o700)).unwrap();
        let env = XdgEnvironment::from_pairs([
            ("HOME", root.join("home")),
            ("XDG_DATA_HOME", root.join("data")),
            ("XDG_CONFIG_HOME", root.join("config")),
            ("XDG_STATE_HOME", root.join("state")),
            ("XDG_CACHE_HOME", root.join("cache")),
            ("XDG_RUNTIME_DIR", runtime.clone()),
        ]);
        let prepared = DesktopPaths::resolve(&env, "default").unwrap().prepare().unwrap();
        assert_eq!(prepared.paths.profile.database(), root.join("data/p2pkanban/profiles/default/profile.db"));
        assert_eq!(prepared.paths.profile.backups(), root.join("data/p2pkanban/profiles/default/backups"));
        assert_eq!(prepared.paths.profile.migration_journal(), root.join("data/p2pkanban/profiles/default/migration-journal.json"));
        assert_eq!(prepared.paths.settings, root.join("config/p2pkanban/settings.json"));
        assert_eq!(prepared.paths.logs, root.join("state/p2pkanban/logs"));
        assert_eq!(prepared.paths.webview_cache, root.join("cache/p2pkanban/webview-cache"));
        assert!(prepared.activation_socket().unwrap().starts_with(runtime.join("p2pkanban/instances")));
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn xdg_defaults_use_home_without_hard_coding_a_user() {
        let root = temp_root("defaults");
        let env = XdgEnvironment::from_pairs([("HOME", root.clone())]);
        let prepared = DesktopPaths::resolve(&env, "default").unwrap().prepare().unwrap();
        assert_eq!(prepared.paths.data_root, root.join(".local/share/p2pkanban"));
        assert_eq!(prepared.paths.config_root, root.join(".config/p2pkanban"));
        assert_eq!(prepared.paths.state_root, root.join(".local/state/p2pkanban"));
        assert_eq!(prepared.paths.cache_root, root.join(".cache/p2pkanban"));
        assert_eq!(prepared.runtime_status, RuntimeStatus::Missing);
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn relative_xdg_values_are_ignored() {
        let root = temp_root("relative");
        let mut env = XdgEnvironment::from_pairs([("HOME", root.clone())]);
        env.values.insert("XDG_DATA_HOME".into(), OsString::from("relative-data"));
        let prepared = DesktopPaths::resolve(&env, "default").unwrap().prepare().unwrap();
        assert_eq!(prepared.paths.data_root, root.join(".local/share/p2pkanban"));
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn missing_runtime_dir_degrades_without_breaking_profile_paths() {
        let root = temp_root("no-runtime");
        let env = XdgEnvironment::from_pairs([("HOME", root.clone())]);
        let prepared = DesktopPaths::resolve(&env, "default").unwrap().prepare().unwrap();
        assert_eq!(prepared.runtime_status, RuntimeStatus::Missing);
        assert!(prepared.activation_socket().is_none());
        assert!(prepared.paths.profile.root().is_dir());
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn unsafe_runtime_dir_is_not_used_for_ipc() {
        let root = temp_root("unsafe-runtime");
        let runtime = root.join("runtime");
        fs::create_dir_all(&runtime).unwrap();
        fs::set_permissions(&runtime, fs::Permissions::from_mode(0o755)).unwrap();
        let env = XdgEnvironment::from_pairs([
            ("HOME", root.join("home")),
            ("XDG_RUNTIME_DIR", runtime),
        ]);
        let prepared = DesktopPaths::resolve(&env, "default").unwrap().prepare().unwrap();
        assert_eq!(prepared.runtime_status, RuntimeStatus::Unsafe);
        assert!(prepared.activation_socket().is_none());
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn invalid_profile_name_cannot_escape_profile_root() {
        let root = temp_root("traversal");
        let env = XdgEnvironment::from_pairs([("HOME", root)]);
        assert_eq!(DesktopPaths::resolve(&env, "../escape").unwrap_err(), XdgError::InvalidProfileName);
    }

    #[test]
    fn unwritable_persistent_root_fails_closed_for_non_root_user() {
        if unsafe { libc::geteuid() } == 0 {
            return;
        }
        let root = temp_root("readonly");
        let parent = root.join("readonly-parent");
        fs::create_dir_all(&parent).unwrap();
        fs::set_permissions(&parent, fs::Permissions::from_mode(0o500)).unwrap();
        let env = XdgEnvironment::from_pairs([
            ("HOME", root.join("home")),
            ("XDG_DATA_HOME", parent.join("data")),
            ("XDG_CONFIG_HOME", root.join("config")),
            ("XDG_STATE_HOME", root.join("state")),
            ("XDG_CACHE_HOME", root.join("cache")),
        ]);
        let err = DesktopPaths::resolve(&env, "default").unwrap().prepare().unwrap_err();
        assert!(matches!(err, XdgError::PersistentPath(_)));
        fs::set_permissions(&parent, fs::Permissions::from_mode(0o700)).unwrap();
        let _ = fs::remove_dir_all(root);
    }
}
