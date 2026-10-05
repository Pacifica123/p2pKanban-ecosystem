/// Runtime kind is a domain-level value, not a Tauri/WebView concept.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RuntimeKind {
    Desktop,
}

impl RuntimeKind {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Desktop => "desktop",
        }
    }
}

/// Stable identity exposed by application read models.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ServiceIdentity {
    service: &'static str,
    version: &'static str,
    runtime: RuntimeKind,
}

impl ServiceIdentity {
    pub const fn desktop(service: &'static str, version: &'static str) -> Self {
        Self {
            service,
            version,
            runtime: RuntimeKind::Desktop,
        }
    }

    pub const fn service(self) -> &'static str {
        self.service
    }

    pub const fn version(self) -> &'static str {
        self.version
    }

    pub const fn runtime(self) -> RuntimeKind {
        self.runtime
    }
}

#[cfg(test)]
mod tests {
    use super::{RuntimeKind, ServiceIdentity};

    #[test]
    fn desktop_identity_is_transport_agnostic() {
        let identity = ServiceIdentity::desktop("p2pkanban-arch-native", "0.1.0");

        assert_eq!(identity.service(), "p2pkanban-arch-native");
        assert_eq!(identity.version(), "0.1.0");
        assert_eq!(identity.runtime(), RuntimeKind::Desktop);
        assert_eq!(identity.runtime().as_str(), "desktop");
    }
}
