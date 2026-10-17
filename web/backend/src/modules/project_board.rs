//! Node side of `p2p-kanban-project-board/1` (contracts/project-board/1):
//! the ecosystem's own board, read-only, outside the user's data.
//!
//! - `build`: the copy of `board/board.json` vendored into this tree
//!   (`assets/project-board.json`, refreshed by `tools/ecosystem/project_board.py vendor web`);
//! - `upstream`: `board/board.json` on `main` of the update channel, checked at start
//!   and then hourly; `P2PKANBAN_PROJECT_BOARD_UPSTREAM=off` turns it off.
//!
//! The board is never written to PostgreSQL, the relay or a node link, so linking
//! nodes cannot duplicate it. The higher `boardRevision` wins.

use std::{
    sync::{OnceLock, RwLock},
    time::Duration,
};

use axum::{
    body::Body,
    http::{header, HeaderMap, HeaderValue, StatusCode},
    response::{IntoResponse, Response},
    routing::get,
    Router,
};
use serde::Serialize;
use serde_json::Value;
use sha2::{Digest, Sha256};

use crate::http::response::ok;

pub const PROTOCOL: &str = "p2p-kanban-project-board/1";
pub const PROJECT_BOARD_ID: &str = "01a10d38-f902-7665-8612-3e74278ceafa";
pub const PROJECT_WORKSPACE_ID: &str = "01a10d38-f901-746d-92f7-10598bb1cc42";
pub const MAX_BYTES: usize = 10 * 1024 * 1024;
pub const BOARD_HEADER: &str = "x-p2p-kanban-project-board";
const DEFAULT_UPSTREAM: &str =
    "https://raw.githubusercontent.com/Pacifica123/p2pKanban-ecosystem/main/board/board.json";
const UPSTREAM_INTERVAL: Duration = Duration::from_secs(3600);
const UPSTREAM_RETRY: Duration = Duration::from_secs(300);

static BUILD: &[u8] = include_bytes!("../../assets/project-board.json");

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Summary {
    pub protocol: &'static str,
    pub board_id: &'static str,
    pub revision: i64,
    pub last_patch_id: String,
    pub generated_at: Option<String>,
    pub sha256: String,
    pub bytes: usize,
}

/// Bytes of a portable board → its project-board summary, or the SPEC rejection code.
pub fn summarize(raw: &[u8]) -> Result<Summary, &'static str> {
    if raw.len() > MAX_BYTES {
        return Err("too-large");
    }
    let bundle: Value = serde_json::from_slice(raw).map_err(|_| "not-json")?;
    let Some(bundle) = bundle.as_object() else { return Err("not-json") };
    let manifest = bundle.get("manifest.json").and_then(Value::as_object);
    let format_ok = manifest.is_some_and(|m| {
        m.get("format").and_then(Value::as_str) == Some("p2p_planner_bundle")
            && m.get("formatVersion").and_then(Value::as_i64) == Some(1)
            && m.get("bundleKind").and_then(Value::as_str) == Some("portable_export")
            && m.get("scopeKind").and_then(Value::as_str) == Some("board")
    });
    if !format_ok {
        return Err("wrong-format");
    }
    let manifest = manifest.expect("checked above");
    let origin = bundle.get("origin").and_then(Value::as_object);
    if manifest.get("boardId").and_then(Value::as_str) != Some(PROJECT_BOARD_ID)
        || manifest.get("workspaceId").and_then(Value::as_str) != Some(PROJECT_WORKSPACE_ID)
        || origin.and_then(|o| o.get("selfHosted")).and_then(Value::as_bool) != Some(true)
    {
        return Err("foreign-board");
    }
    let origin = origin.expect("checked above");
    let revision = origin.get("boardRevision").filter(|v| v.is_i64() || v.is_u64()).and_then(Value::as_i64);
    let patch = origin.get("lastPatchId").and_then(Value::as_str).filter(|p| !p.trim().is_empty());
    let (Some(revision), Some(patch)) = (revision.filter(|r| *r >= 1), patch) else {
        return Err("no-revision");
    };
    Ok(Summary {
        protocol: PROTOCOL,
        board_id: PROJECT_BOARD_ID,
        revision,
        last_patch_id: patch.to_string(),
        generated_at: origin.get("generatedAt").and_then(Value::as_str).map(str::to_string),
        sha256: hex(&Sha256::digest(raw)),
        bytes: raw.len(),
    })
}

fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|b| format!("{b:02x}")).collect()
}

/// `select_project_board` of the reference, for any number of candidates in client order.
pub fn select<'a, T>(candidates: &'a [(T, &'a Summary)]) -> Option<(&'a T, &'a Summary, bool)> {
    let top = candidates.iter().map(|(_, s)| s.revision).max()?;
    let leaders: Vec<_> = candidates.iter().filter(|(_, s)| s.revision == top).collect();
    let lowest = leaders.iter().map(|(_, s)| s.sha256.as_str()).min()?;
    let conflict = leaders.iter().any(|(_, s)| s.sha256 != lowest);
    let (source, summary) = leaders.into_iter().find(|(_, s)| s.sha256 == lowest)?;
    Some((source, summary, conflict))
}

pub fn build_summary() -> &'static Summary {
    static SUMMARY: OnceLock<Summary> = OnceLock::new();
    SUMMARY.get_or_init(|| summarize(BUILD).expect("assets/project-board.json must be the project board"))
}

#[derive(Debug, Default)]
struct Upstream {
    checked_at: Option<String>,
    raw: Option<Vec<u8>>,
    summary: Option<Summary>,
    etag: Option<String>,
    error: Option<String>,
}

fn upstream() -> &'static RwLock<Upstream> {
    static UPSTREAM: OnceLock<RwLock<Upstream>> = OnceLock::new();
    UPSTREAM.get_or_init(|| RwLock::new(Upstream::default()))
}

/// `None` when the upstream check is turned off.
pub fn upstream_url() -> Option<String> {
    match std::env::var("P2PKANBAN_PROJECT_BOARD_UPSTREAM").ok().map(|v| v.trim().to_string()) {
        Some(v) if ["off", "false", "0", "no"].contains(&v.to_ascii_lowercase().as_str()) => None,
        Some(v) if v.starts_with("https://") || v.starts_with("http://") => Some(v),
        _ => Some(DEFAULT_UPSTREAM.to_string()),
    }
}

/// Remember one upstream answer. A valid board replaces the stored one; anything
/// else keeps the last good board and records why the check failed.
fn record_upstream(result: Result<Option<(Vec<u8>, Option<String>)>, String>) {
    let mut state = upstream().write().expect("project board lock");
    state.checked_at = Some(now_iso());
    match result {
        Ok(None) => state.error = None,
        Ok(Some((raw, etag))) => match summarize(&raw) {
            Ok(summary) => {
                state.summary = Some(summary);
                state.raw = Some(raw);
                state.etag = etag;
                state.error = None;
            }
            Err(reason) => state.error = Some(reason.to_string()),
        },
        Err(error) => state.error = Some(error),
    }
}

fn now_iso() -> String {
    let secs = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs() as i64)
        .unwrap_or(0);
    let (days, rem) = (secs.div_euclid(86_400), secs.rem_euclid(86_400));
    // Civil-from-days (H. Hinnant), enough for a timestamp in a status line.
    let z = days + 719_468;
    let era = z.div_euclid(146_097);
    let doe = z.rem_euclid(146_097);
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let day = doy - (153 * mp + 2) / 5 + 1;
    let month = if mp < 10 { mp + 3 } else { mp - 9 };
    let year = yoe + era * 400 + i64::from(month <= 2);
    format!("{year:04}-{month:02}-{day:02}T{:02}:{:02}:{:02}Z", rem / 3600, rem % 3600 / 60, rem % 60)
}

async fn fetch_upstream(client: &reqwest::Client, url: &str) -> Result<Option<(Vec<u8>, Option<String>)>, String> {
    let etag = upstream().read().expect("project board lock").etag.clone();
    let mut request = client.get(url);
    if let Some(etag) = etag {
        request = request.header(reqwest::header::IF_NONE_MATCH, etag);
    }
    let response = request.send().await.map_err(|e| format!("unreachable: {}", short(&e.to_string())))?;
    if response.status() == reqwest::StatusCode::NOT_MODIFIED {
        return Ok(None);
    }
    if !response.status().is_success() {
        return Err(format!("http-error: {}", response.status().as_u16()));
    }
    if response.content_length().is_some_and(|len| len as usize > MAX_BYTES) {
        return Err("too-large".to_string());
    }
    let etag = response.headers().get(reqwest::header::ETAG).and_then(|v| v.to_str().ok()).map(str::to_string);
    let bytes = response.bytes().await.map_err(|e| format!("unreachable: {}", short(&e.to_string())))?;
    Ok(Some((bytes.to_vec(), etag)))
}

fn short(text: &str) -> String {
    text.chars().take(160).collect()
}

/// Check `upstream` at start, then hourly (every five minutes after a failure).
pub fn spawn_upstream_worker() {
    let Some(url) = upstream_url() else {
        tracing::info!("project board: upstream check is off");
        return;
    };
    tokio::spawn(async move {
        let _ = rustls::crypto::ring::default_provider().install_default();
        let client = match reqwest::Client::builder()
            .timeout(Duration::from_secs(20))
            .user_agent(concat!("p2pkanban-node/", env!("CARGO_PKG_VERSION")))
            .build()
        {
            Ok(client) => client,
            Err(error) => {
                record_upstream(Err(format!("unreachable: {}", short(&error.to_string()))));
                return;
            }
        };
        loop {
            let result = fetch_upstream(&client, &url).await;
            let failed = result.is_err();
            if let Err(error) = &result {
                tracing::info!(%error, "project board: upstream check failed, serving the newest known copy");
            }
            record_upstream(result);
            tokio::time::sleep(if failed { UPSTREAM_RETRY } else { UPSTREAM_INTERVAL }).await;
        }
    });
}

/// What `GET /project-board` serves now: (source, bytes, summary, conflict).
fn served() -> (&'static str, Vec<u8>, Summary, bool) {
    let build = build_summary();
    let state = upstream().read().expect("project board lock");
    if let (Some(raw), Some(summary)) = (&state.raw, &state.summary) {
        let candidates = [("build", build), ("upstream", summary)];
        if let Some((source, chosen, conflict)) = select(&candidates) {
            if *source == "upstream" {
                return ("upstream", raw.clone(), chosen.clone(), conflict);
            }
            return ("build", BUILD.to_vec(), chosen.clone(), conflict);
        }
    }
    ("build", BUILD.to_vec(), build.clone(), false)
}

async fn get_board(headers: HeaderMap) -> Response {
    let (source, raw, summary, conflict) = served();
    let etag = format!("\"{}\"", summary.sha256);
    let mut builder = Response::builder()
        .header(header::ETAG, &etag)
        .header(header::CACHE_CONTROL, "no-cache")
        .header(
            BOARD_HEADER,
            format!(
                "rev={}; patch={}; source={source}{}",
                summary.revision,
                summary.last_patch_id,
                if conflict { "; conflict" } else { "" }
            ),
        );
    let matches = headers
        .get(header::IF_NONE_MATCH)
        .and_then(|v| v.to_str().ok())
        .is_some_and(|v| v.split(',').any(|tag| tag.trim().trim_start_matches("W/") == etag));
    if matches {
        return builder.status(StatusCode::NOT_MODIFIED).body(Body::empty()).expect("valid response");
    }
    builder = builder.header(header::CONTENT_TYPE, HeaderValue::from_static("application/json"));
    builder.status(StatusCode::OK).body(Body::from(raw)).expect("valid response")
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct Served {
    source: &'static str,
    summary: Summary,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct UpstreamPayload {
    enabled: bool,
    url: Option<String>,
    checked_at: Option<String>,
    summary: Option<Summary>,
    error: Option<String>,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct NodeSummary {
    protocol: &'static str,
    served: Served,
    build: Summary,
    upstream: UpstreamPayload,
}

pub fn node_summary() -> NodeSummary {
    let (source, _, summary, _) = served();
    let url = upstream_url();
    let state = upstream().read().expect("project board lock");
    NodeSummary {
        protocol: PROTOCOL,
        served: Served { source, summary },
        build: build_summary().clone(),
        upstream: UpstreamPayload {
            enabled: url.is_some(),
            url,
            checked_at: state.checked_at.clone(),
            summary: state.summary.clone(),
            error: state.error.clone(),
        },
    }
}

async fn get_summary() -> impl IntoResponse {
    ok(node_summary())
}

/// No sign-in: the content equals the public repository, and a phone must see the
/// board before signing in and on a node where it has no account.
pub fn router<S: Clone + Send + Sync + 'static>() -> Router<S> {
    Router::new()
        .route("/project-board", get(get_board))
        .route("/project-board/summary", get(get_summary))
}

#[cfg(test)]
pub(crate) fn set_upstream_for_test(raw: Option<Vec<u8>>) {
    let mut state = upstream().write().expect("project board lock");
    *state = Upstream::default();
    if let Some(raw) = raw {
        drop(state);
        record_upstream(Ok(Some((raw, None))));
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn vendored_copy_is_the_project_board() {
        let summary = build_summary();
        assert_eq!(summary.board_id, PROJECT_BOARD_ID);
        assert!(summary.revision >= 33);
    }

    #[test]
    fn timestamp_is_iso() {
        let now = now_iso();
        assert_eq!(now.len(), 20, "{now}");
        assert!(now.starts_with("20") && now.ends_with('Z'), "{now}");
    }

    #[test]
    fn newer_upstream_wins_and_older_does_not_roll_back() {
        let build = build_summary().clone();
        let newer = String::from_utf8(BUILD.to_vec()).unwrap().replacen(
            &format!("\"boardRevision\": {}", build.revision),
            &format!("\"boardRevision\": {}", build.revision + 5),
            1,
        );
        set_upstream_for_test(Some(newer.into_bytes()));
        let (source, _, summary, conflict) = served();
        assert_eq!((source, summary.revision, conflict), ("upstream", build.revision + 5, false));

        let older = String::from_utf8(BUILD.to_vec()).unwrap().replacen(
            &format!("\"boardRevision\": {}", build.revision),
            &format!("\"boardRevision\": {}", build.revision - 1),
            1,
        );
        set_upstream_for_test(Some(older.into_bytes()));
        let (source, _, summary, _) = served();
        assert_eq!((source, summary.revision), ("build", build.revision));

        record_upstream(Ok(Some((b"<html>rate limited</html>".to_vec(), None))));
        let state = node_summary();
        assert_eq!(state.upstream.error.as_deref(), Some("not-json"));
        assert_eq!(state.upstream.summary.map(|s| s.revision), Some(build.revision - 1), "last good board is kept");
        set_upstream_for_test(None);
    }
}
