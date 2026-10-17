//! Node side of contracts/project-board/1: the shared vectors decide what is a
//! project board and which candidate wins; the routes serve the vendored copy
//! without sign-in and answer a matching etag with 304.
use std::path::{Path, PathBuf};

use axum::{
    body::{to_bytes, Body},
    http::{header, Request, StatusCode},
    Router,
};
use p2p_planner_backend::modules::project_board::{self, build_summary, select, summarize};
use serde_json::Value;
use tower::ServiceExt;

fn vectors() -> PathBuf {
    let mut dir = Path::new(env!("CARGO_MANIFEST_DIR")).to_path_buf();
    while !dir.join("contracts/compatibility.json").is_file() {
        assert!(dir.pop(), "contracts/compatibility.json not found above web/backend");
    }
    dir.join("contracts/project-board/1/vectors")
}

fn vector(name: &str) -> Value {
    serde_json::from_slice(&std::fs::read(vectors().join(name)).unwrap()).unwrap()
}

#[test]
fn summary_vectors() {
    let data = vector("summary.json");
    assert_eq!(data["projectBoardId"], project_board::PROJECT_BOARD_ID);
    for case in data["cases"].as_array().unwrap() {
        let name = case["name"].as_str().unwrap();
        let got = summarize(case["raw"].as_str().unwrap().as_bytes());
        match case.get("rejected") {
            Some(reason) => assert_eq!(got.err(), reason.as_str(), "{name}"),
            None => assert_eq!(serde_json::to_value(got.unwrap()).unwrap(), case["expected"], "{name}"),
        }
    }
}

#[test]
fn selection_vectors() {
    let data = vector("selection.json");
    for case in data["cases"].as_array().unwrap() {
        let name = case["name"].as_str().unwrap();
        let parsed: Vec<(String, project_board::Summary)> = case["candidates"]
            .as_array()
            .unwrap()
            .iter()
            .filter(|c| c.get("summary").is_some())
            .map(|c| {
                let s = &c["summary"];
                (c["source"].as_str().unwrap().to_string(), project_board::Summary {
                    protocol: project_board::PROTOCOL,
                    board_id: project_board::PROJECT_BOARD_ID,
                    revision: s["revision"].as_i64().unwrap(),
                    last_patch_id: s["lastPatchId"].as_str().unwrap().to_string(),
                    generated_at: s["generatedAt"].as_str().map(str::to_string),
                    sha256: s["sha256"].as_str().unwrap().to_string(),
                    bytes: s["bytes"].as_u64().unwrap() as usize,
                })
            })
            .collect();
        let refs: Vec<(String, &project_board::Summary)> = parsed.iter().map(|(k, s)| (k.clone(), s)).collect();
        let expected = &case["expected"];
        match select(&refs) {
            None => assert!(expected["chosen"].is_null(), "{name}"),
            Some((source, summary, conflict)) => {
                assert_eq!(expected["chosen"], source.as_str(), "{name}");
                assert_eq!(expected["revision"], summary.revision, "{name}");
                assert_eq!(expected["sha256"], summary.sha256.as_str(), "{name}");
                assert_eq!(expected["lastPatchId"], summary.last_patch_id.as_str(), "{name}");
                assert_eq!(expected["conflict"], conflict, "{name}");
            }
        }
    }
}

fn app() -> Router {
    Router::new().nest("/api/v1", project_board::router::<()>())
}

#[tokio::test]
async fn routes_serve_the_vendored_board_without_sign_in() {
    let build = build_summary();
    let response = app().oneshot(Request::get("/api/v1/project-board").body(Body::empty()).unwrap()).await.unwrap();
    assert_eq!(response.status(), StatusCode::OK);
    let etag = response.headers().get(header::ETAG).unwrap().to_str().unwrap().to_string();
    assert_eq!(etag, format!("\"{}\"", build.sha256));
    let marker = response.headers().get(project_board::BOARD_HEADER).unwrap().to_str().unwrap().to_string();
    assert!(marker.starts_with(&format!("rev={}; patch={}", build.revision, build.last_patch_id)), "{marker}");
    let bytes = to_bytes(response.into_body(), usize::MAX).await.unwrap();
    assert_eq!(summarize(&bytes).unwrap(), *build);

    let again = app()
        .oneshot(Request::get("/api/v1/project-board").header(header::IF_NONE_MATCH, &etag).body(Body::empty()).unwrap())
        .await
        .unwrap();
    assert_eq!(again.status(), StatusCode::NOT_MODIFIED);

    let summary = app().oneshot(Request::get("/api/v1/project-board/summary").body(Body::empty()).unwrap()).await.unwrap();
    assert_eq!(summary.status(), StatusCode::OK);
    let body: Value = serde_json::from_slice(&to_bytes(summary.into_body(), usize::MAX).await.unwrap()).unwrap();
    assert_eq!(body["data"]["protocol"], project_board::PROTOCOL);
    assert_eq!(body["data"]["served"]["summary"]["revision"], build.revision);
    assert_eq!(body["data"]["build"]["sha256"], build.sha256.as_str());
}
