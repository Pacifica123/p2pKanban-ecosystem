use std::{
    collections::{BTreeMap, HashMap},
    fs,
    io::Write,
    os::unix::fs::{OpenOptionsExt, PermissionsExt},
    path::{Path, PathBuf},
    sync::{Mutex, MutexGuard},
};

use argon2::{Algorithm, Argon2, Params, Version};
use chacha20poly1305::{
    aead::{Aead, KeyInit, Payload},
    XChaCha20Poly1305, XNonce,
};
use secret_service::{blocking::SecretService, EncryptionType};

use crate::{
    application::vault::{
        SecretKind, SecretRecordKey, SecretValue, SecretVault, VaultError, VaultMode, VaultService,
        VaultState, VaultStatus,
    },
    infrastructure::profile::ProfileStoragePaths,
};

const VAULT_MAGIC: &[u8] = b"P2PKVAULT\x01";
const ROOT_WRAP_MAGIC: &[u8] = b"P2PKROOT\x01";
const VAULT_AAD: &[u8] = b"p2pkanban:typed-secret-vault:v1";
const ROOT_WRAP_AAD: &[u8] = b"p2pkanban:vault-root-wrap:v1";
const ROOT_BYTES: usize = 32;
const NONCE_BYTES: usize = 24;
const SALT_BYTES: usize = 16;
const MAX_VAULT_FILE: usize = 4 * 1024 * 1024;
const MAX_RECORDS: usize = 4096;
const ARGON2_M_KIB: u32 = 19_456;
const ARGON2_T: u32 = 2;
const ARGON2_P: u32 = 1;
const ARGON2_MIN_M_KIB: u32 = 8_192;
const ARGON2_MAX_M_KIB: u32 = 262_144;
const ARGON2_MAX_T: u32 = 10;
const ARGON2_MAX_P: u32 = 16;
const KDF_PARAMS_BYTES: usize = 12;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
struct PassphraseKdfParams {
    m_kib: u32,
    t: u32,
    p: u32,
}

impl PassphraseKdfParams {
    const CURRENT: Self = Self { m_kib: ARGON2_M_KIB, t: ARGON2_T, p: ARGON2_P };

    fn validate(self) -> Result<Self, VaultError> {
        if self.m_kib < ARGON2_MIN_M_KIB
            || self.m_kib > ARGON2_MAX_M_KIB
            || self.t == 0
            || self.t > ARGON2_MAX_T
            || self.p == 0
            || self.p > ARGON2_MAX_P
        {
            return Err(VaultError::Corrupt);
        }
        Ok(self)
    }
}

struct SensitiveKey([u8; ROOT_BYTES]);

impl SensitiveKey {
    fn expose(&self) -> &[u8; ROOT_BYTES] { &self.0 }
}

impl Drop for SensitiveKey {
    fn drop(&mut self) { self.0.fill(0); }
}

struct VaultRoot([u8; ROOT_BYTES]);

impl VaultRoot {
    fn random() -> Result<Self, VaultError> {
        let mut bytes = [0_u8; ROOT_BYTES];
        getrandom::fill(&mut bytes).map_err(|_| VaultError::Crypto)?;
        Ok(Self(bytes))
    }

    fn from_bytes(bytes: &[u8]) -> Result<Self, VaultError> {
        let root: [u8; ROOT_BYTES] = bytes.try_into().map_err(|_| VaultError::Corrupt)?;
        Ok(Self(root))
    }

    fn expose(&self) -> &[u8; ROOT_BYTES] {
        &self.0
    }
}

impl Drop for VaultRoot {
    fn drop(&mut self) {
        self.0.fill(0);
    }
}

pub struct Passphrase(Vec<u8>);

impl Passphrase {
    pub fn new(value: impl Into<Vec<u8>>) -> Result<Self, VaultError> {
        let value = value.into();
        if value.len() < 12 || value.len() > 1024 {
            return Err(VaultError::AuthenticationFailed);
        }
        Ok(Self(value))
    }

    fn expose(&self) -> &[u8] {
        &self.0
    }
}

impl Drop for Passphrase {
    fn drop(&mut self) {
        self.0.fill(0);
    }
}

pub struct EncryptedFileVault {
    path: PathBuf,
    root: VaultRoot,
    mode: VaultMode,
    values: Mutex<BTreeMap<SecretRecordKey, SecretValue>>,
}

impl EncryptedFileVault {
    fn open(path: PathBuf, root: VaultRoot, mode: VaultMode) -> Result<Self, VaultError> {
        let values = if path.exists() {
            decrypt_vault_file(&path, root.expose())?
        } else {
            BTreeMap::new()
        };
        Ok(Self { path, root, mode, values: Mutex::new(values) })
    }

    fn lock(&self) -> Result<MutexGuard<'_, BTreeMap<SecretRecordKey, SecretValue>>, VaultError> {
        self.values.lock().map_err(|_| VaultError::Poisoned)
    }

    fn persist(&self, values: &BTreeMap<SecretRecordKey, SecretValue>) -> Result<(), VaultError> {
        let mut plaintext = encode_records(values)?;
        let encrypted = encrypt_envelope(VAULT_MAGIC, VAULT_AAD, self.root.expose(), &plaintext);
        plaintext.fill(0);
        atomic_private_write(&self.path, &encrypted?)
    }
}

impl SecretVault for EncryptedFileVault {
    fn status(&self) -> VaultStatus {
        VaultStatus::durable(self.mode)
    }

    fn put(&self, key: SecretRecordKey, value: SecretValue) -> Result<(), VaultError> {
        let mut values = self.lock()?;
        let previous = values.insert(key.clone(), value);
        if let Err(error) = self.persist(&values) {
            match previous {
                Some(old) => { values.insert(key, old); }
                None => { values.remove(&key); }
            }
            return Err(error);
        }
        Ok(())
    }

    fn get(&self, key: &SecretRecordKey) -> Result<Option<SecretValue>, VaultError> {
        Ok(self.lock()?.get(key).map(SecretValue::duplicate))
    }

    fn delete(&self, key: &SecretRecordKey) -> Result<(), VaultError> {
        let mut values = self.lock()?;
        let previous = values.remove(key);
        if let Err(error) = self.persist(&values) {
            if let Some(old) = previous {
                values.insert(key.clone(), old);
            }
            return Err(error);
        }
        Ok(())
    }
}

pub struct PassphraseVault;

impl PassphraseVault {
    pub fn open_or_create(
        profile: &ProfileStoragePaths,
        passphrase: &Passphrase,
    ) -> Result<EncryptedFileVault, VaultError> {
        let root = if profile.passphrase_root_wrap().exists() {
            unwrap_root_with_passphrase(profile.passphrase_root_wrap(), passphrase)?
        } else {
            let root = VaultRoot::random()?;
            write_passphrase_root_wrap(profile.passphrase_root_wrap(), passphrase, &root)?;
            root
        };
        EncryptedFileVault::open(profile.encrypted_vault().to_path_buf(), root, VaultMode::Passphrase)
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum SecretServiceRootState {
    Locked,
    Unavailable,
    Corrupt,
}

fn secret_service_root(
    profile_name: &str,
    encrypted_vault_exists: bool,
) -> Result<VaultRoot, SecretServiceRootState> {
    let service = SecretService::connect(EncryptionType::Dh)
        .map_err(|_| SecretServiceRootState::Unavailable)?;
    let collection = service.get_default_collection()
        .map_err(|_| SecretServiceRootState::Unavailable)?;
    if collection.is_locked().map_err(|_| SecretServiceRootState::Unavailable)? {
        return Err(SecretServiceRootState::Locked);
    }

    let attributes = HashMap::from([
        ("application", "p2pkanban"),
        ("profile", profile_name),
        ("purpose", "vault-root-v1"),
    ]);
    let items = collection.search_items(attributes.clone())
        .map_err(|_| SecretServiceRootState::Unavailable)?;

    if items.len() > 1 {
        return Err(SecretServiceRootState::Corrupt);
    }

    if let Some(item) = items.first() {
        if item.is_locked().map_err(|_| SecretServiceRootState::Unavailable)? {
            return Err(SecretServiceRootState::Locked);
        }
        let mut bytes = item.get_secret().map_err(|_| SecretServiceRootState::Unavailable)?;
        let root = VaultRoot::from_bytes(&bytes).map_err(|_| SecretServiceRootState::Corrupt);
        bytes.fill(0);
        return root;
    }

    if encrypted_vault_exists {
        return Err(SecretServiceRootState::Corrupt);
    }

    let root = VaultRoot::random().map_err(|_| SecretServiceRootState::Unavailable)?;
    collection.create_item(
        "p2pKanban vault root",
        attributes,
        root.expose(),
        true,
        "application/octet-stream",
    ).map_err(|_| SecretServiceRootState::Unavailable)?;
    Ok(root)
}

pub fn bootstrap_vault(profile: &ProfileStoragePaths, profile_name: &str) -> VaultService {
    if profile.passphrase_root_wrap().is_file() {
        return VaultService::session_only_with_state(VaultState::PassphraseRequired);
    }

    match secret_service_root(profile_name, profile.encrypted_vault().is_file()) {
        Ok(root) => match EncryptedFileVault::open(
            profile.encrypted_vault().to_path_buf(), root, VaultMode::SecretService,
        ) {
            Ok(vault) => VaultService::from_provider(vault),
            Err(_) => VaultService::session_only_with_state(VaultState::ProviderCorrupt),
        },
        Err(SecretServiceRootState::Locked) => VaultService::session_only_with_state(VaultState::ProviderLocked),
        Err(SecretServiceRootState::Unavailable) => VaultService::session_only_with_state(VaultState::ProviderUnavailable),
        Err(SecretServiceRootState::Corrupt) => VaultService::session_only_with_state(VaultState::ProviderCorrupt),
    }
}

fn argon2id(params: PassphraseKdfParams) -> Result<Argon2<'static>, VaultError> {
    let params = params.validate()?;
    let params = Params::new(params.m_kib, params.t, params.p, Some(ROOT_BYTES))
        .map_err(|_| VaultError::Crypto)?;
    Ok(Argon2::new(Algorithm::Argon2id, Version::V0x13, params))
}

fn derive_kek(
    passphrase: &Passphrase,
    salt: &[u8; SALT_BYTES],
    params: PassphraseKdfParams,
) -> Result<SensitiveKey, VaultError> {
    let mut key = SensitiveKey([0_u8; ROOT_BYTES]);
    argon2id(params)?.hash_password_into(passphrase.expose(), salt, &mut key.0)
        .map_err(|_| VaultError::Crypto)?;
    Ok(key)
}

fn encode_kdf_params(out: &mut Vec<u8>, params: PassphraseKdfParams) {
    out.extend_from_slice(&params.m_kib.to_le_bytes());
    out.extend_from_slice(&params.t.to_le_bytes());
    out.extend_from_slice(&params.p.to_le_bytes());
}

fn decode_kdf_params(bytes: &[u8]) -> Result<PassphraseKdfParams, VaultError> {
    if bytes.len() != KDF_PARAMS_BYTES { return Err(VaultError::Corrupt); }
    let m_kib = u32::from_le_bytes(bytes[0..4].try_into().map_err(|_| VaultError::Corrupt)?);
    let t = u32::from_le_bytes(bytes[4..8].try_into().map_err(|_| VaultError::Corrupt)?);
    let p = u32::from_le_bytes(bytes[8..12].try_into().map_err(|_| VaultError::Corrupt)?);
    PassphraseKdfParams { m_kib, t, p }.validate()
}

fn write_passphrase_root_wrap(
    path: &Path,
    passphrase: &Passphrase,
    root: &VaultRoot,
) -> Result<(), VaultError> {
    let params = PassphraseKdfParams::CURRENT;
    let mut salt = [0_u8; SALT_BYTES];
    getrandom::fill(&mut salt).map_err(|_| VaultError::Crypto)?;
    let key = derive_kek(passphrase, &salt, params)?;
    let encrypted = encrypt_envelope(ROOT_WRAP_MAGIC, ROOT_WRAP_AAD, key.expose(), root.expose())?;

    let mut out = Vec::with_capacity(
        ROOT_WRAP_MAGIC.len() + KDF_PARAMS_BYTES + SALT_BYTES + encrypted.len(),
    );
    out.extend_from_slice(ROOT_WRAP_MAGIC);
    encode_kdf_params(&mut out, params);
    out.extend_from_slice(&salt);
    out.extend_from_slice(&encrypted[ROOT_WRAP_MAGIC.len()..]);
    atomic_private_write(path, &out)
}

fn unwrap_root_with_passphrase(path: &Path, passphrase: &Passphrase) -> Result<VaultRoot, VaultError> {
    let bytes = read_bounded(path, 4096)?;
    let prefix = ROOT_WRAP_MAGIC.len();
    let header = prefix + KDF_PARAMS_BYTES + SALT_BYTES + NONCE_BYTES + 16;
    if bytes.len() < header || !bytes.starts_with(ROOT_WRAP_MAGIC) {
        return Err(VaultError::Corrupt);
    }
    let params = decode_kdf_params(&bytes[prefix..prefix + KDF_PARAMS_BYTES])?;
    let salt_start = prefix + KDF_PARAMS_BYTES;
    let salt_end = salt_start + SALT_BYTES;
    let salt: [u8; SALT_BYTES] = bytes[salt_start..salt_end]
        .try_into().map_err(|_| VaultError::Corrupt)?;
    let key = derive_kek(passphrase, &salt, params)?;

    let mut normalized = Vec::with_capacity(bytes.len() - KDF_PARAMS_BYTES - SALT_BYTES);
    normalized.extend_from_slice(ROOT_WRAP_MAGIC);
    normalized.extend_from_slice(&bytes[salt_end..]);
    let mut plaintext = decrypt_envelope(ROOT_WRAP_MAGIC, ROOT_WRAP_AAD, key.expose(), &normalized)
        .map_err(|_| VaultError::AuthenticationFailed)?;
    let root = VaultRoot::from_bytes(&plaintext).map_err(|_| VaultError::Corrupt);
    plaintext.fill(0);
    root
}

fn encrypt_envelope(
    magic: &[u8], aad: &[u8], key: &[u8; ROOT_BYTES], plaintext: &[u8],
) -> Result<Vec<u8>, VaultError> {
    let cipher = XChaCha20Poly1305::new_from_slice(key).map_err(|_| VaultError::Crypto)?;
    let mut nonce = [0_u8; NONCE_BYTES];
    getrandom::fill(&mut nonce).map_err(|_| VaultError::Crypto)?;
    let ciphertext = cipher.encrypt(
        XNonce::from_slice(&nonce), Payload { msg: plaintext, aad },
    ).map_err(|_| VaultError::Crypto)?;
    let mut out = Vec::with_capacity(magic.len() + NONCE_BYTES + ciphertext.len());
    out.extend_from_slice(magic);
    out.extend_from_slice(&nonce);
    out.extend_from_slice(&ciphertext);
    Ok(out)
}

fn decrypt_envelope(
    magic: &[u8], aad: &[u8], key: &[u8; ROOT_BYTES], bytes: &[u8],
) -> Result<Vec<u8>, VaultError> {
    if bytes.len() < magic.len() + NONCE_BYTES + 16 || !bytes.starts_with(magic) {
        return Err(VaultError::Corrupt);
    }
    let nonce_start = magic.len();
    let nonce_end = nonce_start + NONCE_BYTES;
    let cipher = XChaCha20Poly1305::new_from_slice(key).map_err(|_| VaultError::Crypto)?;
    cipher.decrypt(
        XNonce::from_slice(&bytes[nonce_start..nonce_end]),
        Payload { msg: &bytes[nonce_end..], aad },
    ).map_err(|_| VaultError::AuthenticationFailed)
}

fn decrypt_vault_file(
    path: &Path, root: &[u8; ROOT_BYTES],
) -> Result<BTreeMap<SecretRecordKey, SecretValue>, VaultError> {
    let bytes = read_bounded(path, MAX_VAULT_FILE)?;
    let mut plaintext = decrypt_envelope(VAULT_MAGIC, VAULT_AAD, root, &bytes)
        .map_err(|_| VaultError::Corrupt)?;
    let decoded = decode_records(&plaintext);
    plaintext.fill(0);
    decoded
}

fn push_u32(out: &mut Vec<u8>, value: usize) -> Result<(), VaultError> {
    let value = u32::try_from(value).map_err(|_| VaultError::Corrupt)?;
    out.extend_from_slice(&value.to_le_bytes());
    Ok(())
}

fn read_u32(input: &[u8], cursor: &mut usize) -> Result<usize, VaultError> {
    let end = cursor.checked_add(4).ok_or(VaultError::Corrupt)?;
    let bytes: [u8; 4] = input.get(*cursor..end).ok_or(VaultError::Corrupt)?
        .try_into().map_err(|_| VaultError::Corrupt)?;
    *cursor = end;
    Ok(u32::from_le_bytes(bytes) as usize)
}

fn take<'a>(input: &'a [u8], cursor: &mut usize, len: usize) -> Result<&'a [u8], VaultError> {
    let end = cursor.checked_add(len).ok_or(VaultError::Corrupt)?;
    let bytes = input.get(*cursor..end).ok_or(VaultError::Corrupt)?;
    *cursor = end;
    Ok(bytes)
}

fn encode_records(values: &BTreeMap<SecretRecordKey, SecretValue>) -> Result<Vec<u8>, VaultError> {
    if values.len() > MAX_RECORDS { return Err(VaultError::Corrupt); }
    let mut out = Vec::new();
    push_u32(&mut out, values.len())?;
    for (key, value) in values {
        out.push(key.kind.stable_code());
        push_u32(&mut out, key.scope_id.len())?;
        out.extend_from_slice(key.scope_id.as_bytes());
        push_u32(&mut out, value.expose().len())?;
        out.extend_from_slice(value.expose());
    }
    Ok(out)
}

fn decode_records(bytes: &[u8]) -> Result<BTreeMap<SecretRecordKey, SecretValue>, VaultError> {
    let mut cursor = 0;
    let count = read_u32(bytes, &mut cursor)?;
    if count > MAX_RECORDS { return Err(VaultError::Corrupt); }
    let mut values = BTreeMap::new();
    for _ in 0..count {
        let code = *take(bytes, &mut cursor, 1)?.first().ok_or(VaultError::Corrupt)?;
        let scope_len = read_u32(bytes, &mut cursor)?;
        if scope_len == 0 || scope_len > 512 { return Err(VaultError::Corrupt); }
        let scope = std::str::from_utf8(take(bytes, &mut cursor, scope_len)?)
            .map_err(|_| VaultError::Corrupt)?;
        let secret_len = read_u32(bytes, &mut cursor)?;
        if secret_len == 0 || secret_len > 65_536 { return Err(VaultError::Corrupt); }
        let secret = take(bytes, &mut cursor, secret_len)?.to_vec();
        let key = SecretRecordKey::new(SecretKind::from_stable_code(code)?, scope.to_owned())?;
        if values.insert(key, SecretValue::new(secret)?).is_some() {
            return Err(VaultError::Corrupt);
        }
    }
    if cursor != bytes.len() { return Err(VaultError::Corrupt); }
    Ok(values)
}

fn read_bounded(path: &Path, limit: usize) -> Result<Vec<u8>, VaultError> {
    let metadata = fs::symlink_metadata(path).map_err(|_| VaultError::Io)?;
    if !metadata.file_type().is_file() || metadata.len() as usize > limit {
        return Err(VaultError::Corrupt);
    }
    fs::read(path).map_err(|_| VaultError::Io)
}

fn atomic_private_write(path: &Path, bytes: &[u8]) -> Result<(), VaultError> {
    let parent = path.parent().ok_or(VaultError::Io)?;
    fs::create_dir_all(parent).map_err(|_| VaultError::Io)?;
    fs::set_permissions(parent, fs::Permissions::from_mode(0o700)).map_err(|_| VaultError::Io)?;

    let mut random = [0_u8; 8];
    let (temp, mut file) = (0..8).find_map(|_| {
        getrandom::fill(&mut random).ok()?;
        let candidate = parent.join(format!(
            ".p2pkanban-vault-{:016x}.tmp",
            u64::from_le_bytes(random),
        ));
        let mut options = fs::OpenOptions::new();
        options
            .create_new(true)
            .write(true)
            .mode(0o600)
            .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC);
        match options.open(&candidate) {
            Ok(file) => Some((candidate, file)),
            Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => None,
            Err(_) => None,
        }
    }).ok_or(VaultError::Io)?;

    let write_result = (|| -> Result<(), VaultError> {
        file.write_all(bytes).map_err(|_| VaultError::Io)?;
        file.sync_all().map_err(|_| VaultError::Io)?;
        fs::rename(&temp, path).map_err(|_| VaultError::Io)?;
        let dir = fs::File::open(parent).map_err(|_| VaultError::Io)?;
        dir.sync_all().map_err(|_| VaultError::Io)?;
        Ok(())
    })();
    if write_result.is_err() {
        let _ = fs::remove_file(&temp);
    }
    write_result
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::{os::unix::fs::PermissionsExt, sync::atomic::{AtomicU64, Ordering}};

    static NEXT: AtomicU64 = AtomicU64::new(1);

    fn temp_profile(name: &str) -> (PathBuf, ProfileStoragePaths) {
        let n = NEXT.fetch_add(1, Ordering::Relaxed);
        let root = std::env::temp_dir().join(format!("p2pkanban-a09-{name}-{}-{n}", std::process::id()));
        let profile = ProfileStoragePaths::new(root.clone());
        profile.prepare().unwrap();
        (root, profile)
    }

    fn test_passphrase() -> Passphrase {
        Passphrase::new(b"correct horse battery staple".to_vec()).unwrap()
    }

    #[test]
    fn a09_passphrase_vault_round_trip_is_encrypted_at_rest() {
        let (root, profile) = temp_profile("roundtrip");
        let key = SecretRecordKey::new(SecretKind::BoardCapability, "board-a").unwrap();
        let canary = std::env::var("P2PKANBAN_UTS_SECRET_CANARY")
            .unwrap_or_else(|_| "a09-runtime-secret-canary".to_owned());
        {
            let vault = PassphraseVault::open_or_create(&profile, &test_passphrase()).unwrap();
            vault.put(key.clone(), SecretValue::new(canary.as_bytes().to_vec()).unwrap()).unwrap();
            assert_eq!(vault.status().mode, VaultMode::Passphrase);
            assert!(vault.status().durable);
        }
        let raw = fs::read(profile.encrypted_vault()).unwrap();
        assert!(!raw.windows(canary.len()).any(|window| window == canary.as_bytes()));
        let reopened = PassphraseVault::open_or_create(&profile, &test_passphrase()).unwrap();
        assert_eq!(reopened.get(&key).unwrap().unwrap().expose(), canary.as_bytes());
        let mode = fs::metadata(profile.encrypted_vault()).unwrap().permissions().mode() & 0o777;
        assert_eq!(mode, 0o600);
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn a09_wrong_passphrase_and_corruption_fail_closed() {
        let (root, profile) = temp_profile("wrong-passphrase");
        let vault = PassphraseVault::open_or_create(&profile, &test_passphrase()).unwrap();
        let key = SecretRecordKey::new(SecretKind::RefreshToken, "account-a").unwrap();
        vault.put(key, SecretValue::new(b"refresh-secret".to_vec()).unwrap()).unwrap();
        drop(vault);

        let wrong = Passphrase::new(b"definitely wrong passphrase".to_vec()).unwrap();
        assert!(matches!(PassphraseVault::open_or_create(&profile, &wrong), Err(VaultError::AuthenticationFailed)));

        let mut bytes = fs::read(profile.encrypted_vault()).unwrap();
        let last = bytes.len() - 1;
        bytes[last] ^= 0x55;
        atomic_private_write(profile.encrypted_vault(), &bytes).unwrap();
        assert!(matches!(PassphraseVault::open_or_create(&profile, &test_passphrase()), Err(VaultError::Corrupt)));
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn a09_existing_passphrase_wrapper_blocks_automatic_provider_rebinding() {
        let (root, profile) = temp_profile("passphrase-marker");
        let _vault = PassphraseVault::open_or_create(&profile, &test_passphrase()).unwrap();
        let service = bootstrap_vault(&profile, "default");
        assert_eq!(service.status().mode, VaultMode::SessionOnly);
        assert_eq!(service.status().state, VaultState::PassphraseRequired);
        assert!(!service.status().durable);
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn a09_argon2id_parameters_are_versioned_and_nontrivial() {
        assert_eq!((ARGON2_M_KIB, ARGON2_T, ARGON2_P), (19_456, 2, 1));
        let params = argon2id(PassphraseKdfParams::CURRENT).unwrap();
        assert_eq!(params.params().m_cost(), ARGON2_M_KIB);
        assert_eq!(params.params().t_cost(), ARGON2_T);
        assert_eq!(params.params().p_cost(), ARGON2_P);

        let (root, profile) = temp_profile("kdf-format");
        let _vault = PassphraseVault::open_or_create(&profile, &test_passphrase()).unwrap();
        let bytes = fs::read(profile.passphrase_root_wrap()).unwrap();
        let start = ROOT_WRAP_MAGIC.len();
        assert_eq!(
            decode_kdf_params(&bytes[start..start + KDF_PARAMS_BYTES]).unwrap(),
            PassphraseKdfParams::CURRENT,
        );
        let _ = fs::remove_dir_all(root);
    }
}
