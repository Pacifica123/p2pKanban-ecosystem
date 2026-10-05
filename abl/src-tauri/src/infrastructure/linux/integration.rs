use std::env;

use zbus::{blocking::{fdo::DBusProxy, Connection}, names::BusName};

use crate::{
    application::integration::IntegrationAdapter,
    domain::integration::{CapabilityState, IntegrationCapabilities, SessionKind},
};

const NOTIFICATIONS_NAME: &str = "org.freedesktop.Notifications";
const STATUS_NOTIFIER_NAME: &str = "org.kde.StatusNotifierWatcher";
const PORTAL_NAME: &str = "org.freedesktop.portal.Desktop";

#[derive(Debug, Clone, Default)]
pub struct IntegrationEnvironment {
    pub xdg_session_type: Option<String>,
    pub wayland_display: Option<String>,
    pub display: Option<String>,
    pub current_desktop: Option<String>,
    pub session_desktop: Option<String>,
}

impl IntegrationEnvironment {
    pub fn current() -> Self {
        Self {
            xdg_session_type: env::var("XDG_SESSION_TYPE").ok(),
            wayland_display: env::var("WAYLAND_DISPLAY").ok(),
            display: env::var("DISPLAY").ok(),
            current_desktop: env::var("XDG_CURRENT_DESKTOP").ok(),
            session_desktop: env::var("XDG_SESSION_DESKTOP").ok(),
        }
    }

    fn session_kind(&self) -> SessionKind {
        match self.xdg_session_type.as_deref().map(str::to_ascii_lowercase).as_deref() {
            Some("wayland") => SessionKind::Wayland,
            Some("x11") => SessionKind::X11,
            _ if self.wayland_display.as_deref().is_some_and(|value| !value.is_empty()) => SessionKind::Wayland,
            _ if self.display.as_deref().is_some_and(|value| !value.is_empty()) => SessionKind::X11,
            _ => SessionKind::Unknown,
        }
    }

    fn desktop_name(&self) -> Option<String> {
        self.current_desktop
            .as_deref()
            .or(self.session_desktop.as_deref())
            .and_then(sanitize_desktop_name)
    }
}

fn sanitize_desktop_name(value: &str) -> Option<String> {
    let value = value.trim();
    if value.is_empty() || value.len() > 80 {
        return None;
    }
    if !value.chars().all(|ch| ch.is_ascii_alphanumeric() || matches!(ch, '-' | '_' | '.' | ':' | '+' | ' ')) {
        return None;
    }
    Some(value.to_owned())
}

fn name_has_owner(proxy: &DBusProxy<'_>, name: &'static str) -> bool {
    let Ok(bus_name) = BusName::try_from(name) else {
        return false;
    };
    proxy.name_has_owner(bus_name).unwrap_or(false)
}

pub struct LinuxIntegrationAdapter {
    runtime_activation_available: bool,
}

impl LinuxIntegrationAdapter {
    pub const fn new(runtime_activation_available: bool) -> Self {
        Self { runtime_activation_available }
    }

    fn detect_with_environment(&self, environment: IntegrationEnvironment) -> IntegrationCapabilities {
        let (session_bus, notifications, status_notifier, portal) = match Connection::session() {
            Ok(connection) => match DBusProxy::new(&connection) {
                Ok(proxy) => (
                    CapabilityState::Available,
                    CapabilityState::from_bool(name_has_owner(&proxy, NOTIFICATIONS_NAME)),
                    CapabilityState::from_bool(name_has_owner(&proxy, STATUS_NOTIFIER_NAME)),
                    CapabilityState::from_bool(name_has_owner(&proxy, PORTAL_NAME)),
                ),
                Err(_) => (
                    CapabilityState::Unavailable,
                    CapabilityState::Unavailable,
                    CapabilityState::Unavailable,
                    CapabilityState::Unavailable,
                ),
            },
            Err(_) => (
                CapabilityState::Unavailable,
                CapabilityState::Unavailable,
                CapabilityState::Unavailable,
                CapabilityState::Unavailable,
            ),
        };

        IntegrationCapabilities {
            session: environment.session_kind(),
            desktop: environment.desktop_name(),
            session_bus,
            notifications,
            status_notifier,
            portal,
            runtime_activation: CapabilityState::from_bool(self.runtime_activation_available),
        }
    }
}

impl IntegrationAdapter for LinuxIntegrationAdapter {
    fn detect(&self) -> IntegrationCapabilities {
        self.detect_with_environment(IntegrationEnvironment::current())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a13_session_detection_prefers_declared_wayland_and_x11() {
        let adapter = LinuxIntegrationAdapter::new(true);
        let mut env = IntegrationEnvironment {
            xdg_session_type: Some("wayland".into()),
            wayland_display: Some("wayland-0".into()),
            display: Some(":0".into()),
            current_desktop: Some("KDE".into()),
            session_desktop: None,
        };
        let view = adapter.detect_with_environment(env.clone());
        assert_eq!(view.session, SessionKind::Wayland);
        assert_eq!(view.desktop.as_deref(), Some("KDE"));
        assert_eq!(view.runtime_activation, CapabilityState::Available);

        env.xdg_session_type = Some("x11".into());
        assert_eq!(adapter.detect_with_environment(env).session, SessionKind::X11);
    }

    #[test]
    fn a13_session_detection_falls_back_without_collecting_display_values() {
        let adapter = LinuxIntegrationAdapter::new(false);
        let env = IntegrationEnvironment {
            xdg_session_type: None,
            wayland_display: Some("wayland-sensitive-name".into()),
            display: Some(":88".into()),
            current_desktop: Some("GNOME:GNOME-Classic".into()),
            session_desktop: None,
        };
        let view = adapter.detect_with_environment(env);
        assert_eq!(view.session, SessionKind::Wayland);
        assert_eq!(view.desktop.as_deref(), Some("GNOME:GNOME-Classic"));
        assert_eq!(view.runtime_activation, CapabilityState::Unavailable);
    }

    #[test]
    fn a13_desktop_name_is_sanitized_and_bounded() {
        assert_eq!(sanitize_desktop_name(" KDE ").as_deref(), Some("KDE"));
        assert!(sanitize_desktop_name("GNOME\nsecret").is_none());
        assert!(sanitize_desktop_name(&"x".repeat(81)).is_none());
    }
}
