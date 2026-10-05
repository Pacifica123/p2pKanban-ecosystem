use tauri::Url;

/// A01 intentionally permits only Tauri's packaged-asset origin.
/// HTTP(S), file, data, javascript and custom remote schemes are denied.
pub fn allows_top_level_navigation(url: &Url) -> bool {
    url.scheme() == "tauri" && url.host_str() == Some("localhost")
}

#[cfg(test)]
mod tests {
    use super::allows_top_level_navigation;
    use tauri::Url;

    fn allowed(candidate: &str) -> bool {
        allows_top_level_navigation(&Url::parse(candidate).expect("test URL must parse"))
    }

    #[test]
    fn accepts_packaged_tauri_origin() {
        assert!(allowed("tauri://localhost/index.html"));
        assert!(allowed("tauri://localhost/assets/index.js"));
    }

    #[test]
    fn rejects_remote_and_local_http_origins() {
        assert!(!allowed("https://example.com/"));
        assert!(!allowed("http://example.com/"));
        assert!(!allowed("http://localhost:5173/"));
        assert!(!allowed("http://127.0.0.1:3000/"));
    }

    #[test]
    fn rejects_non_app_schemes() {
        assert!(!allowed("file:///tmp/index.html"));
        assert!(!allowed("data:text/html,hello"));
        assert!(!allowed("javascript:alert(1)"));
    }
}
