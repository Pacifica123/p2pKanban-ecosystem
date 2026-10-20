pub mod import;
pub mod integration;
pub mod parity;
pub mod planner;
pub mod recovery;
pub mod repository;
pub mod system;
// Staged (A10): sync-core/roaming layer is complete and covered by tests, but no relay
// transport or coordinator constructs it yet, so the running app neither sends nor
// receives board events. Board card: «abl: живая синхронизация доски по roaming/1».
#[allow(dead_code)]
pub mod sync;
pub mod vault;
pub mod workspace;

use system::SystemService;

/// Root application service registry owned by the native process.
///
/// Platform adapters receive this registry through their own integration
/// mechanism; application/domain code never depends on that mechanism.
pub struct ApplicationServices {
    system: SystemService,
}

impl ApplicationServices {
    pub fn desktop() -> Self {
        Self {
            system: SystemService::desktop(
                "p2pkanban-arch-native",
                env!("CARGO_PKG_VERSION"),
            ),
        }
    }

    pub fn system(&self) -> &SystemService {
        &self.system
    }
}

#[cfg(test)]
mod tests {
    use super::ApplicationServices;

    #[test]
    fn desktop_registry_exposes_application_service_without_platform_adapter() {
        let app = ApplicationServices::desktop();
        let health = app.system().health();

        assert_eq!(health.status, "ok");
        assert_eq!(health.service, "p2pkanban-arch-native");
        assert_eq!(health.environment, "desktop");
        assert_eq!(health.version, env!("CARGO_PKG_VERSION"));
    }
}

pub mod lan_bridge;
