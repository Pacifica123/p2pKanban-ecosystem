use axum::{
    http::StatusCode,
    response::{IntoResponse, Response},
    Json,
};
use serde::Serialize;
use serde_json::Value;
use thiserror::Error;

pub type AppResult<T> = Result<T, AppError>;

#[derive(Debug, Error)]
pub enum AppError {
    #[error("bad request: {message}")]
    BadRequest {
        message: String,
        details: Option<Value>,
    },

    #[error("unauthorized: {message}")]
    Unauthorized { message: String },

    #[error("forbidden: {message}")]
    Forbidden { message: String },

    #[error("not found: {message}")]
    NotFound { message: String },

    #[error("conflict: {message}")]
    Conflict { message: String },

    #[error("not implemented: {message}")]
    NotImplemented { message: String },

    #[error("internal server error")]
    Internal { details: Option<Value> },
}

#[derive(Debug, Serialize)]
struct ErrorEnvelope {
    error: ErrorPayload,
}

#[derive(Debug, Serialize)]
struct ErrorPayload {
    code: String,
    message: String,
    details: Option<Value>,
}

impl AppError {
    pub fn bad_request(message: impl Into<String>) -> Self {
        Self::BadRequest {
            message: message.into(),
            details: None,
        }
    }

    pub fn unauthorized(message: impl Into<String>) -> Self {
        Self::Unauthorized {
            message: message.into(),
        }
    }

    pub fn forbidden(message: impl Into<String>) -> Self {
        Self::Forbidden {
            message: message.into(),
        }
    }

    pub fn not_found(message: impl Into<String>) -> Self {
        Self::NotFound {
            message: message.into(),
        }
    }

    pub fn conflict(message: impl Into<String>) -> Self {
        Self::Conflict {
            message: message.into(),
        }
    }

    pub fn not_implemented(message: impl Into<String>) -> Self {
        Self::NotImplemented {
            message: message.into(),
        }
    }

    pub fn internal() -> Self {
        Self::Internal { details: None }
    }

    fn status_code(&self) -> StatusCode {
        match self {
            Self::BadRequest { .. } => StatusCode::BAD_REQUEST,
            Self::Unauthorized { .. } => StatusCode::UNAUTHORIZED,
            Self::Forbidden { .. } => StatusCode::FORBIDDEN,
            Self::NotFound { .. } => StatusCode::NOT_FOUND,
            Self::Conflict { .. } => StatusCode::CONFLICT,
            Self::NotImplemented { .. } => StatusCode::NOT_IMPLEMENTED,
            Self::Internal { .. } => StatusCode::INTERNAL_SERVER_ERROR,
        }
    }

    fn code(&self) -> &'static str {
        match self {
            Self::BadRequest { .. } => "bad_request",
            Self::Unauthorized { .. } => "unauthorized",
            Self::Forbidden { .. } => "forbidden",
            Self::NotFound { .. } => "not_found",
            Self::Conflict { .. } => "conflict",
            Self::NotImplemented { .. } => "not_implemented",
            Self::Internal { .. } => "internal_error",
        }
    }

    fn message(&self) -> String {
        match self {
            Self::BadRequest { message, .. } => message.clone(),
            Self::Unauthorized { message } => message.clone(),
            Self::Forbidden { message } => message.clone(),
            Self::NotFound { message } => message.clone(),
            Self::Conflict { message } => message.clone(),
            Self::NotImplemented { message } => message.clone(),
            Self::Internal { .. } => "Internal server error".to_string(),
        }
    }

    fn details(&self) -> Option<Value> {
        match self {
            Self::BadRequest { details, .. } => details.clone(),
            Self::Internal { details } => details.clone(),
            _ => None,
        }
    }
}

impl IntoResponse for AppError {
    fn into_response(self) -> Response {
        let body = ErrorEnvelope {
            error: ErrorPayload {
                code: self.code().to_string(),
                message: self.message(),
                details: self.details(),
            },
        };

        (self.status_code(), Json(body)).into_response()
    }
}

impl From<sqlx::Error> for AppError {
    fn from(err: sqlx::Error) -> Self {
        tracing::error!(error = %err, "database error");
        AppError::internal()
    }
}

impl From<anyhow::Error> for AppError {
    fn from(err: anyhow::Error) -> Self {
        tracing::error!(error = %err, "unexpected error");
        AppError::internal()
    }
}
