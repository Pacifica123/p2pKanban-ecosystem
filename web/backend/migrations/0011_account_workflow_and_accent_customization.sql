alter table user_appearance_preferences
  add column if not exists checklist_item_submit_mode text not null default 'ctrl_enter',
  add column if not exists card_details_mode text not null default 'drawer';

alter table user_appearance_preferences
  drop constraint if exists chk_user_appearance_preferences_checklist_item_submit_mode;

alter table user_appearance_preferences
  add constraint chk_user_appearance_preferences_checklist_item_submit_mode
  check (checklist_item_submit_mode in ('ctrl_enter', 'enter', 'button'));

alter table user_appearance_preferences
  drop constraint if exists chk_user_appearance_preferences_card_details_mode;

alter table user_appearance_preferences
  add constraint chk_user_appearance_preferences_card_details_mode
  check (card_details_mode in ('drawer', 'modal'));

alter table board_appearance_settings
  drop constraint if exists chk_board_appearance_settings_wallpaper_kind;

alter table board_appearance_settings
  add constraint chk_board_appearance_settings_wallpaper_kind
  check (wallpaper_kind in ('none', 'accent', 'solid', 'gradient', 'preset', 'image'));

alter table board_appearance_settings
  drop constraint if exists chk_board_appearance_settings_wallpaper_value_shape;

alter table board_appearance_settings
  add constraint chk_board_appearance_settings_wallpaper_value_shape
  check (
    (wallpaper_kind in ('none', 'accent') and wallpaper_value is null)
    or
    (
      wallpaper_kind not in ('none', 'accent')
      and wallpaper_value is not null
      and btrim(wallpaper_value) <> ''
    )
  );
