use std::{
    fs,
    io,
    os::fd::AsRawFd,
};

use crate::infrastructure::linux::xdg::PreparedDesktopPaths;

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum RecoveryLockError {
    Io(io::ErrorKind),
    Lock(io::ErrorKind),
}

/// Exclusive profile ownership for CLI/native recovery operations.
///
/// This deliberately does not create the A06/A13 activation socket and never
/// routes a secondary launch to a graphical process. Recovery must operate on a
/// quiescent profile or fail closed.
pub struct RecoveryProfileLock {
    lock_dir: fs::File,
}

impl Drop for RecoveryProfileLock {
    fn drop(&mut self) {
        let _ = unsafe { libc::flock(self.lock_dir.as_raw_fd(), libc::LOCK_UN) };
    }
}

pub fn acquire(paths: &PreparedDesktopPaths) -> Result<Option<RecoveryProfileLock>, RecoveryLockError> {
    let file = fs::File::open(paths.paths.profile.root())
        .map_err(|error| RecoveryLockError::Io(error.kind()))?;
    let rc = unsafe { libc::flock(file.as_raw_fd(), libc::LOCK_EX | libc::LOCK_NB) };
    if rc == 0 {
        return Ok(Some(RecoveryProfileLock { lock_dir: file }));
    }
    let error = io::Error::last_os_error();
    if error.raw_os_error() == Some(libc::EWOULDBLOCK)
        || error.raw_os_error() == Some(libc::EAGAIN)
    {
        return Ok(None);
    }
    Err(RecoveryLockError::Lock(error.kind()))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::infrastructure::linux::xdg::{DesktopPaths, XdgEnvironment};
    use std::{
        fs,
        os::unix::fs::PermissionsExt,
        path::PathBuf,
        sync::atomic::{AtomicU64, Ordering},
    };

    static NEXT: AtomicU64 = AtomicU64::new(1);

    fn prepared() -> PreparedDesktopPaths {
        let n = NEXT.fetch_add(1, Ordering::Relaxed);
        let root = std::env::temp_dir().join(format!(
            "p2pkanban-a16-recovery-lock-{}-{n}",
            std::process::id()
        ));
        let runtime = root.join("runtime");
        fs::create_dir_all(&runtime).unwrap();
        fs::set_permissions(&runtime, fs::Permissions::from_mode(0o700)).unwrap();
        DesktopPaths::resolve(
            &XdgEnvironment::from_pairs([
                ("HOME", root.join("home")),
                ("XDG_DATA_HOME", root.join("data")),
                ("XDG_CONFIG_HOME", root.join("config")),
                ("XDG_STATE_HOME", root.join("state")),
                ("XDG_CACHE_HOME", root.join("cache")),
                ("XDG_RUNTIME_DIR", runtime),
            ]),
            "default",
        )
        .unwrap()
        .prepare()
        .unwrap()
    }

    fn cleanup(paths: &PreparedDesktopPaths) {
        let root = paths
            .paths
            .data_root
            .parent()
            .and_then(|path| path.parent())
            .map(PathBuf::from);
        if let Some(root) = root {
            let _ = fs::remove_dir_all(root);
        }
    }

    #[test]
    fn a16_recovery_lock_is_exclusive_without_activation_socket() {
        let paths = prepared();
        let activation = paths.activation_socket().unwrap();
        let first = acquire(&paths).unwrap().expect("first recovery owner");
        assert!(!activation.exists());
        assert!(acquire(&paths).unwrap().is_none());
        drop(first);
        assert!(acquire(&paths).unwrap().is_some());
        cleanup(&paths);
    }
}
