use uuid::Uuid;

pub const MAX_DEEP_LINK_BYTES: usize = 512;
pub const DEEP_LINK_ACTIVATION_PREFIX: &[u8] = b"deep-link-v1\t";

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SessionKind {
    Wayland,
    X11,
    Unknown,
}

impl SessionKind {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Wayland => "wayland",
            Self::X11 => "x11",
            Self::Unknown => "unknown",
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CapabilityState {
    Available,
    Unavailable,
}

impl CapabilityState {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Available => "available",
            Self::Unavailable => "unavailable",
        }
    }

    pub const fn from_bool(value: bool) -> Self {
        if value { Self::Available } else { Self::Unavailable }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct IntegrationCapabilities {
    pub session: SessionKind,
    pub desktop: Option<String>,
    pub session_bus: CapabilityState,
    pub notifications: CapabilityState,
    pub status_notifier: CapabilityState,
    pub portal: CapabilityState,
    pub runtime_activation: CapabilityState,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum DeepLinkTarget {
    Activate,
    Workspace(Uuid),
    Board(Uuid),
    Card(Uuid),
}

impl DeepLinkTarget {
    pub const fn kind(&self) -> &'static str {
        match self {
            Self::Activate => "activate",
            Self::Workspace(_) => "workspace",
            Self::Board(_) => "board",
            Self::Card(_) => "card",
        }
    }

    pub fn entity_id(&self) -> Option<String> {
        match self {
            Self::Activate => None,
            Self::Workspace(id) | Self::Board(id) | Self::Card(id) => Some(id.to_string()),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DeepLinkIntent {
    pub canonical: String,
    pub target: DeepLinkTarget,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DeepLinkError {
    Empty,
    TooLong,
    UnsafeCharacters,
    WrongScheme,
    UnsupportedTarget,
    InvalidIdentifier,
}

pub fn parse_deep_link(raw: &str) -> Result<DeepLinkIntent, DeepLinkError> {
    if raw.is_empty() {
        return Err(DeepLinkError::Empty);
    }
    if raw.len() > MAX_DEEP_LINK_BYTES {
        return Err(DeepLinkError::TooLong);
    }
    if raw != raw.trim() || raw.bytes().any(|byte| byte.is_ascii_control()) {
        return Err(DeepLinkError::UnsafeCharacters);
    }
    if raw == "p2pkanban://activate" {
        return Ok(DeepLinkIntent {
            canonical: raw.to_owned(),
            target: DeepLinkTarget::Activate,
        });
    }

    let remainder = raw
        .strip_prefix("p2pkanban://")
        .ok_or(DeepLinkError::WrongScheme)?;
    if remainder.chars().any(|ch| matches!(ch, '?' | '#' | '%' | '\\')) {
        return Err(DeepLinkError::UnsafeCharacters);
    }
    let mut parts = remainder.split('/');
    let kind = parts.next().unwrap_or_default();
    let id_text = parts.next().ok_or(DeepLinkError::UnsupportedTarget)?;
    if parts.next().is_some() || id_text.is_empty() {
        return Err(DeepLinkError::UnsupportedTarget);
    }
    let id = Uuid::parse_str(id_text).map_err(|_| DeepLinkError::InvalidIdentifier)?;
    if id.to_string() != id_text {
        return Err(DeepLinkError::InvalidIdentifier);
    }
    let target = match kind {
        "workspace" => DeepLinkTarget::Workspace(id),
        "board" => DeepLinkTarget::Board(id),
        "card" => DeepLinkTarget::Card(id),
        _ => return Err(DeepLinkError::UnsupportedTarget),
    };
    Ok(DeepLinkIntent {
        canonical: raw.to_owned(),
        target,
    })
}

pub fn encode_deep_link_activation(intent: &DeepLinkIntent) -> Vec<u8> {
    let mut encoded = Vec::with_capacity(DEEP_LINK_ACTIVATION_PREFIX.len() + intent.canonical.len() + 1);
    encoded.extend_from_slice(DEEP_LINK_ACTIVATION_PREFIX);
    encoded.extend_from_slice(intent.canonical.as_bytes());
    encoded.push(b'\n');
    encoded
}

pub fn decode_deep_link_activation(payload: &[u8]) -> Result<DeepLinkIntent, DeepLinkError> {
    if payload.len() > DEEP_LINK_ACTIVATION_PREFIX.len() + MAX_DEEP_LINK_BYTES + 1 {
        return Err(DeepLinkError::TooLong);
    }
    let raw = payload
        .strip_prefix(DEEP_LINK_ACTIVATION_PREFIX)
        .ok_or(DeepLinkError::WrongScheme)?
        .strip_suffix(b"\n")
        .ok_or(DeepLinkError::UnsafeCharacters)?;
    let text = std::str::from_utf8(raw).map_err(|_| DeepLinkError::UnsafeCharacters)?;
    parse_deep_link(text)
}

#[cfg(test)]
mod tests {
    use super::*;

    const ID: &str = "11111111-2222-4333-8444-555555555555";

    #[test]
    fn a13_deep_links_are_narrow_canonical_and_versioned() {
        let activate = parse_deep_link("p2pkanban://activate").unwrap();
        assert_eq!(activate.target.kind(), "activate");

        for kind in ["workspace", "board", "card"] {
            let raw = format!("p2pkanban://{kind}/{ID}");
            let parsed = parse_deep_link(&raw).unwrap();
            assert_eq!(parsed.canonical, raw);
            assert_eq!(parsed.target.kind(), kind);
            assert_eq!(parsed.target.entity_id().as_deref(), Some(ID));
            let encoded = encode_deep_link_activation(&parsed);
            assert_eq!(decode_deep_link_activation(&encoded).unwrap(), parsed);
        }
    }

    #[test]
    fn a13_deep_links_fail_closed_on_untrusted_url_shapes() {
        for raw in [
            "https://example.invalid/",
            "p2pkanban://board/not-a-uuid",
            "p2pkanban://board/11111111-2222-4333-8444-555555555555?x=1",
            "p2pkanban://board/11111111-2222-4333-8444-555555555555/extra",
            " p2pkanban://activate",
            "p2pkanban://unknown/11111111-2222-4333-8444-555555555555",
        ] {
            assert!(parse_deep_link(raw).is_err(), "unexpectedly accepted {raw}");
        }
    }
}
