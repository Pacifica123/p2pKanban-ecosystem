use std::{
    fs,
    io,
    os::unix::fs::{DirBuilderExt, OpenOptionsExt, PermissionsExt},
    path::{Path, PathBuf},
};

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ProfileStoragePaths {
    root: PathBuf,
    database: PathBuf,
    backups: PathBuf,
    migration_journal: PathBuf,
    encrypted_vault: PathBuf,
    passphrase_root_wrap: PathBuf,
}

impl ProfileStoragePaths {
    pub fn new(root: PathBuf) -> Self {
        Self {
            database: root.join("profile.db"),
            backups: root.join("backups"),
            migration_journal: root.join("migration-journal.json"),
            encrypted_vault: root.join("secrets.vault"),
            passphrase_root_wrap: root.join("vault-root.passphrase"),
            root,
        }
    }

    pub fn root(&self) -> &Path {
        &self.root
    }

    pub fn database(&self) -> &Path {
        &self.database
    }

    pub fn backups(&self) -> &Path {
        &self.backups
    }

    pub fn migration_journal(&self) -> &Path {
        &self.migration_journal
    }

    pub fn encrypted_vault(&self) -> &Path {
        &self.encrypted_vault
    }

    pub fn passphrase_root_wrap(&self) -> &Path {
        &self.passphrase_root_wrap
    }

    pub fn migration_backup(&self, from_version: u32) -> PathBuf {
        self.backups.join(format!("pre-migration-v{from_version}.sqlite"))
    }

    pub fn prepare(&self) -> io::Result<()> {
        create_private_dir(&self.root)?;
        create_private_dir(&self.backups)?;
        Ok(())
    }

    pub fn enforce_database_permissions(&self) -> io::Result<()> {
        if self.database.is_file() {
            fs::set_permissions(&self.database, fs::Permissions::from_mode(0o600))?;
        }
        Ok(())
    }
}

pub(crate) fn create_private_dir(path: &Path) -> io::Result<()> {
    if path.exists() {
        if !path.is_dir() {
            return Err(io::Error::new(io::ErrorKind::AlreadyExists, "path is not a directory"));
        }
        fs::set_permissions(path, fs::Permissions::from_mode(0o700))?;
        return Ok(());
    }
    fs::DirBuilder::new().recursive(true).mode(0o700).create(path)
}

pub(crate) fn write_private_file(path: &Path, bytes: &[u8]) -> io::Result<()> {
    use std::io::Write;

    let mut options = fs::OpenOptions::new();
    options.create(true).truncate(true).write(true).mode(0o600);
    let mut file = options.open(path)?;
    file.write_all(bytes)?;
    file.sync_all()?;
    fs::set_permissions(path, fs::Permissions::from_mode(0o600))?;
    Ok(())
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
        std::env::temp_dir().join(format!("p2pkanban-a06-profile-{name}-{}-{n}", std::process::id()))
    }

    #[test]
    fn profile_storage_layout_matches_architecture() {
        let root = PathBuf::from("/tmp/example/profiles/default");
        let paths = ProfileStoragePaths::new(root.clone());
        assert_eq!(paths.root(), root);
        assert_eq!(paths.database(), Path::new("/tmp/example/profiles/default/profile.db"));
        assert_eq!(paths.backups(), Path::new("/tmp/example/profiles/default/backups"));
        assert_eq!(paths.migration_journal(), Path::new("/tmp/example/profiles/default/migration-journal.json"));
        assert_eq!(paths.encrypted_vault(), Path::new("/tmp/example/profiles/default/secrets.vault"));
        assert_eq!(paths.passphrase_root_wrap(), Path::new("/tmp/example/profiles/default/vault-root.passphrase"));
        assert_eq!(
            paths.migration_backup(0),
            PathBuf::from("/tmp/example/profiles/default/backups/pre-migration-v0.sqlite")
        );
    }

    #[test]
    fn private_dirs_and_files_are_user_only() {
        let root = temp_root("permissions");
        let paths = ProfileStoragePaths::new(root.clone());
        paths.prepare().unwrap();
        write_private_file(paths.migration_journal(), b"{}\n").unwrap();
        let root_mode = fs::metadata(paths.root()).unwrap().permissions().mode() & 0o777;
        let backup_mode = fs::metadata(paths.backups()).unwrap().permissions().mode() & 0o777;
        let journal_mode = fs::metadata(paths.migration_journal()).unwrap().permissions().mode() & 0o777;
        assert_eq!(root_mode, 0o700);
        assert_eq!(backup_mode, 0o700);
        assert_eq!(journal_mode, 0o600);
        let _ = fs::remove_dir_all(root);
    }
}
