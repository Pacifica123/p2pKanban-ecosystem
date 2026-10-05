use std::net::{IpAddr, SocketAddr};

use base64::{engine::general_purpose::STANDARD, Engine as _};
use config::{Config, ConfigError, Environment, File};
use serde::Deserialize;

#[derive(Debug, Clone, Deserialize)]
pub struct Settings {
    pub app: AppSettings,
    pub database: DatabaseSettings,
    pub http: HttpSettings,
    pub auth: AuthSettings,
    #[serde(default)]
    pub transports: TransportSettings,
}

#[derive(Debug, Clone, Deserialize)]
pub struct AppSettings {
    pub name: String,
    pub env: String,
    pub host: IpAddr,
    pub port: u16,
    pub log_format: LogFormat,
}

#[derive(Debug, Clone, Deserialize)]
pub struct DatabaseSettings {
    pub url: String,
    pub max_connections: u32,
    pub min_connections: u32,
    pub connect_timeout_secs: u64,
}

#[derive(Debug, Clone, Deserialize)]
pub struct HttpSettings {
    pub body_limit_mb: usize,
    pub cors_allowed_origins: Vec<String>,
}

#[derive(Debug, Clone, Deserialize)]
pub struct AuthSettings {
    pub jwt_secret: String,
    #[serde(default)]
    pub previous_jwt_secrets: Vec<String>,
    pub access_token_ttl_minutes: i64,
    pub refresh_token_ttl_days: i64,
    pub public_signup_enabled: bool,
    #[serde(default = "default_refresh_cookie_name")]
    pub refresh_cookie_name: String,
    #[serde(default = "default_device_cookie_name")]
    pub device_cookie_name: String,
    #[serde(default = "default_cookie_same_site")]
    pub cookie_same_site: CookieSameSite,
    #[serde(default)]
    pub cookie_secure: bool,
    #[serde(default)]
    pub enable_dev_header_auth: bool,
    #[serde(default = "default_auth_rate_limit_window_secs")]
    pub auth_rate_limit_window_secs: u64,
    #[serde(default = "default_auth_rate_limit_max_attempts")]
    pub auth_rate_limit_max_attempts: u32,
    #[serde(default = "default_sensitive_rate_limit_window_secs")]
    pub sensitive_rate_limit_window_secs: u64,
    #[serde(default = "default_sensitive_rate_limit_max_attempts")]
    pub sensitive_rate_limit_max_attempts: u32,
}

#[derive(Debug, Clone, Deserialize)]
pub struct TransportSettings {
    #[serde(default = "default_transport_poll_interval_ms")]
    pub worker_poll_interval_ms: u64,
    #[serde(default = "default_transport_batch_size")]
    pub batch_size: i64,
    #[serde(default = "default_transport_max_attempts")]
    pub max_attempts: i32,
    #[serde(default)]
    pub nostr: NostrTransportSettings,
    #[serde(default)]
    pub iroh: IrohTransportSettings,
}

#[derive(Debug, Clone, Deserialize)]
pub struct NostrTransportSettings {
    #[serde(default)]
    pub enabled: bool,
    #[serde(default)]
    pub relays: Vec<String>,
    #[serde(default)]
    pub secret_key: Option<String>,
    #[serde(default)]
    pub master_key_base64: Option<String>,
    #[serde(default = "default_nostr_event_kind")]
    pub event_kind: u16,
    #[serde(default = "default_nostr_fetch_timeout_secs")]
    pub fetch_timeout_secs: u64,
    #[serde(default = "default_nostr_min_relay_acks")]
    pub min_relay_acks: usize,
    #[serde(default)]
    pub backfill_on_start: bool,
}

#[derive(Debug, Clone, Deserialize, Default)]
pub struct IrohTransportSettings {
    #[serde(default)]
    pub enabled: bool,
    #[serde(default)]
    pub peers: Vec<String>,
}

impl Default for TransportSettings {
    fn default() -> Self {
        Self {
            worker_poll_interval_ms: default_transport_poll_interval_ms(),
            batch_size: default_transport_batch_size(),
            max_attempts: default_transport_max_attempts(),
            nostr: NostrTransportSettings::default(),
            iroh: IrohTransportSettings::default(),
        }
    }
}

impl Default for NostrTransportSettings {
    fn default() -> Self {
        Self {
            enabled: false,
            relays: Vec::new(),
            secret_key: None,
            master_key_base64: None,
            event_kind: default_nostr_event_kind(),
            fetch_timeout_secs: default_nostr_fetch_timeout_secs(),
            min_relay_acks: default_nostr_min_relay_acks(),
            backfill_on_start: false,
        }
    }
}

#[derive(Debug, Clone, Copy, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum LogFormat {
    Pretty,
    Json,
}

#[derive(Debug, Clone, Copy, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum CookieSameSite {
    Lax,
    Strict,
    None,
}

fn default_refresh_cookie_name() -> String {
    "p2p_planner_refresh".to_string()
}

fn default_device_cookie_name() -> String {
    "p2p_planner_device".to_string()
}

fn default_cookie_same_site() -> CookieSameSite {
    CookieSameSite::Lax
}

fn default_auth_rate_limit_window_secs() -> u64 {
    60
}

fn default_auth_rate_limit_max_attempts() -> u32 {
    20
}

fn default_sensitive_rate_limit_window_secs() -> u64 {
    60
}

fn default_sensitive_rate_limit_max_attempts() -> u32 {
    60
}

fn default_transport_poll_interval_ms() -> u64 {
    1_000
}

fn default_transport_batch_size() -> i64 {
    50
}

fn default_transport_max_attempts() -> i32 {
    12
}

fn default_nostr_event_kind() -> u16 {
    1_978
}

fn default_nostr_fetch_timeout_secs() -> u64 {
    10
}

fn default_nostr_min_relay_acks() -> usize {
    3
}

impl CookieSameSite {
    pub fn as_set_cookie_value(self) -> &'static str {
        match self {
            Self::Lax => "Lax",
            Self::Strict => "Strict",
            Self::None => "None",
        }
    }
}

fn normalized_env(env: &str) -> String {
    env.trim().to_ascii_lowercase().replace('-', "_")
}

fn is_local_dev_env(env: &str) -> bool {
    matches!(
        normalized_env(env).as_str(),
        "local" | "dev" | "development" | "test" | "testing"
    )
}

fn is_hardened_env(env: &str) -> bool {
    matches!(
        normalized_env(env).as_str(),
        "beta" | "preview" | "staging" | "stage" | "self_host" | "selfhost" | "prod" | "production"
    )
}

fn looks_like_placeholder_secret(value: &str) -> bool {
    let normalized = value.trim().to_ascii_lowercase();
    normalized.is_empty()
        || normalized.contains("change-me")
        || normalized.contains("changeme")
        || normalized.contains("default")
        || normalized == "secret"
        || normalized == "dev-secret"
        || normalized == "local-secret"
}

impl Settings {
    pub fn load() -> Result<Self, ConfigError> {
        dotenvy::dotenv().ok();

        let settings: Self = Config::builder()
            .add_source(File::with_name("config/default").required(false))
            .add_source(
                Environment::default()
                    .separator("__")
                    .list_separator(",")
                    .with_list_parse_key("http.cors_allowed_origins")
                    .with_list_parse_key("auth.previous_jwt_secrets")
                    .with_list_parse_key("transports.nostr.relays")
                    .with_list_parse_key("transports.iroh.peers")
                    .try_parsing(true),
            )
            .build()?
            .try_deserialize()?;

        settings.validate()?;
        Ok(settings)
    }

    fn validate(&self) -> Result<(), ConfigError> {
        let local_dev_env = is_local_dev_env(&self.app.env);
        let hardened_env = is_hardened_env(&self.app.env);

        if self.auth.enable_dev_header_auth && !local_dev_env {
            return Err(ConfigError::Message(
                "AUTH__ENABLE_DEV_HEADER_AUTH may only be enabled for local/dev/test profiles"
                    .to_string(),
            ));
        }

        if matches!(self.auth.cookie_same_site, CookieSameSite::None) && !self.auth.cookie_secure {
            return Err(ConfigError::Message(
                "AUTH__COOKIE_SAME_SITE=none requires AUTH__COOKIE_SECURE=true".to_string(),
            ));
        }

        if hardened_env {
            if self.http.cors_allowed_origins.is_empty() {
                return Err(ConfigError::Message(
                    "HTTP__CORS_ALLOWED_ORIGINS must be explicit for beta/self-host/production profiles".to_string(),
                ));
            }

            if self
                .http
                .cors_allowed_origins
                .iter()
                .any(|origin| origin.trim() == "*")
            {
                return Err(ConfigError::Message(
                    "HTTP__CORS_ALLOWED_ORIGINS must not contain wildcard '*' for beta/self-host/production profiles".to_string(),
                ));
            }

            if !self.auth.cookie_secure {
                return Err(ConfigError::Message(
                    "AUTH__COOKIE_SECURE=true is required for beta/self-host/production profiles"
                        .to_string(),
                ));
            }

            if looks_like_placeholder_secret(&self.auth.jwt_secret)
                || self.auth.jwt_secret.len() < 32
            {
                return Err(ConfigError::Message(
                    "AUTH__JWT_SECRET must be a non-default secret with at least 32 characters for beta/self-host/production profiles".to_string(),
                ));
            }
        }

        if self.transports.worker_poll_interval_ms < 100 {
            return Err(ConfigError::Message(
                "TRANSPORTS__WORKER_POLL_INTERVAL_MS must be at least 100".to_string(),
            ));
        }
        if !(1..=500).contains(&self.transports.batch_size) {
            return Err(ConfigError::Message(
                "TRANSPORTS__BATCH_SIZE must be between 1 and 500".to_string(),
            ));
        }
        if !(1..=100).contains(&self.transports.max_attempts) {
            return Err(ConfigError::Message(
                "TRANSPORTS__MAX_ATTEMPTS must be between 1 and 100".to_string(),
            ));
        }

        if self.transports.nostr.enabled {
            if !cfg!(feature = "nostr-shadow") {
                return Err(ConfigError::Message(
                    "Nostr shadow transport is enabled in config but backend was built without the nostr-shadow feature"
                        .to_string(),
                ));
            }
            if self.transports.nostr.relays.len() < 3 {
                return Err(ConfigError::Message(
                    "TRANSPORTS__NOSTR__RELAYS must contain at least three relays in shadow mode"
                        .to_string(),
                ));
            }
            if self.transports.nostr.min_relay_acks < 2
                || self.transports.nostr.min_relay_acks > self.transports.nostr.relays.len()
            {
                return Err(ConfigError::Message(
                    "TRANSPORTS__NOSTR__MIN_RELAY_ACKS must be at least 2 and not exceed the configured relay count"
                        .to_string(),
                ));
            }
            if self
                .transports
                .nostr
                .relays
                .iter()
                .any(|relay| !(relay.starts_with("wss://") || relay.starts_with("ws://")))
            {
                return Err(ConfigError::Message(
                    "Every TRANSPORTS__NOSTR__RELAYS entry must use ws:// or wss://".to_string(),
                ));
            }
            let secret_key = self
                .transports
                .nostr
                .secret_key
                .as_deref()
                .unwrap_or_default()
                .trim();
            if secret_key.is_empty() || looks_like_placeholder_secret(secret_key) {
                return Err(ConfigError::Message(
                    "TRANSPORTS__NOSTR__SECRET_KEY must contain a real Nostr secret key"
                        .to_string(),
                ));
            }
            self.transports.nostr.master_key()?;
        }

        Ok(())
    }

    pub fn dev_header_auth_allowed(&self) -> bool {
        self.auth.enable_dev_header_auth && is_local_dev_env(&self.app.env)
    }

    pub fn socket_addr(&self) -> SocketAddr {
        SocketAddr::new(self.app.host, self.app.port)
    }
}

impl NostrTransportSettings {
    pub fn master_key(&self) -> Result<Vec<u8>, ConfigError> {
        let encoded = self.master_key_base64.as_deref().unwrap_or_default().trim();
        if encoded.is_empty() || looks_like_placeholder_secret(encoded) {
            return Err(ConfigError::Message(
                "TRANSPORTS__NOSTR__MASTER_KEY_BASE64 must contain a real 32-byte key".to_string(),
            ));
        }
        let decoded = STANDARD.decode(encoded).map_err(|_| {
            ConfigError::Message(
                "TRANSPORTS__NOSTR__MASTER_KEY_BASE64 must be valid standard base64".to_string(),
            )
        })?;
        if decoded.len() != 32 {
            return Err(ConfigError::Message(
                "TRANSPORTS__NOSTR__MASTER_KEY_BASE64 must decode to exactly 32 bytes".to_string(),
            ));
        }
        Ok(decoded)
    }
}
