use crate::domain::system::ServiceIdentity;

/// Application-owned read model. It intentionally contains no IPC/HTTP shape.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct HealthView {
    pub status: &'static str,
    pub service: &'static str,
    pub version: &'static str,
    pub environment: &'static str,
}

pub struct SystemService {
    identity: ServiceIdentity,
}

impl SystemService {
    pub const fn desktop(service: &'static str, version: &'static str) -> Self {
        Self {
            identity: ServiceIdentity::desktop(service, version),
        }
    }

    pub fn health(&self) -> HealthView {
        HealthView {
            status: "ok",
            service: self.identity.service(),
            version: self.identity.version(),
            environment: self.identity.runtime().as_str(),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::SystemService;

    #[test]
    fn health_read_model_is_stable_without_transport_runtime() {
        let service = SystemService::desktop("native-test", "9.8.7");
        let view = service.health();

        assert_eq!(view.status, "ok");
        assert_eq!(view.service, "native-test");
        assert_eq!(view.version, "9.8.7");
        assert_eq!(view.environment, "desktop");
    }
}
