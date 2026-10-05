-- A compacted snapshot can carry a field stamp whose original event has not
-- arrived locally. Keep the signed origin id without marking that unseen event
-- as applied (doing so would suppress its later delta).
alter table roaming_field_versions drop constraint if exists roaming_field_versions_event_id_fkey;

-- Independent immutable history delivery: includes actions without a roaming
-- state operation (comments, labels, columns). A relay retry keeps the same event.
create table roaming_activity_outbox (
  activity_id uuid not null references activity_entries(id) on delete cascade,
  capability_epoch bigint not null check(capability_epoch>0),
  event_json jsonb not null,
  delivered boolean not null default false,
  next_attempt_at timestamptz not null default now(),
  primary key(activity_id,capability_epoch)
);
create index idx_roaming_activity_ready on roaming_activity_outbox(next_attempt_at) where not delivered;

-- Recovery snapshots carry the original per-field versions. Never turn the
-- publication timestamp into an authority over a newer local edit.
create function merge_roaming_checklist_versions(wanted_workspace uuid, wanted_board uuid, snapshot jsonb, versions jsonb)
returns void language plpgsql as $$
declare
  card record; ch jsonb; item jsonb; entity jsonb; v jsonb;
  wanted_entity uuid; field text; prefix text; table_name text; current_version record;
  incoming_clock bigint; incoming_replica uuid; incoming_event uuid; pair record;
begin
  for card in select key,value from jsonb_each(snapshot->'checklistsByCardId') loop
    if not exists(select 1 from cards where id=card.key::uuid and board_id=wanted_board and deleted_at is null) then continue; end if;
    for ch in select value from jsonb_array_elements(card.value) loop
      for entity,prefix,table_name in
        select ch,'checklist.','checklists'
        union all select value,'checklist_item.','checklist_items' from jsonb_array_elements(ch->'items')
      loop
        wanted_entity := (entity->>'id')::uuid;
        for field in select unnest(case when prefix='checklist.' then array['title','position','__lifecycle'] else array['title','position','isDone','__lifecycle'] end) loop
          v := versions->(wanted_entity::text||':'||prefix||field);
          if v is null then continue; end if;
          incoming_clock := (v->>'logicalClock')::bigint;
          incoming_replica := (v->>'replicaId')::uuid; incoming_event := (v->>'eventId')::uuid;
          if incoming_clock<0 then raise exception 'invalid snapshot clock'; end if;
          select logical_clock,replica_id,event_id into current_version from roaming_field_versions
            where workspace_id=wanted_workspace and roaming_field_versions.entity_id=wanted_entity and field_name=prefix||field;
          if found and (incoming_clock,incoming_replica,incoming_event)<=(current_version.logical_clock,current_version.replica_id,current_version.event_id) then continue; end if;
          if table_name='checklists' then
            update checklists set
              title=case when field='title' then entity->>'title' else title end,
              position=case when field='position' then (entity->>'position')::double precision else position end,
              deleted_at=case when field='__lifecycle' then null else deleted_at end
            where id=wanted_entity and card_id=card.key::uuid;
          else
            update checklist_items set
              title=case when field='title' then entity->>'title' else title end,
              position=case when field='position' then (entity->>'position')::double precision else position end,
              is_done=case when field='isDone' then (entity->>'isDone')::boolean else is_done end,
              completed_at=case when field='isDone' then case when (entity->>'isDone')::boolean then coalesce(completed_at,now()) else null end else completed_at end,
              deleted_at=case when field='__lifecycle' then null else deleted_at end
            where id=wanted_entity and checklist_id=(ch->>'id')::uuid;
          end if;
          insert into roaming_field_versions(workspace_id,entity_id,field_name,logical_clock,replica_id,event_id)
            values(wanted_workspace,wanted_entity,prefix||field,incoming_clock,incoming_replica,incoming_event)
            on conflict(workspace_id,entity_id,field_name) do update set logical_clock=excluded.logical_clock,replica_id=excluded.replica_id,event_id=excluded.event_id,updated_at=now();
        end loop;
      end loop;
    end loop;
  end loop;
  -- Absence is only a deletion with a signed explicit lifecycle stamp.
  for pair in select key,value from jsonb_each(versions) where key like '%:checklist%.__lifecycle' loop
    wanted_entity := split_part(pair.key,':',1)::uuid; prefix := split_part(pair.key,':',2);
    if prefix='checklist.__lifecycle' then
      if not exists(select 1 from checklists stored_list join cards c on c.id=stored_list.card_id where stored_list.id=wanted_entity and c.board_id=wanted_board) then continue; end if;
      if exists(select 1 from jsonb_each(snapshot->'checklistsByCardId') c,lateral jsonb_array_elements(c.value) json_list where json_list->>'id'=wanted_entity::text) then continue; end if;
    elsif prefix='checklist_item.__lifecycle' then
      if not exists(select 1 from checklist_items i join checklists stored_list on stored_list.id=i.checklist_id join cards c on c.id=stored_list.card_id where i.id=wanted_entity and c.board_id=wanted_board) then continue; end if;
      if exists(select 1 from jsonb_each(snapshot->'checklistsByCardId') c,lateral jsonb_array_elements(c.value) json_list,lateral jsonb_array_elements(json_list->'items') i where i->>'id'=wanted_entity::text) then continue; end if;
    else continue; end if;
    incoming_clock := (pair.value->>'logicalClock')::bigint;incoming_replica := (pair.value->>'replicaId')::uuid;incoming_event := (pair.value->>'eventId')::uuid;
    select logical_clock,replica_id,event_id into current_version from roaming_field_versions where workspace_id=wanted_workspace and roaming_field_versions.entity_id=wanted_entity and field_name=prefix;
    if found and (incoming_clock,incoming_replica,incoming_event)<=(current_version.logical_clock,current_version.replica_id,current_version.event_id) then continue; end if;
    if prefix='checklist.__lifecycle' then update checklists set deleted_at=coalesce(deleted_at,now()) where id=wanted_entity;
    else update checklist_items set deleted_at=coalesce(deleted_at,now()) where id=wanted_entity; end if;
    insert into roaming_field_versions(workspace_id,entity_id,field_name,logical_clock,replica_id,event_id)
      values(wanted_workspace,wanted_entity,prefix,incoming_clock,incoming_replica,incoming_event)
      on conflict(workspace_id,entity_id,field_name) do update set logical_clock=excluded.logical_clock,replica_id=excluded.replica_id,event_id=excluded.event_id,updated_at=now();
  end loop;
end $$;
