-- Preserve source events in the same transaction as the local mutation.
-- Do not edit earlier migration checksums or reset user data.
alter table roaming_board_outbox add column event_json jsonb;
alter table roaming_board_settings_outbox add column event_json jsonb;
create sequence roaming_local_clock;
create view roaming_card_event_source as
        select
          o.id,
          o.event_seq,
          o.workspace_id,
          o.board_id,
          o.card_id,
          ae.kind as source_activity_kind,
          ae.entity_type as source_entity_type,
          ae.entity_id as source_entity_id,
          ae.field_mask as source_field_mask,
          n.replica_id as node_replica_id,
          rbc.board_key_base64,
          coalesce(rbc.capability_epoch, w.access_epoch) as capability_epoch,
          case
            when c.deleted_at is not null or t.entity_id is not null then 'card.delete'
            else 'card.put'
          end as roaming_operation,
          case when coalesce(c.deleted_at, t.deleted_at) is null then null else
            to_char(coalesce(c.deleted_at, t.deleted_at) at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"')
          end as deleted_at,
          to_char(o.created_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') as occurred_at,
          (
            floor(extract(epoch from o.created_at) * 1000)::bigint * 1000
            + (o.event_seq % 1000)
          ) as logical_clock,
          jsonb_build_object(
            'id', c.id::text,
            'boardId', c.board_id::text,
            'columnId', c.column_id::text,
            'parentCardId', c.parent_card_id::text,
            'title', c.title,
            'description', c.description,
            'priority', c.priority,
            'position', c.position::double precision,
            'startAt', case when c.start_at is null then null else to_char(c.start_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') end,
            'dueAt', case when c.due_at is null then null else to_char(c.due_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') end,
            'isArchived', c.archived_at is not null,
            'labelIds', '[]'::jsonb,
            'checklistCount', (
              select count(*)::bigint
              from checklists ch
              where ch.card_id = c.id and ch.deleted_at is null
            ),
            'checklistItemCount', (
              select count(*)::bigint
              from checklist_items chi
              join checklists ch on ch.id = chi.checklist_id
              where ch.card_id = c.id and ch.deleted_at is null and chi.deleted_at is null
            ),
            'checklistCompletedItemCount', (
              select count(*)::bigint
              from checklist_items chi
              join checklists ch on ch.id = chi.checklist_id
              where ch.card_id = c.id
                and ch.deleted_at is null
                and chi.deleted_at is null
                and chi.is_done = true
            ),
            'commentCount', 0,
            'createdByUserId', c.created_by_user_id::text,
            'createdAt', to_char(c.created_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"'),
            'updatedAt', to_char(c.updated_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"'),
            'archivedAt', case when c.archived_at is null then null else to_char(c.archived_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') end
          ) as card,
          coalesce((
            select jsonb_agg(
              jsonb_build_object(
                'id', ch.id::text,
                'cardId', ch.card_id::text,
                'title', ch.title,
                'position', ch.position::double precision,
                'items', coalesce((
                  select jsonb_agg(
                    jsonb_build_object(
                      'id', chi.id::text,
                      'checklistId', chi.checklist_id::text,
                      'title', chi.title,
                      'isDone', chi.is_done,
                      'position', chi.position::double precision,
                      'completedAt', case when chi.completed_at is null then null else to_char(chi.completed_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') end,
                      'createdAt', to_char(chi.created_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"'),
                      'updatedAt', to_char(chi.updated_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"')
                    )
                    order by chi.position, chi.id
                  )
                  from checklist_items chi
                  where chi.checklist_id = ch.id and chi.deleted_at is null
                ), '[]'::jsonb),
                'createdAt', to_char(ch.created_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"'),
                'updatedAt', to_char(ch.updated_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"')
              )
              order by ch.position, ch.id
            )
            from checklists ch
            where ch.card_id = c.id and ch.deleted_at is null
          ), '[]'::jsonb) as checklists
        from roaming_board_outbox o
        join cards c on c.id = o.card_id
        join workspaces w on w.id = o.workspace_id and w.deleted_at is null
        left join activity_entries ae on ae.id = o.source_activity_id
        cross join local_node_identity n
        left join roaming_board_capabilities rbc on rbc.board_id = o.board_id
        left join tombstones t
          on t.entity_type = 'card'
         and t.entity_id = o.card_id
;
create view roaming_appearance_event_source as
        select
          o.id,
          o.event_seq,
          o.workspace_id,
          o.board_id,
          n.replica_id as node_replica_id,
          rbc.board_key_base64,
          coalesce(rbc.capability_epoch, w.access_epoch) as capability_epoch,
          to_char(o.created_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') as occurred_at,
          (
            floor(extract(epoch from o.created_at) * 1000)::bigint * 1000
            + (o.event_seq % 1000)
          ) as logical_clock,
          jsonb_build_object(
            'boardId', b.id::text,
            'isCustomized', a.board_id is not null,
            'themePreset', coalesce(a.theme_preset, 'system'),
            'wallpaper', jsonb_build_object(
              'kind', coalesce(a.wallpaper_kind, 'none'),
              'value', a.wallpaper_value
            ),
            'columnDensity', coalesce(a.column_density, 'comfortable'),
            'cardPreviewMode', coalesce(a.card_preview_mode, 'expanded'),
            'showCardDescription', coalesce(a.show_card_description, true),
            'showCardDates', coalesce(a.show_card_dates, true),
            'showChecklistProgress', coalesce(a.show_checklist_progress, true),
            'customProperties', coalesce(a.custom_properties_jsonb, '{}'::jsonb),
            'createdAt', case when a.created_at is null then null else to_char(a.created_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') end,
            'updatedAt', case when a.updated_at is null then null else to_char(a.updated_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') end
          ) as appearance
        from roaming_board_settings_outbox o
        join boards b on b.id = o.board_id and b.deleted_at is null
        join workspaces w on w.id = b.workspace_id and w.deleted_at is null
        left join board_appearance_settings a on a.board_id = o.board_id
        cross join local_node_identity n
        left join roaming_board_capabilities rbc on rbc.board_id = o.board_id
;

create or replace function freeze_roaming_outbox() returns trigger language plpgsql as $$
declare
  r record; e jsonb; delta jsonb; payload jsonb; fields text[];
  checklist jsonb; item jsonb; parent jsonb; root_chain jsonb;
  clock bigint; event_epoch bigint; replica uuid; target uuid; f text; stamp_fields text[];
  prefix text; op text; entity_kind text; emitted_id uuid;
begin
  if new.event_json is not null then return new; end if;
  -- Legacy rows may have published another payload under their old id.
  emitted_id := case when TG_OP='INSERT' then new.id else gen_random_uuid() end;
  if TG_TABLE_NAME = 'roaming_board_outbox' then
    select * into r from roaming_card_event_source where id=new.id;
    if not found then return new; end if;
    event_epoch := r.capability_epoch; replica := r.node_replica_id;
    op := r.roaming_operation; entity_kind := 'card'; target := new.card_id;
    fields := case when op='card.delete' then array['__lifecycle']
      when r.source_activity_kind is null or r.source_activity_kind like '%.created' then array['*']
      else coalesce(r.source_field_mask,array['*']) end;
    if r.source_entity_type in ('checklist','checklist_item') then
      fields := array['checklists'];
      if r.source_entity_type='checklist' then
        select value into checklist from jsonb_array_elements(r.checklists) where value->>'id'=r.source_entity_id::text;
        if checklist is null or r.source_activity_kind like '%.deleted' then
          delta := jsonb_build_object('kind','checklist.delete','cardId',new.card_id,'checklistId',r.source_entity_id,'fieldMask',array['__lifecycle'],'deletedAt',r.occurred_at);
        else
          delta := jsonb_build_object('kind','checklist.put','cardId',new.card_id,'checklistId',r.source_entity_id,'checklist',checklist,
            'fieldMask',case when r.source_activity_kind like '%.created' then array['*'] else r.source_field_mask end);
        end if;
      else
        select c.value,i.value into parent,item from jsonb_array_elements(r.checklists) c,
          lateral jsonb_array_elements(c.value->'items') i where i.value->>'id'=r.source_entity_id::text;
        if item is null or r.source_activity_kind like '%.deleted' then
          delta := jsonb_build_object('kind','checklist_item.delete','cardId',new.card_id,'itemId',r.source_entity_id,'fieldMask',array['__lifecycle'],'deletedAt',r.occurred_at);
        else
          delta := jsonb_build_object('kind','checklist_item.put','cardId',new.card_id,'checklistId',parent->>'id','itemId',r.source_entity_id,'item',item,
            'fieldMask',case when r.source_activity_kind like '%.created' then array['*'] else r.source_field_mask end);
        end if;
      end if;
    end if;
    payload := case when op='card.delete' then jsonb_build_object('deletedAt',r.deleted_at)
      when delta is not null then jsonb_build_object('card',r.card,'checklistDelta',delta)
      when '*'=any(fields) then jsonb_build_object('card',r.card,'checklists',r.checklists)
      else jsonb_build_object('card',r.card) end;
  else
    select * into r from roaming_appearance_event_source where id=new.id;
    if not found then return new; end if;
    event_epoch := r.capability_epoch; replica := r.node_replica_id;
    op := 'board.appearance.put'; entity_kind := 'board'; target := new.board_id;
    fields := array['appearance']; payload := jsonb_build_object('appearance',r.appearance);
  end if;
  -- A Lamport step also covers received future/skewed peer clocks.
  perform pg_advisory_xact_lock(hashtextextended('p2pkanban-roaming-clock',0));
  select greatest(floor(extract(epoch from clock_timestamp())*1000000)::bigint,
    coalesce(max(logical_clock),0)+1,nextval('roaming_local_clock')) into clock from roaming_board_events;
  select chain_json into root_chain from roaming_device_grants where board_id=new.board_id and roaming_device_grants.epoch=event_epoch;
  if root_chain is not null then payload := payload || jsonb_build_object('_deviceDelegation',root_chain); end if;
  e := jsonb_build_object('protocolVersion','p2p-kanban-roaming/1','eventId',emitted_id,'workspaceId',new.workspace_id,
    'boardId',new.board_id,'capabilityEpoch',event_epoch,'replicaId',replica,'replicaSeq',clock,'logicalClock',clock,
    'entityType',entity_kind,'entityId',target,'operation',op,'fieldMask',fields,'payload',payload,'occurredAt',r.occurred_at);
  if TG_TABLE_NAME='roaming_board_outbox' then
    update roaming_board_outbox set event_json=e where id=new.id;
  else
    update roaming_board_settings_outbox set event_json=e where id=new.id;
  end if;
  insert into roaming_board_events(event_id,nostr_event_id,author_public_key,workspace_id,board_id,replica_id,replica_seq,
    logical_clock,entity_id,operation,status,capability_epoch,actor_user_id)
    select emitted_id,'local:'||emitted_id::text,'local',new.workspace_id,new.board_id,replica,clock,clock,target,op,'applied',event_epoch,w.owner_user_id
    from workspaces w where w.id=new.workspace_id on conflict(event_id) do nothing;
  if delta is not null then
    prefix := case when delta->>'kind' like 'checklist_item.%' then 'checklist_item.' else 'checklist.' end;
    target := coalesce(delta->>'itemId',delta->>'checklistId')::uuid;
    select array_agg(value) into stamp_fields from jsonb_array_elements_text(delta->'fieldMask');
    if '*'=any(stamp_fields) then stamp_fields := case when prefix='checklist_item.' then array['title','position','isDone','__lifecycle'] else array['title','position','__lifecycle'] end; end if;
  else
    prefix := '';
    stamp_fields := case when entity_kind='board' then array['board.appearance']
      when '*'=any(fields) then array['columnId','parentCardId','title','description','priority','position','startAt','dueAt','isArchived','checklists']
      else fields end;
  end if;
  foreach f in array coalesce(stamp_fields,array[]::text[]) loop
    insert into roaming_field_versions(workspace_id,entity_id,field_name,logical_clock,replica_id,event_id)
      values(new.workspace_id,target,prefix||f,clock,replica,emitted_id)
      on conflict(workspace_id,entity_id,field_name) do update set
        logical_clock=excluded.logical_clock,replica_id=excluded.replica_id,event_id=excluded.event_id,updated_at=now();
  end loop;
  return new;
end $$;
create trigger trg_freeze_roaming_card after insert or update of status on roaming_board_outbox for each row execute function freeze_roaming_outbox();
create trigger trg_freeze_roaming_appearance after insert or update of status on roaming_board_settings_outbox for each row execute function freeze_roaming_outbox();

-- Durable baselines make a known board recoverable without HTTP to its creator.
create table roaming_board_baselines (
  board_id uuid primary key references boards(id) on delete cascade,
  fingerprint text not null,
  event_json jsonb not null,
  delivered boolean not null default false
);
create function roaming_camel_row(value jsonb) returns jsonb language sql immutable as $$
  select coalesce(jsonb_object_agg(
    parts[1] || coalesce((select string_agg(upper(left(p,1))||substr(p,2),'') from unnest(parts[2:]) p),''),
    val), '{}'::jsonb)
  from (select string_to_array(key,'_') parts, v.value val from jsonb_each(value) v) entries;
$$;
create function roaming_board_snapshot(wanted uuid) returns jsonb language sql stable as $$
select jsonb_build_object('schemaVersion',6,'workspaceId',b.workspace_id,'board',roaming_camel_row(to_jsonb(b))||jsonb_build_object('isArchived',b.archived_at is not null),
  'columns',coalesce((select jsonb_agg(roaming_camel_row(to_jsonb(col)) order by col.position,col.id) from board_columns col where col.board_id=b.id and col.deleted_at is null),'[]'::jsonb),
  'cards',coalesce((select jsonb_agg(roaming_camel_row(to_jsonb(c))||jsonb_build_object('isArchived',c.archived_at is not null,'labelIds','[]'::jsonb) order by c.id) from cards c where c.board_id=b.id and c.deleted_at is null),'[]'::jsonb),
  'checklistsByCardId',coalesce((select jsonb_object_agg(c.id::text,coalesce((
    select jsonb_agg(roaming_camel_row(to_jsonb(ch))||jsonb_build_object('items',coalesce((
      select jsonb_agg(roaming_camel_row(to_jsonb(i)) order by i.position,i.id) from checklist_items i where i.checklist_id=ch.id and i.deleted_at is null),'[]'::jsonb)) order by ch.position,ch.id)
    from checklists ch where ch.card_id=c.id and ch.deleted_at is null),'[]'::jsonb)) from cards c where c.board_id=b.id and c.deleted_at is null),'{}'::jsonb),
  'checklistsHydratedAt',b.updated_at,'cachedAt',b.updated_at,'lastServerRefreshAt',null)
from boards b where b.id=wanted and b.deleted_at is null;
$$;
