mod auth;
mod envelope;
mod merge;
mod validation;

pub use auth::{sign_envelope, verify_envelope, AuthenticationError};
pub use envelope::{
    ClientChangeEvent, ServerChangeEvent, SignedSyncEnvelope, SyncEnvelope, SYNC_PROTOCOL_VERSION,
};
pub use merge::{choose_winner, MergeDecision, VersionStamp};
pub use validation::{
    normalize_operation, validate_client_event, validate_envelope, ValidationError,
};
