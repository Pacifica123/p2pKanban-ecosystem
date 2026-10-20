pub(crate) mod migration;
pub(crate) mod import;
pub(crate) mod repository;
pub(crate) mod recovery;
pub(crate) mod workspace;
// Staged (A10): sync-core/roaming layer is complete and covered by tests, but no relay
// transport or coordinator constructs it yet, so the running app neither sends nor
// receives board events. Board card: «abl: живая синхронизация доски по roaming/1».
#[allow(dead_code)]
pub(crate) mod sync;
pub(crate) mod parity;
