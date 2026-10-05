use std::{
    sync::{Arc, Mutex},
    time::{SystemTime, UNIX_EPOCH},
};

use k256::{elliptic_curve::Generate as _, schnorr::SigningKey};

use crate::{
    application::{
        import::{BoardCapabilityMaterial, DeviceIdentityMaterial, ImportService},
        vault::VaultService,
    },
    domain::{
        import::parse_portable_bundle_v1,
        lan_bridge::{
            encode_capability_token, LanBridgeLifecycle, LanBridgeStartRequest, LanBridgeStatus,
            LanBridgeValidationError, LanProvisionPackageV1, LAN_BRIDGE_TOKEN_BYTES,
        },
    },
};

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum LanBridgeRuntimeError {
    BindUnavailable,
    Io,
    UnsupportedAddress,
    AlreadyStopped,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum LanBridgeServiceError {
    InvalidRequest(LanBridgeValidationError),
    AlreadyRunning,
    Runtime(LanBridgeRuntimeError),
    Randomness,
    VaultNotDurable,
    InvalidPackage,
    ImportFailed,
    Poisoned,
}

impl From<LanBridgeRuntimeError> for LanBridgeServiceError {
    fn from(value: LanBridgeRuntimeError) -> Self {
        Self::Runtime(value)
    }
}

pub trait LanBridgeHandle: Send {
    fn status(&self) -> LanBridgeStatus;
    fn stop(&self) -> Result<(), LanBridgeRuntimeError>;
}

pub type LanBridgePayloadHandler = Arc<dyn Fn(&[u8]) -> Result<String, String> + Send + Sync + 'static>;

pub trait LanBridgeRuntime: Send + Sync {
    fn available_bind_addresses(&self) -> Vec<String>;
    fn start(
        &self,
        request: LanBridgeStartRequest,
        token: [u8; LAN_BRIDGE_TOKEN_BYTES],
        handler: LanBridgePayloadHandler,
    ) -> Result<Box<dyn LanBridgeHandle>, LanBridgeRuntimeError>;
}

pub struct LanBridgeStartView {
    pub status: LanBridgeStatus,
    pub capability: String,
    pub device_public_key: String,
}

pub struct LanBridgeService {
    runtime: Box<dyn LanBridgeRuntime>,
    import: Arc<ImportService>,
    vault: Arc<VaultService>,
    active: Mutex<Option<Box<dyn LanBridgeHandle>>>,
}

impl LanBridgeService {
    pub fn new(
        runtime: Box<dyn LanBridgeRuntime>,
        import: Arc<ImportService>,
        vault: Arc<VaultService>,
    ) -> Self {
        Self {
            runtime,
            import,
            vault,
            active: Mutex::new(None),
        }
    }

    pub fn available_bind_addresses(&self) -> Vec<String> {
        self.runtime
            .available_bind_addresses()
            .into_iter()
            .map(|address| address.to_string())
            .collect()
    }

    pub fn start(
        &self,
        bind_address: &str,
        ttl_secs: u64,
    ) -> Result<LanBridgeStartView, LanBridgeServiceError> {
        if !self.vault.status().durable {
            return Err(LanBridgeServiceError::VaultNotDurable);
        }
        let request = LanBridgeStartRequest::validated(bind_address, ttl_secs)
            .map_err(LanBridgeServiceError::InvalidRequest)?;
        let allowed = self.runtime.available_bind_addresses();
        if !allowed.contains(&request.bind_address) {
            return Err(LanBridgeServiceError::InvalidRequest(
                LanBridgeValidationError::InvalidBindAddress,
            ));
        }

        let mut guard = self.active.lock().map_err(|_| LanBridgeServiceError::Poisoned)?;
        if guard
            .as_ref()
            .is_some_and(|active| active.status().lifecycle == LanBridgeLifecycle::Listening)
        {
            return Err(LanBridgeServiceError::AlreadyRunning);
        }

        let signing_key = SigningKey::generate();
        let device_public_key = signing_key
            .verifying_key()
            .to_bytes()
            .iter()
            .map(|byte| format!("{byte:02x}"))
            .collect::<String>();
        let device_private_key = signing_key.to_bytes().to_vec();
        drop(signing_key);

        let mut token = [0_u8; LAN_BRIDGE_TOKEN_BYTES];
        getrandom::fill(&mut token).map_err(|_| LanBridgeServiceError::Randomness)?;
        let capability = encode_capability_token(&token);
        let handler = self.provision_handler(device_public_key.clone(), device_private_key);
        let started = self.runtime.start(request, token, handler);
        token.fill(0);
        let handle = started?;
        let status = handle.status();
        *guard = Some(handle);
        Ok(LanBridgeStartView { status, capability, device_public_key })
    }

    pub fn status(&self) -> Result<LanBridgeStatus, LanBridgeServiceError> {
        let guard = self.active.lock().map_err(|_| LanBridgeServiceError::Poisoned)?;
        Ok(guard.as_ref().map(|handle| handle.status()).unwrap_or_default())
    }

    pub fn stop(&self) -> Result<LanBridgeStatus, LanBridgeServiceError> {
        let mut guard = self.active.lock().map_err(|_| LanBridgeServiceError::Poisoned)?;
        if let Some(handle) = guard.as_ref() {
            let status = handle.status();
            if status.lifecycle == LanBridgeLifecycle::Listening {
                handle.stop()?;
            }
        }
        let status = guard
            .as_ref()
            .map(|handle| handle.status())
            .unwrap_or_default();
        *guard = None;
        Ok(status)
    }

    fn provision_handler(&self, device_public_key: String, device_private_key: Vec<u8>) -> LanBridgePayloadHandler {
        let import = Arc::clone(&self.import);
        let vault = Arc::clone(&self.vault);
        let private_key = Arc::new(Mutex::new(Some(device_private_key)));
        Arc::new(move |plaintext| {
            if !vault.status().durable {
                return Err("vault-not-durable".to_owned());
            }
            let package = LanProvisionPackageV1::parse(plaintext)
                .map_err(|_| "invalid-provision-package".to_owned())?;
            let grant_json = serde_json::to_string(&package.grant)
                .map_err(|_| "invalid-device-link-grant".to_owned())?;
            let bundle_json = serde_json::to_string(&package.portable_bundle)
                .map_err(|_| "invalid-portable-bundle".to_owned())?;
            let plan = parse_portable_bundle_v1(&bundle_json)
                .map_err(|_| "invalid-portable-bundle".to_owned())?;
            let board_key = package
                .decode_board_key()
                .map_err(|_| "invalid-board-capability".to_owned())?;
            let private_key = private_key
                .lock()
                .map_err(|_| "device-identity-unavailable".to_owned())?
                .take()
                .ok_or_else(|| "device-identity-already-consumed".to_owned())?;
            let identity = DeviceIdentityMaterial::new(device_public_key.clone(), private_key)
                .map_err(|_| "invalid-device-identity".to_owned())?;
            let capability = BoardCapabilityMaterial::new(package.board_id, board_key)
                .map_err(|_| "invalid-board-capability".to_owned())?;
            let now_unix = SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .map_err(|_| "invalid-system-clock".to_owned())?
                .as_secs() as i64;
            let report = import
                .provision_authenticated_device_link(
                    &grant_json,
                    now_unix,
                    plan,
                    identity,
                    capability,
                    vault.as_ref(),
                )
                .map_err(|_| "device-link-provisioning-failed".to_owned())?;
            Ok(serde_json::json!({
                "status": "accepted",
                "source": report.source_kind.stable_name(),
                "workspaces": report.workspaces,
                "boards": report.boards,
                "cards": report.cards,
                "tombstones": report.tombstones,
            })
            .to_string())
        })
    }
}

#[cfg(test)]
mod tests {
    use std::sync::atomic::{AtomicBool, Ordering};

    use base64::{engine::general_purpose::URL_SAFE_NO_PAD, Engine as _};

    use super::*;
        use crate::{
        application::{
            import::{ImportApplyReport, ImportRepository, ImportRepositoryError},
            vault::{
                SecretRecordKey, SecretValue, SecretVault, SessionVault, VaultError, VaultMode,
                VaultService, VaultStatus,
            },
        },
        domain::import::{ImportPlan, ImportSourceKind},
    };

    struct DurableMemoryVault { inner: SessionVault }
    impl Default for DurableMemoryVault {
        fn default() -> Self { Self { inner: SessionVault::default() } }
    }
    impl SecretVault for DurableMemoryVault {
        fn status(&self) -> VaultStatus { VaultStatus::durable(VaultMode::Passphrase) }
        fn put(&self, key: SecretRecordKey, value: SecretValue) -> Result<(), VaultError> { self.inner.put(key, value) }
        fn get(&self, key: &SecretRecordKey) -> Result<Option<SecretValue>, VaultError> { self.inner.get(key) }
        fn delete(&self, key: &SecretRecordKey) -> Result<(), VaultError> { self.inner.delete(key) }
    }

    struct NoopRepository;
    impl ImportRepository for NoopRepository {
        fn preflight(&self, _plan: &ImportPlan) -> Result<(), ImportRepositoryError> { Ok(()) }
        fn apply_plan(&mut self, _plan: &ImportPlan) -> Result<ImportApplyReport, ImportRepositoryError> {
            Ok(ImportApplyReport { source_kind: ImportSourceKind::DeviceLinkV2, workspaces: 1, boards: 1, cards: 0, tombstones: 0, omissions: vec![] })
        }
    }

    struct FakeHandle { listening: AtomicBool }
    impl LanBridgeHandle for FakeHandle {
        fn status(&self) -> LanBridgeStatus {
            LanBridgeStatus {
                lifecycle: if self.listening.load(Ordering::SeqCst) { LanBridgeLifecycle::Listening } else { LanBridgeLifecycle::Stopped },
                bind_address: Some("192.168.1.2:55000".into()),
                endpoint: Some("http://192.168.1.2:55000/v1/p2pkanban/pair".into()),
                expires_at_unix: Some(2_000_000_000),
                attempts: 0,
                last_result: None,
            }
        }
        fn stop(&self) -> Result<(), LanBridgeRuntimeError> { self.listening.store(false, Ordering::SeqCst); Ok(()) }
    }

    struct FakeRuntime;
    impl LanBridgeRuntime for FakeRuntime {
        fn available_bind_addresses(&self) -> Vec<String> { vec!["192.168.1.2".to_owned()] }
        fn start(&self, _request: LanBridgeStartRequest, _token: [u8; LAN_BRIDGE_TOKEN_BYTES], _handler: LanBridgePayloadHandler) -> Result<Box<dyn LanBridgeHandle>, LanBridgeRuntimeError> {
            Ok(Box::new(FakeHandle { listening: AtomicBool::new(true) }))
        }
    }

    #[test]
    fn a14_bridge_is_explicit_off_by_default_and_rejects_session_only_vault() {
        let import = Arc::new(ImportService::new(Box::new(NoopRepository)));
        let vault = Arc::new(VaultService::from_provider(SessionVault::default()));
        let service = LanBridgeService::new(Box::new(FakeRuntime), import, vault);
        assert_eq!(service.status().unwrap().lifecycle, LanBridgeLifecycle::Stopped);
        assert!(matches!(
            service.start("192.168.1.2", 300),
            Err(LanBridgeServiceError::VaultNotDurable)
        ));
    }

    #[test]
    fn a14_bind_address_must_come_from_detected_adapter_list() {
        let request = LanBridgeStartRequest::validated("192.168.1.2", 300).unwrap();
        assert_eq!(request.bind_address, "192.168.1.2");
        assert!(LanBridgeStartRequest::validated("", 300).is_err());
    }

    #[test]
    fn a14_start_generates_fresh_native_identity_and_returns_no_private_key() {
        let import = Arc::new(ImportService::new(Box::new(NoopRepository)));
        let vault = Arc::new(VaultService::from_provider(DurableMemoryVault::default()));
        let service = LanBridgeService::new(Box::new(FakeRuntime), import, vault);
        let started = service.start("192.168.1.2", 300).unwrap();
        assert_eq!(started.device_public_key.len(), 64);
        assert!(started.device_public_key.bytes().all(|byte| byte.is_ascii_hexdigit()));
        assert_eq!(URL_SAFE_NO_PAD.decode(&started.capability).unwrap().len(), 32);
        assert_eq!(started.status.lifecycle, LanBridgeLifecycle::Listening);
        service.stop().unwrap();
    }

    #[test]
    fn a14_capability_encoding_is_256_bit_urlsafe_material() {
        let raw = [0xA5_u8; LAN_BRIDGE_TOKEN_BYTES];
        let encoded = encode_capability_token(&raw);
        assert_eq!(URL_SAFE_NO_PAD.decode(encoded).unwrap(), raw);
    }
}
