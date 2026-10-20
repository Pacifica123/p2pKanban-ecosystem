pub mod import;
pub mod integration;
pub mod parity;
pub mod planner;
pub mod system;
// Staged (A10): sync-core/roaming layer is complete and covered by tests, but no relay
// transport or coordinator constructs it yet, so the running app neither sends nor
// receives board events. Board card: «abl: живая синхронизация доски по roaming/1».
#[allow(dead_code)]
pub mod sync;

pub mod lan_bridge;
pub mod project_board;
pub mod recovery;
