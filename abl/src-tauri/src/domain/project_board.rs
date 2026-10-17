//! abl side of `p2p-kanban-project-board/1` (contracts/project-board/1): the
//! ecosystem's own board, read-only and outside the profile database.
//!
//! The only source here is `build`: the copy of `board/board.json` vendored into
//! `src-tauri/assets/project-board.json` by `tools/ecosystem/project_board.py vendor abl`
//! and compiled into the binary. abl has no link to a web node yet, so `node` and
//! `cache` are not offered. The board is never written to the profile database, a replica, the
//! relay or the keyring, so connecting devices cannot duplicate it.

use serde_json::Value;
use sha2::{Digest, Sha256};

pub const PROTOCOL: &str = "p2p-kanban-project-board/1";
pub const PROJECT_BOARD_ID: &str = "01a10d38-f902-7665-8612-3e74278ceafa";
pub const PROJECT_WORKSPACE_ID: &str = "01a10d38-f901-746d-92f7-10598bb1cc42";
pub const MAX_BYTES: usize = 10 * 1024 * 1024;

pub static BUILD: &str = include_str!("../../assets/project-board.json");

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ProjectBoardSummary {
    pub revision: i64,
    pub last_patch_id: String,
    pub generated_at: Option<String>,
    pub sha256: String,
    pub bytes: usize,
}

/// Bytes of a portable board → its project-board summary, or the SPEC rejection code.
pub fn summarize(raw: &[u8]) -> Result<ProjectBoardSummary, &'static str> {
    if raw.len() > MAX_BYTES {
        return Err("too-large");
    }
    let bundle: Value = serde_json::from_slice(raw).map_err(|_| "not-json")?;
    let Some(bundle) = bundle.as_object() else { return Err("not-json") };
    let Some(manifest) = bundle.get("manifest.json").and_then(Value::as_object).filter(|m| {
        m.get("format").and_then(Value::as_str) == Some("p2p_planner_bundle")
            && m.get("formatVersion").and_then(Value::as_i64) == Some(1)
            && m.get("bundleKind").and_then(Value::as_str) == Some("portable_export")
            && m.get("scopeKind").and_then(Value::as_str) == Some("board")
    }) else {
        return Err("wrong-format");
    };
    let origin = bundle.get("origin").and_then(Value::as_object);
    let Some(origin) = origin.filter(|o| {
        manifest.get("boardId").and_then(Value::as_str) == Some(PROJECT_BOARD_ID)
            && manifest.get("workspaceId").and_then(Value::as_str) == Some(PROJECT_WORKSPACE_ID)
            && o.get("selfHosted").and_then(Value::as_bool) == Some(true)
    }) else {
        return Err("foreign-board");
    };
    let revision = origin
        .get("boardRevision")
        .filter(|v| v.is_i64() || v.is_u64())
        .and_then(Value::as_i64)
        .filter(|r| *r >= 1);
    let patch = origin.get("lastPatchId").and_then(Value::as_str).filter(|p| !p.trim().is_empty());
    let (Some(revision), Some(patch)) = (revision, patch) else {
        return Err("no-revision");
    };
    Ok(ProjectBoardSummary {
        revision,
        last_patch_id: patch.to_owned(),
        generated_at: origin.get("generatedAt").and_then(Value::as_str).map(str::to_owned),
        sha256: Sha256::digest(raw).iter().map(|b| format!("{b:02x}")).collect(),
        bytes: raw.len(),
    })
}

/// The copy compiled into this build. The UTS gate and the unit test below keep it valid.
pub fn build_board() -> (&'static str, ProjectBoardSummary) {
    (BUILD, summarize(BUILD.as_bytes()).expect("assets/project-board.json must be the project board"))
}

#[cfg(test)]
mod tests {
    use super::*;

    // abl lives in the ecosystem tree next to contracts/, like tools/check_error_report.mjs assumes.
    fn vectors() -> Value {
        serde_json::from_str(include_str!("../../../../contracts/project-board/1/vectors/summary.json")).unwrap()
    }

    #[test]
    fn project_board_summary_matches_contract_vectors() {
        let vectors = vectors();
        assert_eq!(vectors["projectBoardId"], PROJECT_BOARD_ID);
        assert_eq!(vectors["projectWorkspaceId"], PROJECT_WORKSPACE_ID);
        for case in vectors["cases"].as_array().unwrap() {
            let name = case["name"].as_str().unwrap();
            let raw = case["raw"].as_str().unwrap().as_bytes();
            match (case.get("rejected"), summarize(raw)) {
                (Some(code), got) => assert_eq!(got.map(|_| ()), Err(code.as_str().unwrap()), "{name}"),
                (None, got) => {
                    let summary = got.unwrap_or_else(|code| panic!("{name}: {code}"));
                    let expected = &case["expected"];
                    assert_eq!(expected["protocol"], PROTOCOL, "{name}");
                    assert_eq!(expected["revision"], summary.revision, "{name}");
                    assert_eq!(expected["lastPatchId"], summary.last_patch_id.as_str(), "{name}");
                    assert_eq!(expected["generatedAt"].as_str(), summary.generated_at.as_deref(), "{name}");
                    assert_eq!(expected["sha256"], summary.sha256.as_str(), "{name}");
                    assert_eq!(expected["bytes"], summary.bytes, "{name}");
                }
            }
        }
    }

    #[test]
    fn vendored_copy_is_the_project_board() {
        let (raw, summary) = build_board();
        assert_eq!(summary.bytes, raw.len());
        assert!(summary.revision >= 1);
    }

    #[test]
    fn oversized_input_is_rejected_before_parsing() {
        assert_eq!(summarize(&vec![b' '; MAX_BYTES + 1]), Err("too-large"));
    }
}
