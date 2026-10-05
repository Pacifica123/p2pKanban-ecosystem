use serde_json::Value;
use uuid::Uuid;

use crate::{
    error::{AppError, AppResult},
    modules::common::trim_to_option,
    state::AppState,
};

use super::dto::{
    BoardAppearanceResponse, UpdateBoardAppearanceRequest, UpdateUserAppearancePreferencesRequest,
    UserAppearancePreferencesResponse,
};

const APP_THEMES: &[&str] = &["system", "light", "dark"];
const DENSITIES: &[&str] = &["comfortable", "compact"];
const WALLPAPER_KINDS: &[&str] = &["none", "accent", "solid", "gradient", "preset", "image"];
const CARD_PREVIEW_MODES: &[&str] = &["compact", "expanded"];
const CHECKLIST_ITEM_SUBMIT_MODES: &[&str] = &["ctrl_enter", "enter", "button"];
const CARD_DETAILS_MODES: &[&str] = &["drawer", "modal"];

fn normalize_choice(
    value: Option<String>,
    allowed: &[&str],
    field_name: &str,
) -> AppResult<Option<String>> {
    let Some(value) = value else {
        return Ok(None);
    };

    let normalized = value.trim().to_ascii_lowercase();
    if normalized.is_empty() {
        return Err(AppError::bad_request(format!(
            "{field_name} cannot be empty"
        )));
    }
    if !allowed.contains(&normalized.as_str()) {
        return Err(AppError::bad_request(format!(
            "{field_name} has unsupported value"
        )));
    }
    Ok(Some(normalized))
}

fn normalize_theme_preset(value: Option<String>) -> AppResult<Option<String>> {
    let Some(value) = value else {
        return Ok(None);
    };

    let trimmed = value.trim();
    if trimmed.is_empty() {
        return Err(AppError::bad_request("themePreset cannot be empty"));
    }
    if trimmed.len() > 100 {
        return Err(AppError::bad_request("themePreset is too long"));
    }
    Ok(Some(trimmed.to_string()))
}

fn normalize_custom_properties(value: Option<Value>) -> AppResult<Option<Value>> {
    let Some(value) = value else {
        return Ok(None);
    };

    if !value.is_object() {
        return Err(AppError::bad_request(
            "customProperties must be a JSON object",
        ));
    }
    if let Some(accent_color) = value.get("accentColor") {
        let is_hex_color = accent_color
            .as_str()
            .map(|color| {
                color.len() == 7
                    && color.starts_with('#')
                    && color[1..]
                        .chars()
                        .all(|character| character.is_ascii_hexdigit())
            })
            .unwrap_or(false);
        if !is_hex_color {
            return Err(AppError::bad_request(
                "customProperties.accentColor must be a #RRGGBB color",
            ));
        }
    }
    Ok(Some(value))
}

pub async fn get_my_preferences(
    state: &AppState,
    actor_user_id: Uuid,
) -> AppResult<UserAppearancePreferencesResponse> {
    super::repo::get_my_preferences(&state.db, actor_user_id).await
}

pub async fn upsert_my_preferences(
    state: &AppState,
    actor_user_id: Uuid,
    payload: UpdateUserAppearancePreferencesRequest,
) -> AppResult<UserAppearancePreferencesResponse> {
    let app_theme = normalize_choice(payload.app_theme, APP_THEMES, "appTheme")?;
    let density = normalize_choice(payload.density, DENSITIES, "density")?;
    let checklist_item_submit_mode = normalize_choice(
        payload.checklist_item_submit_mode,
        CHECKLIST_ITEM_SUBMIT_MODES,
        "checklistItemSubmitMode",
    )?;
    let card_details_mode = normalize_choice(
        payload.card_details_mode,
        CARD_DETAILS_MODES,
        "cardDetailsMode",
    )?;

    super::repo::upsert_my_preferences(
        &state.db,
        actor_user_id,
        app_theme,
        density,
        payload.reduce_motion,
        checklist_item_submit_mode,
        card_details_mode,
    )
    .await
}

pub async fn get_board_appearance(
    state: &AppState,
    actor_user_id: Uuid,
    board_id: Uuid,
) -> AppResult<BoardAppearanceResponse> {
    super::repo::get_board_appearance(&state.db, actor_user_id, board_id).await
}

pub async fn upsert_board_appearance(
    state: &AppState,
    actor_user_id: Uuid,
    board_id: Uuid,
    payload: UpdateBoardAppearanceRequest,
) -> AppResult<BoardAppearanceResponse> {
    let theme_preset = normalize_theme_preset(payload.theme_preset)?;
    let column_density = normalize_choice(payload.column_density, DENSITIES, "columnDensity")?;
    let card_preview_mode = normalize_choice(
        payload.card_preview_mode,
        CARD_PREVIEW_MODES,
        "cardPreviewMode",
    )?;
    let custom_properties = normalize_custom_properties(payload.custom_properties)?;

    let (wallpaper_changed, wallpaper_kind, wallpaper_value) = match payload.wallpaper {
        Some(wallpaper) => {
            let kind = normalize_choice(Some(wallpaper.kind), WALLPAPER_KINDS, "wallpaper.kind")?
                .expect("validated wallpaper kind");
            let value = match kind.as_str() {
                "none" | "accent" => None,
                _ => {
                    let value = trim_to_option(wallpaper.value);
                    if value.is_none() {
                        return Err(AppError::bad_request(
                            "wallpaper.value is required for non-none wallpapers",
                        ));
                    }
                    if kind == "image" {
                        let image_url = value.as_deref().unwrap_or_default();
                        if image_url.len() > 2_048
                            || image_url.contains('\r')
                            || image_url.contains('\n')
                            || !(image_url.starts_with("https://")
                                || image_url.starts_with("http://"))
                        {
                            return Err(AppError::bad_request(
                                "wallpaper image must be an http(s) URL up to 2048 characters",
                            ));
                        }
                    }
                    value
                }
            };
            (true, Some(kind), value)
        }
        None => (false, None, None),
    };

    super::repo::upsert_board_appearance(
        &state.db,
        actor_user_id,
        board_id,
        theme_preset,
        wallpaper_changed,
        wallpaper_kind,
        wallpaper_value,
        column_density,
        card_preview_mode,
        payload.show_card_description,
        payload.show_card_dates,
        payload.show_checklist_progress,
        custom_properties,
    )
    .await
}
