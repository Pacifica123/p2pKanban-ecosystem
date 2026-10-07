//! The web implementation of R1 contracts checked against the shared vectors in
//! `contracts/` (account-ring/1, keyring/1). The vectors are the source of truth;
//! when this test and `tools/ecosystem/contract_ref.py` disagree, this side is wrong.
use std::path::{Path, PathBuf};

use nostr_sdk::prelude::*;
use p2p_kanban_nostr_transport::ring;
use serde_json::Value;

fn contracts_dir() -> PathBuf {
    let mut dir = Path::new(env!("CARGO_MANIFEST_DIR")).to_path_buf();
    loop {
        if dir.join("contracts/compatibility.json").is_file() {
            return dir.join("contracts");
        }
        assert!(dir.pop(), "contracts/compatibility.json not found above the crate");
    }
}

fn vector(path: &str) -> Value {
    let text = std::fs::read_to_string(contracts_dir().join(path)).unwrap();
    serde_json::from_str(&text).unwrap()
}

fn keys(secret: &Value) -> Keys {
    Keys::parse(secret.as_str().unwrap()).unwrap()
}

#[test]
fn every_ring_vector_folds_to_expected_state_in_any_order() {
    let dir = contracts_dir().join("account-ring/1/vectors");
    let mut checked = 0;
    for entry in std::fs::read_dir(dir).unwrap() {
        let path = entry.unwrap().path();
        let name = path.file_name().unwrap().to_string_lossy().to_string();
        if !name.starts_with("ring-") {
            continue;
        }
        let data: Value = serde_json::from_str(&std::fs::read_to_string(&path).unwrap()).unwrap();
        let mut entries = data["entries"].as_array().unwrap().clone();
        let account = data["accountId"].as_str();
        let state = ring::fold_ring(&entries, account).unwrap();
        assert_eq!(state, data["expected"], "{name}");
        entries.reverse();
        assert_eq!(ring::fold_ring(&entries, account).unwrap(), data["expected"], "{name} reversed");
        assert_eq!(state["accountTag"].as_str().unwrap(), ring::account_tag(data["accountId"].as_str().unwrap()).unwrap());
        checked += 1;
    }
    assert!(checked >= 7, "only {checked} ring vectors");
}

#[test]
fn rendezvous_welcome_entries_fold_to_ring_after() {
    // R2 does not run rendezvous yet (that is R3), but the welcome log it would
    // receive must fold here exactly as on the other directions.
    for name in ["invite-mode.json", "join-mode.json"] {
        let data = vector(&format!("rendezvous/1/vectors/{name}"));
        let expected = &data["expectedRingAfter"];
        let welcome = data["expectedMessages"].as_array().unwrap().iter().find(|m| m["type"] == "welcome").unwrap();
        let entries = welcome["entries"].as_array().unwrap();
        assert_eq!(&ring::fold_ring(entries, expected["accountId"].as_str()).unwrap(), expected, "{name}");
    }
}

#[test]
fn keys_vector_derives_public_keys() {
    let data = vector("account-ring/1/vectors/keys.json");
    for key in data["keys"].as_array().unwrap() {
        assert_eq!(keys(&key["secretKey"]).public_key().to_hex(), key["publicKey"].as_str().unwrap());
    }
}

#[test]
fn sealed_ring_log_opens_for_recipient_only() {
    let data = vector("account-ring/1/vectors/sealed-ring-log.json");
    let account = data["expectedPlaintext"]["accountId"].as_str().unwrap();
    assert_eq!(ring::account_tag(account).unwrap(), data["accountTag"].as_str().unwrap());
    let (_, record_type, plain) = ring::open_sealed_event(&keys(&data["recipient"]["secretKey"]), &data["event"], account).unwrap();
    assert_eq!(record_type, "ring-log");
    assert_eq!(plain, data["expectedPlaintext"]);
    assert!(ring::open_sealed_event(&keys(&data["outsider"]["secretKey"]), &data["event"], account).is_err());

    let mut tampered = data["event"].clone();
    tampered["content"] = Value::String(tampered["content"].as_str().unwrap().replace("\"ciphertext\":\"", "\"ciphertext\":\"A"));
    assert!(ring::open_sealed_event(&keys(&data["recipient"]["secretKey"]), &tampered, account).is_err());
}

#[test]
fn sealed_keyring_opens_and_merge_matches() {
    let data = vector("keyring/1/vectors/sealed-keyring.json");
    let account = data["expectedPlaintext"]["accountId"].as_str().unwrap();
    let (_, record_type, plain) = ring::open_sealed_event(&keys(&data["recipient"]["secretKey"]), &data["event"], account).unwrap();
    assert_eq!(record_type, "keyring");
    assert_eq!(plain, data["expectedPlaintext"]);

    let merge = vector("keyring/1/vectors/merge.json");
    let copies = merge["copies"].as_array().unwrap().clone();
    let items = ring::merge_keyrings(&copies);
    assert_eq!(Value::Array(items.clone()), merge["expected"]["items"]);
    assert_eq!(ring::keyring_digest(&items), merge["expected"]["digest"].as_str().unwrap());
    let reversed: Vec<Value> = copies.into_iter().rev().collect();
    assert_eq!(ring::merge_keyrings(&reversed), items);
}

#[test]
fn presence_opens_and_skew_matches() {
    let data = vector("account-ring/1/vectors/presence.json");
    let me = keys(&data["recipient"]["secretKey"]);
    let mut presences = Vec::new();
    for (event, expected) in data["events"].as_array().unwrap().iter().zip(data["expectedPlaintexts"].as_array().unwrap()) {
        let account = expected["accountId"].as_str().unwrap();
        let (_, record_type, plain) = ring::open_sealed_event(&me, event, account).unwrap();
        assert_eq!(record_type, "presence");
        assert_eq!(&plain, expected);
        presences.push(plain);
    }
    let heads: Vec<String> = data["ringHeads"].as_array().unwrap().iter().map(|h| h.as_str().unwrap().to_string()).collect();
    assert_eq!(Value::Array(ring::presence_skew(&presences, &heads)), data["expectedSkew"]);
}
