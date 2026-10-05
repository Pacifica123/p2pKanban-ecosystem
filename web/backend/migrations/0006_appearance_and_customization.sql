create table if not exists user_appearance_preferences (
  user_id uuid primary key references users(id) on delete cascade,
  app_theme text not null default 'system',
  density text not null default 'comfortable',
  reduce_motion boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint chk_user_appearance_preferences_app_theme
    check (app_theme in ('system', 'light', 'dark')),
  constraint chk_user_appearance_preferences_density
    check (density in ('comfortable', 'compact'))
);

create trigger trg_user_appearance_preferences_updated_at
before update on user_appearance_preferences
for each row execute function set_row_updated_at();

create table if not exists board_appearance_settings (
  board_id uuid primary key references boards(id) on delete cascade,
  theme_preset text not null default 'system',
  wallpaper_kind text not null default 'none',
  wallpaper_value text null,
  column_density text not null default 'comfortable',
  card_preview_mode text not null default 'expanded',
  show_card_description boolean not null default true,
  show_card_dates boolean not null default true,
  show_checklist_progress boolean not null default true,
  custom_properties_jsonb jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint chk_board_appearance_settings_wallpaper_kind
    check (wallpaper_kind in ('none', 'solid', 'gradient', 'preset')),
  constraint chk_board_appearance_settings_column_density
    check (column_density in ('comfortable', 'compact')),
  constraint chk_board_appearance_settings_card_preview_mode
    check (card_preview_mode in ('compact', 'expanded')),
  constraint chk_board_appearance_settings_wallpaper_value_shape
    check (
      (wallpaper_kind = 'none' and wallpaper_value is null)
      or
      (wallpaper_kind <> 'none' and wallpaper_value is not null and btrim(wallpaper_value) <> '')
    ),
  constraint chk_board_appearance_settings_custom_properties_object
    check (jsonb_typeof(custom_properties_jsonb) = 'object')
);

create trigger trg_board_appearance_settings_updated_at
before update on board_appearance_settings
for each row execute function set_row_updated_at();
