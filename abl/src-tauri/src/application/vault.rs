use std::{
    collections::BTreeMap,
    sync::{Mutex, MutexGuard},
};

#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord)]
pub enum SecretKind {
    RefreshToken,
    BoardCapability,
    DevicePrivateKey,
}

impl SecretKind {
    pub fn stable_name(&self) -> &'static str {
        match self {
            Self::RefreshToken => "refresh-token",
            Self::BoardCapability => "board-capability",
            Self::DevicePrivateKey => "device-private-key",
        }
    }

    pub fn stable_code(&self) -> u8 {
        match self {
            Self::RefreshToken => 1,
            Self::BoardCapability => 2,
            Self::DevicePrivateKey => 3,
        }
    }

    pub fn from_stable_code(value: u8) -> Result<Self, VaultError> {
        match value {
            1 => Ok(Self::RefreshToken),
            2 => Ok(Self::BoardCapability),
            3 => Ok(Self::DevicePrivateKey),
            _ => Err(VaultError::Corrupt),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord)]
pub struct SecretRecordKey {
    pub kind: SecretKind,
    pub scope_id: String,
}

impl SecretRecordKey {
    pub fn new(kind: SecretKind, scope_id: impl Into<String>) -> Result<Self, VaultError> {
        let scope_id = scope_id.into();
        let trimmed = scope_id.trim();
        if trimmed.is_empty() || trimmed.len() > 512 || trimmed.as_bytes().contains(&0) {
            return Err(VaultError::InvalidKey);
        }
        Ok(Self { kind, scope_id })
    }
}

/// Secret bytes intentionally do not implement Debug or Display.
pub struct SecretValue(Vec<u8>);

impl SecretValue {
    pub fn new(bytes: impl Into<Vec<u8>>) -> Result<Self, VaultError> {
        let bytes = bytes.into();
        if bytes.is_empty() || bytes.len() > 65_536 {
            return Err(VaultError::EmptySecret);
        }
        Ok(Self(bytes))
    }

    pub fn expose(&self) -> &[u8] {
        &self.0
    }

    pub(crate) fn duplicate(&self) -> Self {
        Self(self.0.clone())
    }
}

impl Drop for SecretValue {
    fn drop(&mut self) {
        self.0.fill(0);
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum VaultMode {
    SessionOnly,
    SecretService,
    Passphrase,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum VaultState {
    Ready,
    ProviderUnavailable,
    ProviderLocked,
    ProviderCorrupt,
    PassphraseRequired,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct VaultStatus {
    pub mode: VaultMode,
    pub state: VaultState,
    pub durable: bool,
    pub passphrase_fallback_available: bool,
}

impl VaultStatus {
    pub fn session_only(state: VaultState) -> Self {
        Self {
            mode: VaultMode::SessionOnly,
            state,
            durable: false,
            passphrase_fallback_available: true,
        }
    }

    pub fn durable(mode: VaultMode) -> Self {
        debug_assert!(matches!(mode, VaultMode::SecretService | VaultMode::Passphrase));
        Self {
            mode,
            state: VaultState::Ready,
            durable: true,
            passphrase_fallback_available: true,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum VaultError {
    InvalidKey,
    EmptySecret,
    Unavailable,
    Locked,
    Corrupt,
    AuthenticationFailed,
    Io,
    Crypto,
    Poisoned,
}

pub trait SecretVault: Send + Sync {
    fn status(&self) -> VaultStatus;
    fn put(&self, key: SecretRecordKey, value: SecretValue) -> Result<(), VaultError>;
    fn get(&self, key: &SecretRecordKey) -> Result<Option<SecretValue>, VaultError>;
    fn delete(&self, key: &SecretRecordKey) -> Result<(), VaultError>;
}

pub struct SessionVault {
    values: Mutex<BTreeMap<SecretRecordKey, SecretValue>>,
    state: VaultState,
}

impl Default for SessionVault {
    fn default() -> Self {
        Self::with_state(VaultState::Ready)
    }
}

impl SessionVault {
    pub fn with_state(state: VaultState) -> Self {
        Self {
            values: Mutex::new(BTreeMap::new()),
            state,
        }
    }

    fn lock(&self) -> Result<MutexGuard<'_, BTreeMap<SecretRecordKey, SecretValue>>, VaultError> {
        self.values.lock().map_err(|_| VaultError::Poisoned)
    }
}

impl SecretVault for SessionVault {
    fn status(&self) -> VaultStatus {
        VaultStatus::session_only(self.state)
    }

    fn put(&self, key: SecretRecordKey, value: SecretValue) -> Result<(), VaultError> {
        self.lock()?.insert(key, value);
        Ok(())
    }

    fn get(&self, key: &SecretRecordKey) -> Result<Option<SecretValue>, VaultError> {
        Ok(self.lock()?.get(key).map(SecretValue::duplicate))
    }

    fn delete(&self, key: &SecretRecordKey) -> Result<(), VaultError> {
        self.lock()?.remove(key);
        Ok(())
    }
}

pub struct VaultService {
    provider: Box<dyn SecretVault>,
}

impl Default for VaultService {
    fn default() -> Self {
        Self::session_only()
    }
}

impl VaultService {
    pub fn session_only() -> Self {
        Self::session_only_with_state(VaultState::Ready)
    }

    pub fn session_only_with_state(state: VaultState) -> Self {
        Self {
            provider: Box::new(SessionVault::with_state(state)),
        }
    }

    pub fn from_provider(provider: impl SecretVault + 'static) -> Self {
        Self {
            provider: Box::new(provider),
        }
    }

    pub fn status(&self) -> VaultStatus {
        self.provider.status()
    }

    pub fn provider(&self) -> &dyn SecretVault {
        self.provider.as_ref()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn session_vault_round_trip_is_memory_only_and_typed() {
        let vault = SessionVault::default();
        let key = SecretRecordKey::new(SecretKind::BoardCapability, "board-a").unwrap();
        vault.put(key.clone(), SecretValue::new(b"canary-secret".to_vec()).unwrap()).unwrap();
        let value = vault.get(&key).unwrap().unwrap();
        assert_eq!(value.expose(), b"canary-secret");
        vault.delete(&key).unwrap();
        assert!(vault.get(&key).unwrap().is_none());
        assert_eq!(vault.status().mode, VaultMode::SessionOnly);
        assert!(!vault.status().durable);
    }

    #[test]
    fn empty_secret_or_scope_is_rejected() {
        assert_eq!(
            SecretRecordKey::new(SecretKind::RefreshToken, " "),
            Err(VaultError::InvalidKey)
        );
        assert!(matches!(SecretValue::new(Vec::<u8>::new()), Err(VaultError::EmptySecret)));
    }
}
