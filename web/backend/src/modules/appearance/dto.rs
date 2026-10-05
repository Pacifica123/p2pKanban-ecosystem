use serde::{Deserialize, Serialize};
use serde_json::Value;

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct UpdateUserAppearancePreferencesRequest {
    pub app_theme: Option<String>,
    pub density: Option<String>,
    pub reduce_motion: Option<bool>,
    pub checklist_item_submit_mode: Option<String>,
    pub card_details_mode: Option<String>,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct WallpaperInput {
    pub kind: String,
    #[serde(default)]
    pub value: Option<String>,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct UpdateBoardAppearanceRequest {
    pub theme_preset: Option<String>,
    pub wallpaper: Option<WallpaperInput>,
    pub column_density: Option<String>,
    pub card_preview_mode: Option<String>,
    pub show_card_description: Option<bool>,
    pub show_card_dates: Option<bool>,
    pub show_checklist_progress: Option<bool>,
    pub custom_properties: Option<Value>,
}

#[derive(Debug, Serialize, Clone)]
#[serde(rename_all = "camelCase")]
pub struct WallpaperResponse {
    pub kind: String,
    pub value: Option<String>,
}

#[derive(Debug, Serialize, Clone)]
#[serde(rename_all = "camelCase")]
pub struct UserAppearancePreferencesResponse {
    pub user_id: String,
    pub is_customized: bool,
    pub app_theme: String,
    pub density: String,
    pub reduce_motion: bool,
    pub checklist_item_submit_mode: String,
    pub card_details_mode: String,
    pub created_at: Option<String>,
    pub updated_at: Option<String>,
}

#[derive(Debug, Serialize, Clone)]
#[serde(rename_all = "camelCase")]
pub struct BoardAppearanceResponse {
    pub board_id: String,
    pub is_customized: bool,
    pub theme_preset: String,
    pub wallpaper: WallpaperResponse,
    pub column_density: String,
    pub card_preview_mode: String,
    pub show_card_description: bool,
    pub show_card_dates: bool,
    pub show_checklist_progress: bool,
    pub custom_properties: Value,
    pub created_at: Option<String>,
    pub updated_at: Option<String>,
}
