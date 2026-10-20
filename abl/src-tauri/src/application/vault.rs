use std::{
    collections::BTreeMap,
    sync::{Arc, Mutex, MutexGuard, RwLock},
};

#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord)]
pub enum SecretKind {
    RefreshToken,
    BoardCapability,
    DevicePrivateKey,
}

impl SecretKind {
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
    /// `passphrase_fallback_available` starts false: only `VaultService` knows whether a
    /// passphrase provider is wired and whether this profile may use it.
    pub fn session_only(state: VaultState) -> Self {
        Self {
            mode: VaultMode::SessionOnly,
            state,
            durable: false,
            passphrase_fallback_available: false,
        }
    }

    pub fn durable(mode: VaultMode) -> Self {
        debug_assert!(matches!(mode, VaultMode::SecretService | VaultMode::Passphrase));
        Self {
            mode,
            state: VaultState::Ready,
            durable: true,
            passphrase_fallback_available: false,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum VaultError {
    InvalidKey,
    EmptySecret,
    /// The passphrase is outside the accepted length (12..=1024 bytes).
    WeakPassphrase,
    /// The requested passphrase transition does not apply to the current vault state.
    NotApplicable,
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

/// Opens the explicit passphrase provider (ADR-004). Implemented by the
/// platform layer; the application only decides when a transition is allowed.
pub trait PassphraseVaultProvider: Send + Sync {
    /// True when no passphrase wrap and no provider-encrypted vault exist yet, so a new
    /// passphrase vault cannot shadow secrets sealed by another provider.
    fn can_create(&self) -> bool;
    fn create(&self, passphrase: &[u8]) -> Result<Box<dyn SecretVault>, VaultError>;
    fn unlock(&self, passphrase: &[u8]) -> Result<Box<dyn SecretVault>, VaultError>;
}

pub struct VaultService {
    provider: RwLock<Arc<dyn SecretVault>>,
    passphrase: Option<Box<dyn PassphraseVaultProvider>>,
    transition: Mutex<()>,
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
        Self::from_provider(SessionVault::with_state(state))
    }

    pub fn from_provider(provider: impl SecretVault + 'static) -> Self {
        Self {
            provider: RwLock::new(Arc::new(provider)),
            passphrase: None,
            transition: Mutex::new(()),
        }
    }

    pub fn with_passphrase_provider(mut self, provider: Box<dyn PassphraseVaultProvider>) -> Self {
        self.passphrase = Some(provider);
        self
    }

    pub fn status(&self) -> VaultStatus {
        let mut status = self.current().status();
        status.passphrase_fallback_available = self.passphrase_applicable(status);
        status
    }

    pub fn provider(&self) -> Arc<dyn SecretVault> {
        self.current()
    }

    /// First-time setup on a host without a usable Secret Service.
    pub fn set_up_passphrase(&self, passphrase: &[u8]) -> Result<VaultStatus, VaultError> {
        self.transition(VaultState::ProviderUnavailable, passphrase, |provider, value| provider.create(value))
    }

    /// Every launch of a profile whose vault root is wrapped by a passphrase.
    pub fn unlock_passphrase(&self, passphrase: &[u8]) -> Result<VaultStatus, VaultError> {
        self.transition(VaultState::PassphraseRequired, passphrase, |provider, value| provider.unlock(value))
    }

    fn transition(
        &self,
        expected: VaultState,
        passphrase: &[u8],
        open: impl FnOnce(&dyn PassphraseVaultProvider, &[u8]) -> Result<Box<dyn SecretVault>, VaultError>,
    ) -> Result<VaultStatus, VaultError> {
        let _guard = self.transition.lock().map_err(|_| VaultError::Poisoned)?;
        let status = self.current().status();
        if status.state != expected || !self.passphrase_applicable(status) {
            return Err(VaultError::NotApplicable);
        }
        if passphrase.len() < 12 || passphrase.len() > 1024 {
            return Err(VaultError::WeakPassphrase);
        }
        let provider = self.passphrase.as_deref().ok_or(VaultError::NotApplicable)?;
        let opened: Arc<dyn SecretVault> = Arc::from(open(provider, passphrase)?);
        *self.provider.write().map_err(|_| VaultError::Poisoned)? = opened;
        Ok(self.status())
    }

    fn passphrase_applicable(&self, status: VaultStatus) -> bool {
        let Some(provider) = self.passphrase.as_deref() else {
            return false;
        };
        match (status.mode, status.state) {
            (VaultMode::SessionOnly, VaultState::PassphraseRequired) => true,
            (VaultMode::SessionOnly, VaultState::ProviderUnavailable) => provider.can_create(),
            _ => false,
        }
    }

    fn current(&self) -> Arc<dyn SecretVault> {
        match self.provider.read() {
            Ok(guard) => Arc::clone(&guard),
            Err(poisoned) => Arc::clone(&poisoned.into_inner()),
        }
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

    struct FakePassphraseProvider {
        can_create: bool,
        accepted: &'static [u8],
    }

    impl PassphraseVaultProvider for FakePassphraseProvider {
        fn can_create(&self) -> bool {
            self.can_create
        }

        fn create(&self, _passphrase: &[u8]) -> Result<Box<dyn SecretVault>, VaultError> {
            Ok(Box::new(DurableFake))
        }

        fn unlock(&self, passphrase: &[u8]) -> Result<Box<dyn SecretVault>, VaultError> {
            if passphrase != self.accepted {
                return Err(VaultError::AuthenticationFailed);
            }
            Ok(Box::new(DurableFake))
        }
    }

    struct DurableFake;

    impl SecretVault for DurableFake {
        fn status(&self) -> VaultStatus {
            VaultStatus::durable(VaultMode::Passphrase)
        }
        fn put(&self, _key: SecretRecordKey, _value: SecretValue) -> Result<(), VaultError> {
            Ok(())
        }
        fn get(&self, _key: &SecretRecordKey) -> Result<Option<SecretValue>, VaultError> {
            Ok(None)
        }
        fn delete(&self, _key: &SecretRecordKey) -> Result<(), VaultError> {
            Ok(())
        }
    }

    fn with_fake(state: VaultState, can_create: bool) -> VaultService {
        VaultService::session_only_with_state(state).with_passphrase_provider(Box::new(
            FakePassphraseProvider { can_create, accepted: b"correct horse battery" },
        ))
    }

    #[test]
    fn passphrase_fallback_is_reported_only_when_it_can_be_used() {
        assert!(!VaultService::session_only_with_state(VaultState::ProviderUnavailable)
            .status()
            .passphrase_fallback_available);
        assert!(with_fake(VaultState::ProviderUnavailable, true).status().passphrase_fallback_available);
        assert!(!with_fake(VaultState::ProviderUnavailable, false).status().passphrase_fallback_available);
        assert!(!with_fake(VaultState::ProviderLocked, true).status().passphrase_fallback_available);
        assert!(!with_fake(VaultState::ProviderCorrupt, true).status().passphrase_fallback_available);
        assert!(with_fake(VaultState::PassphraseRequired, false).status().passphrase_fallback_available);
    }

    #[test]
    fn passphrase_set_up_switches_shared_service_to_durable_provider() {
        let vault = with_fake(VaultState::ProviderUnavailable, true);
        assert_eq!(vault.set_up_passphrase(b"short"), Err(VaultError::WeakPassphrase));
        assert_eq!(vault.unlock_passphrase(b"correct horse battery"), Err(VaultError::NotApplicable));
        let status = vault.set_up_passphrase(b"correct horse battery").unwrap();
        assert_eq!(status.mode, VaultMode::Passphrase);
        assert!(status.durable);
        assert!(!status.passphrase_fallback_available);
        assert!(vault.provider().status().durable);
        assert_eq!(vault.set_up_passphrase(b"correct horse battery"), Err(VaultError::NotApplicable));
    }

    #[test]
    fn passphrase_unlock_keeps_session_only_on_wrong_passphrase() {
        let vault = with_fake(VaultState::PassphraseRequired, false);
        assert_eq!(vault.set_up_passphrase(b"correct horse battery"), Err(VaultError::NotApplicable));
        assert_eq!(
            vault.unlock_passphrase(b"wrong horse battery"),
            Err(VaultError::AuthenticationFailed)
        );
        assert_eq!(vault.status().state, VaultState::PassphraseRequired);
        assert!(!vault.status().durable);
        assert!(vault.unlock_passphrase(b"correct horse battery").unwrap().durable);
    }
}
