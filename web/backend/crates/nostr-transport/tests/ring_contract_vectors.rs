//! The web implementation of R1 contracts checked against the shared vectors in
//! `contracts/` (account-ring/1, keyring/1, rendezvous/1). The vectors are the source of truth;
//! when this test and `tools/ecosystem/contract_ref.py` disagree, this side is wrong.
use std::path::{Path, PathBuf};

use nostr_sdk::prelude::*;
use p2p_kanban_nostr_transport::{rendezvous, ring};
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
    // The welcome log a joiner receives folds here exactly as on the other directions.
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

fn rendezvous_vectors() -> Vec<(String, Value)> {
    ["invite-mode.json", "join-mode.json", "refuse-ring-merge.json"].iter()
        .map(|name| (name.to_string(), vector(&format!("rendezvous/1/vectors/{name}")))).collect()
}

#[test]
fn rendezvous_qr_and_derived_values_match() {
    for (name, data) in rendezvous_vectors() {
        let qr = &data["qr"];
        assert_eq!(rendezvous::qr_encode(qr), data["qrText"].as_str().unwrap(), "{name}");
        assert_eq!(&rendezvous::qr_decode(data["qrText"].as_str().unwrap()).unwrap(), qr, "{name}");
        let secret = ring::unb64url(qr["s"].as_str().unwrap()).unwrap();
        let session = rendezvous::session_id(&secret);
        assert_eq!(session, data["derived"]["sessionId"].as_str().unwrap(), "{name}");
        let key: String = rendezvous::session_key(&secret).iter().map(|b| format!("{b:02x}")).collect();
        assert_eq!(key, data["derived"]["sessionKey"].as_str().unwrap(), "{name}");
        let joiner = data["roles"]["joiner"].as_str().unwrap();
        assert_eq!(rendezvous::confirm_code(&session, joiner), data["derived"]["confirmCode"].as_str().unwrap(), "{name}");
    }
}

#[test]
fn rendezvous_mailbox_opens_to_expected_messages() {
    for (name, data) in rendezvous_vectors() {
        let secret = ring::unb64url(data["qr"]["s"].as_str().unwrap()).unwrap();
        let mails = rendezvous::open_mailbox(data["events"].as_array().unwrap(), &secret);
        let messages: Vec<Value> = mails.iter().map(|m| m.message.clone()).collect();
        assert_eq!(Value::Array(messages), data["expectedMessages"], "{name}");
        let mut reversed = data["events"].as_array().unwrap().clone();
        reversed.reverse();
        assert_eq!(rendezvous::open_mailbox(&reversed, &secret), mails, "{name} reversed");
        assert!(rendezvous::open_mailbox(data["events"].as_array().unwrap(), &[0u8; 32]).is_empty(), "{name}: foreign secret");
    }
}

#[test]
fn rendezvous_sponsor_and_joiner_reach_the_vector_outcome() {
    for (name, data) in rendezvous_vectors() {
        let qr = &data["qr"];
        let secret = ring::unb64url(qr["s"].as_str().unwrap()).unwrap();
        let mails = rendezvous::open_mailbox(data["events"].as_array().unwrap(), &secret);
        let sponsor = data["roles"]["sponsor"].as_str().unwrap();
        let joiner = data["roles"]["joiner"].as_str().unwrap();
        let expected = &data["expectedMessages"];
        // The sponsor's own ring before the meeting: it is the admin.
        let state = serde_json::json!({"accountId": "00".repeat(32), "removed": [],
            "members": [{"publicKey": sponsor, "role": "admin"}]});
        let before = qr["x"].as_u64().unwrap() - 60;
        let review = rendezvous::sponsor_review(qr, &mails, sponsor, &state, true, before);
        match expected.as_array().unwrap().iter().find(|m| m["type"] == "refuse") {
            Some(refuse) => {
                let refusal = review.unwrap_err();
                assert_eq!(refusal.message(mails[0].message["sessionId"].as_str().unwrap()), *refuse, "{name}");
            }
            None => {
                assert_eq!(review.unwrap().unwrap(), expected[0], "{name}: hello to answer");
                let welcome = mails.iter().find(|m| m.message["type"] == "welcome").unwrap();
                let ring_after = rendezvous::verify_welcome(welcome, qr, joiner).unwrap();
                assert_eq!(&ring_after, &data["expectedRingAfter"], "{name}");
                let stranger = "11".repeat(32);
                assert_eq!(rendezvous::verify_welcome(welcome, qr, &stranger).unwrap_err().reason, "welcome-invalid");
            }
        }
        assert_eq!(rendezvous::sponsor_review(qr, &mails, sponsor, &state, true, qr["x"].as_u64().unwrap() + 1).unwrap_err().reason, "expired");
        assert_eq!(rendezvous::sponsor_review(qr, &mails, sponsor, &state, false, before).unwrap_err().reason, "sponsor-stale", "{name}");
    }
}

#[test]
fn rendezvous_second_hello_contests_invite() {
    let data = vector("rendezvous/1/vectors/invite-mode.json");
    let qr = &data["qr"];
    let secret = ring::unb64url(qr["s"].as_str().unwrap()).unwrap();
    let mut events = data["events"].as_array().unwrap().clone();
    let intruder = Keys::generate();
    let mut hello = data["expectedMessages"][0].clone();
    hello["device"]["publicKey"] = Value::String(intruder.public_key().to_hex());
    events.extend(rendezvous::mailbox_events(&intruder, &secret, &hello, 1_791_244_831, qr["x"].as_u64().unwrap()).unwrap());
    let mails = rendezvous::open_mailbox(&events, &secret);
    let sponsor = data["roles"]["sponsor"].as_str().unwrap();
    let state = serde_json::json!({"accountId": "00".repeat(32), "removed": [], "members": [{"publicKey": sponsor, "role": "admin"}]});
    let refusal = rendezvous::sponsor_review(qr, &mails, sponsor, &state, true, qr["x"].as_u64().unwrap() - 60).unwrap_err();
    assert_eq!(refusal.reason, "contested");
}
