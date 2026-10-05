use std::{collections::VecDeque, sync::Mutex};

use crate::domain::integration::{DeepLinkIntent, IntegrationCapabilities};

pub trait IntegrationAdapter: Send + Sync {
    fn detect(&self) -> IntegrationCapabilities;
}

pub struct IntegrationService {
    adapter: Box<dyn IntegrationAdapter>,
    pending_deep_links: Mutex<VecDeque<DeepLinkIntent>>,
}

impl IntegrationService {
    pub fn new(adapter: Box<dyn IntegrationAdapter>) -> Self {
        Self {
            adapter,
            pending_deep_links: Mutex::new(VecDeque::new()),
        }
    }

    pub fn capabilities(&self) -> IntegrationCapabilities {
        self.adapter.detect()
    }

    pub fn enqueue_deep_link(&self, intent: DeepLinkIntent) {
        let mut pending = self.pending_deep_links.lock().unwrap_or_else(|poisoned| poisoned.into_inner());
        if pending.len() >= 32 {
            pending.pop_front();
        }
        pending.push_back(intent);
    }

    pub fn take_deep_links(&self) -> Vec<DeepLinkIntent> {
        let mut pending = self.pending_deep_links.lock().unwrap_or_else(|poisoned| poisoned.into_inner());
        pending.drain(..).collect()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::domain::integration::{
        parse_deep_link, CapabilityState, IntegrationCapabilities, SessionKind,
    };

    struct FakeAdapter;

    impl IntegrationAdapter for FakeAdapter {
        fn detect(&self) -> IntegrationCapabilities {
            IntegrationCapabilities {
                session: SessionKind::Wayland,
                desktop: Some("test-desktop".into()),
                session_bus: CapabilityState::Available,
                notifications: CapabilityState::Unavailable,
                status_notifier: CapabilityState::Unavailable,
                portal: CapabilityState::Available,
                runtime_activation: CapabilityState::Available,
            }
        }
    }

    #[test]
    fn a13_integration_capabilities_degrade_without_becoming_requirements() {
        let service = IntegrationService::new(Box::new(FakeAdapter));
        let view = service.capabilities();
        assert_eq!(view.session, SessionKind::Wayland);
        assert_eq!(view.notifications, CapabilityState::Unavailable);
        assert_eq!(view.status_notifier, CapabilityState::Unavailable);
        assert_eq!(view.portal, CapabilityState::Available);
    }

    #[test]
    fn a13_deep_link_queue_is_bounded_and_drain_only() {
        let service = IntegrationService::new(Box::new(FakeAdapter));
        for _ in 0..40 {
            service.enqueue_deep_link(parse_deep_link("p2pkanban://activate").unwrap());
        }
        assert_eq!(service.take_deep_links().len(), 32);
        assert!(service.take_deep_links().is_empty());
    }
}
