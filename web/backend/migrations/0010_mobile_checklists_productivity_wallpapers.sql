alter table board_appearance_settings
  drop constraint if exists chk_board_appearance_settings_wallpaper_kind;

alter table board_appearance_settings
  add constraint chk_board_appearance_settings_wallpaper_kind
  check (wallpaper_kind in ('none', 'solid', 'gradient', 'preset', 'image'));

create or replace function enqueue_roaming_card_activity()
returns trigger language plpgsql as $$
begin
  if new.entity_type in ('card', 'checklist', 'checklist_item')
     and new.card_id is not null then
    insert into roaming_board_outbox (
      id,
      source_key,
      source_activity_id,
      workspace_id,
      board_id,
      card_id
    ) values (
      gen_random_uuid(),
      'activity:' || new.id::text,
      new.id,
      new.workspace_id,
      new.board_id,
      new.card_id
    )
    on conflict (source_key) do nothing;
  end if;
  return new;
end;
$$;
