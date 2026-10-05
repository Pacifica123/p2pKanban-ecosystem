use std::{
    fs,
    io,
    os::{fd::AsRawFd, unix::fs::PermissionsExt, unix::net::UnixDatagram},
    path::{Path, PathBuf},
};

use crate::infrastructure::linux::xdg::PreparedDesktopPaths;

pub const ACTIVATE_MAIN_V1: &[u8] = b"activate-main-v1\n";
pub const MAX_ACTIVATION_PAYLOAD_BYTES: usize = 1024;

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum InstanceError {
    Io(io::ErrorKind),
    Lock(io::ErrorKind),
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SecondaryInstance {
    Routed,
    RoutingUnavailable,
}

pub enum InstanceRole {
    Primary(PrimaryInstance),
    Secondary(SecondaryInstance),
}

pub struct PrimaryInstance {
    lock_dir: fs::File,
    socket_path: Option<PathBuf>,
    receiver: Option<UnixDatagram>,
}

impl PrimaryInstance {
    pub fn take_activation_receiver(&mut self) -> Option<UnixDatagram> {
        self.receiver.take()
    }
}

impl Drop for PrimaryInstance {
    fn drop(&mut self) {
        let _ = unsafe { libc::flock(self.lock_dir.as_raw_fd(), libc::LOCK_UN) };
        if let Some(path) = &self.socket_path {
            let _ = fs::remove_file(path);
        }
    }
}

fn try_lock_profile_dir(path: &Path) -> Result<Option<fs::File>, InstanceError> {
    let file = fs::File::open(path).map_err(|err| InstanceError::Io(err.kind()))?;
    let rc = unsafe { libc::flock(file.as_raw_fd(), libc::LOCK_EX | libc::LOCK_NB) };
    if rc == 0 {
        return Ok(Some(file));
    }
    let err = io::Error::last_os_error();
    if err.raw_os_error() == Some(libc::EWOULDBLOCK) || err.raw_os_error() == Some(libc::EAGAIN) {
        return Ok(None);
    }
    Err(InstanceError::Lock(err.kind()))
}

fn route_bytes(socket: Option<&Path>, payload: &[u8]) -> bool {
    let Some(socket) = socket else {
        return false;
    };
    if payload.is_empty() || payload.len() > MAX_ACTIVATION_PAYLOAD_BYTES {
        return false;
    }
    UnixDatagram::unbound()
        .and_then(|sender| sender.send_to(payload, socket))
        .map(|written| written == payload.len())
        .unwrap_or(false)
}

fn route_activation(socket: Option<&Path>) -> bool {
    route_bytes(socket, ACTIVATE_MAIN_V1)
}

pub fn route_payload(paths: &PreparedDesktopPaths, payload: &[u8]) -> bool {
    route_bytes(paths.activation_socket().as_deref(), payload)
}

fn bind_activation_socket(path: &Path) -> Result<UnixDatagram, InstanceError> {
    if fs::symlink_metadata(path).is_ok() {
        fs::remove_file(path).map_err(|err| InstanceError::Io(err.kind()))?;
    }
    let socket = UnixDatagram::bind(path).map_err(|err| InstanceError::Io(err.kind()))?;
    fs::set_permissions(path, fs::Permissions::from_mode(0o600))
        .map_err(|err| InstanceError::Io(err.kind()))?;
    Ok(socket)
}

pub fn acquire(paths: &PreparedDesktopPaths) -> Result<InstanceRole, InstanceError> {
    let activation_socket = paths.activation_socket();
    let Some(lock_dir) = try_lock_profile_dir(paths.paths.profile.root())? else {
        return Ok(InstanceRole::Secondary(if route_activation(activation_socket.as_deref()) {
            SecondaryInstance::Routed
        } else {
            SecondaryInstance::RoutingUnavailable
        }));
    };

    let receiver = match activation_socket.as_deref() {
        Some(path) => Some(bind_activation_socket(path)?),
        None => None,
    };
    Ok(InstanceRole::Primary(PrimaryInstance {
        lock_dir,
        socket_path: activation_socket,
        receiver,
    }))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::infrastructure::linux::xdg::{DesktopPaths, XdgEnvironment};
    use std::{
        os::unix::fs::PermissionsExt,
        process::Command,
        sync::atomic::{AtomicU64, Ordering},
        time::Duration,
    };

    static NEXT: AtomicU64 = AtomicU64::new(1);

    fn temp_root(name: &str) -> PathBuf {
        let n = NEXT.fetch_add(1, Ordering::Relaxed);
        std::env::temp_dir().join(format!("p2pkanban-a06-instance-{name}-{}-{n}", std::process::id()))
    }

    fn prepared(name: &str, with_runtime: bool) -> PreparedDesktopPaths {
        let root = temp_root(name);
        let mut pairs = vec![
            ("HOME", root.join("home")),
            ("XDG_DATA_HOME", root.join("data")),
            ("XDG_CONFIG_HOME", root.join("config")),
            ("XDG_STATE_HOME", root.join("state")),
            ("XDG_CACHE_HOME", root.join("cache")),
        ];
        if with_runtime {
            let runtime = root.join("runtime");
            fs::create_dir_all(&runtime).unwrap();
            fs::set_permissions(&runtime, fs::Permissions::from_mode(0o700)).unwrap();
            pairs.push(("XDG_RUNTIME_DIR", runtime));
        }
        DesktopPaths::resolve(&XdgEnvironment::from_pairs(pairs), "default")
            .unwrap()
            .prepare()
            .unwrap()
    }

    #[test]
    fn concurrent_second_instance_is_routed_to_primary() {
        let paths = prepared("concurrent", true);
        let mut primary = match acquire(&paths).unwrap() {
            InstanceRole::Primary(primary) => primary,
            InstanceRole::Secondary(_) => panic!("first instance must be primary"),
        };
        let receiver = primary.take_activation_receiver().unwrap();
        receiver.set_read_timeout(Some(Duration::from_secs(1))).unwrap();
        assert!(matches!(acquire(&paths).unwrap(), InstanceRole::Secondary(SecondaryInstance::Routed)));
        let mut buf = [0_u8; 64];
        let read = receiver.recv(&mut buf).unwrap();
        assert_eq!(&buf[..read], ACTIVATE_MAIN_V1);
        drop(primary);
        let _ = fs::remove_dir_all(paths.paths.data_root.parent().unwrap().parent().unwrap());
    }

    #[test]
    fn a13_activation_payload_is_bounded_and_uses_existing_socket() {
        let paths = prepared("a13-payload", true);
        let mut primary = match acquire(&paths).unwrap() {
            InstanceRole::Primary(primary) => primary,
            _ => panic!("expected primary"),
        };
        let receiver = primary.take_activation_receiver().unwrap();
        receiver.set_read_timeout(Some(Duration::from_secs(1))).unwrap();
        let payload = b"deep-link-v1\tp2pkanban://activate\n";
        assert!(route_payload(&paths, payload));
        let mut buf = [0_u8; MAX_ACTIVATION_PAYLOAD_BYTES];
        let read = receiver.recv(&mut buf).unwrap();
        assert_eq!(&buf[..read], payload);
        assert!(!route_payload(&paths, &vec![b'x'; MAX_ACTIVATION_PAYLOAD_BYTES + 1]));
    }

    #[test]
    fn missing_runtime_keeps_writer_lock_but_routes_nothing() {
        let paths = prepared("no-runtime", false);
        let primary = match acquire(&paths).unwrap() {
            InstanceRole::Primary(primary) => primary,
            InstanceRole::Secondary(_) => panic!("first instance must be primary"),
        };
        assert!(matches!(
            acquire(&paths).unwrap(),
            InstanceRole::Secondary(SecondaryInstance::RoutingUnavailable)
        ));
        drop(primary);
        assert!(matches!(acquire(&paths).unwrap(), InstanceRole::Primary(_)));
    }

    #[test]
    fn stale_runtime_socket_is_replaced_only_after_writer_lock_is_owned() {
        let paths = prepared("stale-socket", true);
        let socket_path = paths.activation_socket().unwrap();
        let stale = UnixDatagram::bind(&socket_path).unwrap();
        drop(stale);
        assert!(socket_path.exists());
        let primary = match acquire(&paths).unwrap() {
            InstanceRole::Primary(primary) => primary,
            InstanceRole::Secondary(_) => panic!("stale socket must not imply live writer"),
        };
        assert!(socket_path.exists());
        drop(primary);
        assert!(!socket_path.exists());
    }

    #[test]
    fn lock_is_reacquired_after_guard_drop() {
        let paths = prepared("reopen", false);
        let primary = match acquire(&paths).unwrap() {
            InstanceRole::Primary(primary) => primary,
            _ => panic!("expected primary"),
        };
        drop(primary);
        assert!(matches!(acquire(&paths).unwrap(), InstanceRole::Primary(_)));
    }

    #[test]
    fn crash_holder_child() {
        if std::env::var_os("P2PKANBAN_A06_CRASH_CHILD").is_none() {
            return;
        }
        let profile_root = PathBuf::from(std::env::var_os("P2PKANBAN_A06_CRASH_PROFILE").unwrap());
        fs::create_dir_all(&profile_root).unwrap();
        let data_home = profile_root.ancestors().nth(3).unwrap().to_path_buf();
        let home = data_home.parent().unwrap().to_path_buf();
        let env = XdgEnvironment::from_pairs([
            ("HOME", home.clone()),
            ("XDG_DATA_HOME", data_home),
            ("XDG_CONFIG_HOME", home.join("config")),
            ("XDG_STATE_HOME", home.join("state")),
            ("XDG_CACHE_HOME", home.join("cache")),
        ]);
        let paths = DesktopPaths::resolve(&env, "default").unwrap().prepare().unwrap();
        let _guard = match acquire(&paths).unwrap() {
            InstanceRole::Primary(primary) => primary,
            _ => panic!("child failed to acquire profile lock"),
        };
        fs::write(std::env::var_os("P2PKANBAN_A06_CRASH_MARKER").unwrap(), b"locked").unwrap();
        unsafe { libc::_exit(99) };
    }

    #[test]
    fn kernel_lock_is_released_after_abnormal_child_exit() {
        let root = temp_root("crash");
        let data = root.join("data");
        let profile_root = data.join("p2pkanban/profiles/default");
        fs::create_dir_all(&profile_root).unwrap();
        let marker = root.join("child-held-lock");
        let status = Command::new(std::env::current_exe().unwrap())
            .arg("crash_holder_child")
            .arg("--nocapture")
            .env("P2PKANBAN_A06_CRASH_CHILD", "1")
            .env("P2PKANBAN_A06_CRASH_PROFILE", &profile_root)
            .env("P2PKANBAN_A06_CRASH_MARKER", &marker)
            .status()
            .unwrap();
        assert_eq!(status.code(), Some(99));
        assert_eq!(fs::read(&marker).unwrap(), b"locked");
        let env = XdgEnvironment::from_pairs([
            ("HOME", root.join("home")),
            ("XDG_DATA_HOME", data),
            ("XDG_CONFIG_HOME", root.join("config")),
            ("XDG_STATE_HOME", root.join("state")),
            ("XDG_CACHE_HOME", root.join("cache")),
        ]);
        let paths = DesktopPaths::resolve(&env, "default").unwrap().prepare().unwrap();
        assert!(matches!(acquire(&paths).unwrap(), InstanceRole::Primary(_)));
        let _ = fs::remove_dir_all(root);
    }
}
