create unique index if not exists inbox_items_household_id_id_key
    on public.inbox_items(household_id, id);

create table if not exists public.inbox_suggestions (
    id uuid primary key default gen_random_uuid(),
    household_id uuid not null references public.households(id) on delete cascade,
    inbox_item_id uuid not null,
    foreign key (household_id, inbox_item_id) references public.inbox_items(household_id, id) on delete cascade,
    suggestion_type text not null check (suggestion_type in ('task', 'event', 'meal', 'grocery', 'note')),
    proposed_payload jsonb not null check (jsonb_typeof(proposed_payload) = 'object'),
    status text not null default 'pending' check (status in ('pending', 'accepted', 'rejected')),
    created_by uuid not null references auth.users(id) on delete restrict,
    reviewed_by uuid references auth.users(id) on delete set null,
    reviewed_at timestamptz,
    created_at timestamptz not null default timezone('utc', now()),
    updated_at timestamptz not null default timezone('utc', now()),
    unique (inbox_item_id)
);

create index if not exists inbox_suggestions_household_status_idx
    on public.inbox_suggestions(household_id, status, created_at desc);

insert into public.inbox_suggestions (household_id, inbox_item_id, suggestion_type, proposed_payload, created_by)
select household_id, id, 'task', jsonb_build_object('title', original_text), created_by
from public.inbox_items
where status = 'open'
on conflict (inbox_item_id) do nothing;

alter table public.inbox_suggestions enable row level security;

drop policy if exists inbox_suggestions_member_select on public.inbox_suggestions;
create policy inbox_suggestions_member_select on public.inbox_suggestions
for select to authenticated
using (
    private.is_household_member(household_id)
    and exists (
        select 1
        from public.inbox_items item
        where item.id = inbox_suggestions.inbox_item_id
          and (not item.private or item.created_by = (select auth.uid()))
    )
);

revoke all on public.inbox_suggestions from public, anon, authenticated, service_role;
grant select on public.inbox_suggestions to authenticated;

create or replace function public.create_inbox_capture(
    p_household_id uuid,
    p_actor_user_id uuid,
    p_original_text text,
    p_source text,
    p_private boolean,
    p_suggestion_type text,
    p_proposed_payload jsonb
)
returns jsonb
language plpgsql
security definer
set search_path = public, private, extensions
as $$
declare
    actor_membership public.memberships;
    capture_row public.inbox_items;
    suggestion_row public.inbox_suggestions;
begin
    if (auth.uid() is null and coalesce(auth.role(), '') <> 'service_role')
       or (auth.uid() is not null and auth.uid() <> p_actor_user_id) then
        raise exception 'authenticated actor required' using errcode = '42501';
    end if;
    select * into actor_membership
    from public.memberships
    where household_id = p_household_id and user_id = p_actor_user_id
    for update;
    if not found then
        raise exception 'household membership required' using errcode = '42501';
    end if;
    if char_length(trim(coalesce(p_original_text, ''))) not between 1 and 4000 then
        raise exception 'original text is required' using errcode = '22023';
    end if;
    if char_length(trim(coalesce(p_source, ''))) not between 1 and 80 then
        raise exception 'source is invalid' using errcode = '22023';
    end if;
    if p_suggestion_type not in ('task', 'event', 'meal', 'grocery', 'note') then
        raise exception 'suggestion type is invalid' using errcode = '22023';
    end if;
    if p_proposed_payload is null or jsonb_typeof(p_proposed_payload) <> 'object' then
        raise exception 'suggestion payload must be an object' using errcode = '22023';
    end if;
    if pg_column_size(p_proposed_payload) > 16384 then
        raise exception 'suggestion payload is too large' using errcode = '22023';
    end if;

    insert into public.inbox_items (household_id, original_text, source, private, created_by)
    values (p_household_id, trim(p_original_text), trim(p_source), coalesce(p_private, false), p_actor_user_id)
    returning * into capture_row;

    insert into public.inbox_suggestions (household_id, inbox_item_id, suggestion_type, proposed_payload, created_by)
    values (p_household_id, capture_row.id, p_suggestion_type, p_proposed_payload, p_actor_user_id)
    returning * into suggestion_row;

    insert into public.activity_log (household_id, actor, action, entity_type, entity_id, before_json, after_json)
    values (
        p_household_id,
        p_actor_user_id,
        'inbox.created',
        'inbox',
        capture_row.id,
        null,
        jsonb_build_object('source', capture_row.source, 'private', capture_row.private, 'has_suggestion', true)
    );

    return jsonb_build_object('item', to_jsonb(capture_row), 'suggestion', to_jsonb(suggestion_row));
end;
$$;

revoke all on function public.create_inbox_capture(uuid, uuid, text, text, boolean, text, jsonb) from public, anon;
grant execute on function public.create_inbox_capture(uuid, uuid, text, text, boolean, text, jsonb) to authenticated, service_role;

create or replace function public.read_inbox_snapshot(
    p_household_id uuid,
    p_actor_user_id uuid
)
returns jsonb
language plpgsql
security definer
set search_path = public, private, extensions
as $$
declare
    actor_membership public.memberships;
    snapshot jsonb;
begin
    if (auth.uid() is null and coalesce(auth.role(), '') <> 'service_role')
       or (auth.uid() is not null and auth.uid() <> p_actor_user_id) then
        raise exception 'authenticated actor required' using errcode = '42501';
    end if;
    select * into actor_membership
    from public.memberships
    where household_id = p_household_id and user_id = p_actor_user_id
    for update;
    if not found then
        raise exception 'household membership required' using errcode = '42501';
    end if;

    select coalesce(
        jsonb_agg(
            to_jsonb(snapshot_rows.item_row)
            || jsonb_build_object('suggestion', to_jsonb(snapshot_rows.suggestion_row))
            order by snapshot_rows.created_at desc
        ),
        '[]'::jsonb
    ) into snapshot
    from (
        select item as item_row, suggestion as suggestion_row, item.created_at
        from public.inbox_items item
        left join public.inbox_suggestions suggestion
          on suggestion.household_id = item.household_id
         and suggestion.inbox_item_id = item.id
         and suggestion.status = 'pending'
        where item.household_id = p_household_id
          and item.status = 'open'
          and (not item.private or item.created_by = p_actor_user_id)
        order by item.created_at desc
        limit 100
    ) snapshot_rows;
    return snapshot;
end;
$$;

revoke all on function public.read_inbox_snapshot(uuid, uuid) from public, anon;
grant execute on function public.read_inbox_snapshot(uuid, uuid) to authenticated, service_role;

create or replace function public.review_inbox_suggestion(
    p_household_id uuid,
    p_actor_user_id uuid,
    p_inbox_item_id uuid,
    p_suggestion_id uuid,
    p_decision text,
    p_suggestion_type text,
    p_proposed_payload jsonb
)
returns jsonb
language plpgsql
security definer
set search_path = public, private, extensions
as $$
declare
    actor_membership public.memberships;
    suggestion_row public.inbox_suggestions;
    reviewed_suggestion public.inbox_suggestions;
    capture_row public.inbox_items;
    reviewed_capture public.inbox_items;
    task_row public.tasks;
    event_row public.events;
    meal_row public.meals;
    grocery_row public.grocery_items;
    payload jsonb;
    effective_type text;
    created_record jsonb;
    created_id uuid;
    created_type text;
    decision_label text;
    title_value text;
    meal_type_value text;
    quantity_value numeric;
begin
    if (auth.uid() is null and coalesce(auth.role(), '') <> 'service_role')
       or (auth.uid() is not null and auth.uid() <> p_actor_user_id) then
        raise exception 'authenticated actor required' using errcode = '42501';
    end if;
    select * into actor_membership
    from public.memberships
    where household_id = p_household_id and user_id = p_actor_user_id
    for update;
    if not found then
        raise exception 'household membership required' using errcode = '42501';
    end if;

    select * into suggestion_row
    from public.inbox_suggestions
    where id = p_suggestion_id
      and household_id = p_household_id
      and inbox_item_id = p_inbox_item_id
    for update;
    if not found then
        raise exception 'suggestion not found' using errcode = 'P0002';
    end if;
    if suggestion_row.status <> 'pending' then
        raise exception 'suggestion has already been reviewed' using errcode = '55006';
    end if;

    select * into capture_row
    from public.inbox_items
    where id = p_inbox_item_id and household_id = p_household_id
    for update;
    if not found then
        raise exception 'inbox item not found' using errcode = 'P0002';
    end if;
    if capture_row.private and capture_row.created_by <> p_actor_user_id then
        raise exception 'private inbox item is not reviewable by this member' using errcode = '42501';
    end if;
    if capture_row.status <> 'open' then
        raise exception 'inbox item has already been resolved' using errcode = '55006';
    end if;

    if p_decision not in ('accept', 'reject') then
        raise exception 'decision must be accept or reject' using errcode = '22023';
    end if;

    if p_decision = 'reject' then
        update public.inbox_suggestions
        set status = 'rejected', reviewed_by = p_actor_user_id, reviewed_at = timezone('utc', now()), updated_at = timezone('utc', now())
        where id = suggestion_row.id
        returning * into reviewed_suggestion;

        update public.inbox_items
        set status = 'archived', resolved_at = timezone('utc', now())
        where id = capture_row.id
        returning * into reviewed_capture;

        insert into public.activity_log (household_id, actor, action, entity_type, entity_id, before_json, after_json)
        values (
            p_household_id,
            p_actor_user_id,
            'inbox.suggestion_rejected',
            'inbox_suggestion',
            suggestion_row.id,
            jsonb_build_object('status', 'pending', 'suggestion_type', suggestion_row.suggestion_type),
            jsonb_build_object('status', 'rejected')
        );
        return jsonb_build_object(
            'decision', 'rejected',
            'suggestion', to_jsonb(reviewed_suggestion),
            'item', to_jsonb(reviewed_capture),
            'created', null,
            'created_type', null
        );
    end if;

    effective_type := coalesce(nullif(trim(p_suggestion_type), ''), suggestion_row.suggestion_type);
    if effective_type not in ('task', 'event', 'meal', 'grocery', 'note') then
        raise exception 'suggestion type is invalid' using errcode = '22023';
    end if;
    if capture_row.private and effective_type not in ('task', 'note') then
        raise exception 'private captures can only become private tasks or notes' using errcode = '42501';
    end if;
    payload := coalesce(p_proposed_payload, suggestion_row.proposed_payload);
    if payload is null or jsonb_typeof(payload) <> 'object' then
        raise exception 'suggestion payload must be an object' using errcode = '22023';
    end if;
    if pg_column_size(payload) > 16384 then
        raise exception 'suggestion payload is too large' using errcode = '22023';
    end if;

    if effective_type = 'task' then
        title_value := trim(coalesce(payload->>'title', ''));
        if char_length(title_value) not between 1 and 500 then
            raise exception 'task title is required' using errcode = '22023';
        end if;
        if payload ? 'private' and jsonb_typeof(payload->'private') not in ('boolean', 'null') then
            raise exception 'task private flag is invalid' using errcode = '22023';
        end if;
        insert into public.tasks (household_id, title, due_at, private, recurrence, created_by)
        values (
            p_household_id,
            title_value,
            nullif(payload->>'due_at', '')::timestamptz,
            case when capture_row.private then true
                 when jsonb_typeof(payload->'private') = 'boolean' then (payload->>'private')::boolean
                 else false end,
            coalesce(nullif(payload->>'recurrence', ''), 'none'),
            p_actor_user_id
        ) returning * into task_row;
        created_record := to_jsonb(task_row);
        created_id := task_row.id;
        created_type := 'task';
    elsif effective_type = 'event' then
        title_value := trim(coalesce(payload->>'title', ''));
        if char_length(title_value) not between 1 and 500 or nullif(payload->>'starts_at', '') is null then
            raise exception 'event title and start are required' using errcode = '22023';
        end if;
        if char_length(coalesce(payload->>'person', '')) > 200 then
            raise exception 'event person is too long' using errcode = '22023';
        end if;
        if nullif(payload->>'ends_at', '') is not null
           and (payload->>'ends_at')::timestamptz < (payload->>'starts_at')::timestamptz then
            raise exception 'event end must not precede start' using errcode = '22023';
        end if;
        insert into public.events (household_id, title, starts_at, ends_at, person, created_by)
        values (
            p_household_id,
            title_value,
            (payload->>'starts_at')::timestamptz,
            nullif(payload->>'ends_at', '')::timestamptz,
            nullif(trim(payload->>'person'), ''),
            p_actor_user_id
        ) returning * into event_row;
        created_record := to_jsonb(event_row);
        created_id := event_row.id;
        created_type := 'event';
    elsif effective_type = 'meal' then
        title_value := trim(coalesce(payload->>'title', ''));
        meal_type_value := lower(trim(coalesce(payload->>'meal_type', 'dinner')));
        if char_length(title_value) not between 1 and 500 or nullif(payload->>'meal_date', '') is null or meal_type_value not in ('breakfast', 'lunch', 'dinner') then
            raise exception 'meal title, date, and meal type are required' using errcode = '22023';
        end if;
        if payload ? 'ingredients' and jsonb_typeof(payload->'ingredients') <> 'array' then
            raise exception 'meal ingredients must be an array' using errcode = '22023';
        end if;
        if jsonb_typeof(payload->'ingredients') = 'array'
           and (jsonb_array_length(payload->'ingredients') > 100
                or exists (
                    select 1
                    from jsonb_array_elements(payload->'ingredients') ingredient
                    where jsonb_typeof(ingredient) <> 'string'
                       or char_length(trim(ingredient #>> '{}')) not between 1 and 200
                )) then
            raise exception 'meal ingredients are invalid' using errcode = '22023';
        end if;
        execute 'select * from public.create_meal($1, $2, $3)'
        into meal_row
        using
            p_household_id,
            p_actor_user_id,
            jsonb_build_object(
                'meal_date', payload->>'meal_date',
                'meal_type', meal_type_value,
                'title', title_value,
                'ingredients', case
                    when jsonb_typeof(payload->'ingredients') = 'array' then payload->'ingredients'
                    else '[]'::jsonb
                end
            );
        created_record := to_jsonb(meal_row);
        created_id := meal_row.id;
        created_type := 'meal';
    elsif effective_type = 'grocery' then
        title_value := trim(coalesce(payload->>'name', ''));
        quantity_value := coalesce(nullif(payload->>'quantity', '')::numeric, 1);
        if char_length(title_value) not between 1 and 300
           or quantity_value <= 0 or quantity_value > 100000
           or char_length(coalesce(payload->>'unit', '')) > 100
           or char_length(coalesce(payload->>'category', '')) > 100 then
            raise exception 'grocery name and quantity are required' using errcode = '22023';
        end if;
        insert into public.grocery_items (household_id, name, quantity, unit, category, created_by)
        values (
            p_household_id,
            title_value,
            quantity_value,
            coalesce(nullif(trim(payload->>'unit'), ''), 'each'),
            coalesce(nullif(trim(payload->>'category'), ''), 'Inbox'),
            p_actor_user_id
        ) returning * into grocery_row;
        created_record := to_jsonb(grocery_row);
        created_id := grocery_row.id;
        created_type := 'grocery';
    else
        if char_length(trim(coalesce(payload->>'text', ''))) not between 1 and 4000 then
            raise exception 'note is required' using errcode = '22023';
        end if;
    end if;

    update public.inbox_suggestions
    set suggestion_type = effective_type,
        proposed_payload = payload,
        status = 'accepted',
        reviewed_by = p_actor_user_id,
        reviewed_at = timezone('utc', now()),
        updated_at = timezone('utc', now())
    where id = suggestion_row.id
    returning * into reviewed_suggestion;

    update public.inbox_items
    set status = case when created_id is null then 'archived' else 'converted' end,
        converted_type = created_type,
        converted_id = created_id,
        resolved_at = timezone('utc', now())
    where id = capture_row.id
    returning * into reviewed_capture;

    insert into public.activity_log (household_id, actor, action, entity_type, entity_id, before_json, after_json)
    values (
        p_household_id,
        p_actor_user_id,
        'inbox.suggestion_accepted',
        'inbox_suggestion',
        suggestion_row.id,
        jsonb_build_object('status', 'pending', 'suggestion_type', suggestion_row.suggestion_type),
        jsonb_build_object('status', 'accepted', 'created_type', created_type, 'created_id', created_id)
    );

    return jsonb_build_object(
        'decision', 'accepted',
        'suggestion', to_jsonb(reviewed_suggestion),
        'item', to_jsonb(reviewed_capture),
        'created', created_record,
        'created_type', created_type
    );
end;
$$;

revoke all on function public.review_inbox_suggestion(uuid, uuid, uuid, uuid, text, text, jsonb) from public, anon;
grant execute on function public.review_inbox_suggestion(uuid, uuid, uuid, uuid, text, text, jsonb) to authenticated, service_role;

create or replace function public.archive_inbox_capture(
    p_household_id uuid,
    p_actor_user_id uuid,
    p_inbox_item_id uuid
)
returns jsonb
language plpgsql
security definer
set search_path = public, private, extensions
as $$
declare
    actor_membership public.memberships;
    capture_row public.inbox_items;
    suggestion_row public.inbox_suggestions;
    reviewed_suggestion public.inbox_suggestions;
    reviewed_capture public.inbox_items;
begin
    if (auth.uid() is null and coalesce(auth.role(), '') <> 'service_role')
       or (auth.uid() is not null and auth.uid() <> p_actor_user_id) then
        raise exception 'authenticated actor required' using errcode = '42501';
    end if;

    select * into actor_membership
    from public.memberships
    where household_id = p_household_id and user_id = p_actor_user_id
    for update;
    if not found then
        raise exception 'household membership required' using errcode = '42501';
    end if;

    select * into capture_row
    from public.inbox_items
    where id = p_inbox_item_id and household_id = p_household_id
    for update;
    if not found then
        raise exception 'inbox item not found' using errcode = 'P0002';
    end if;
    if capture_row.private and capture_row.created_by <> p_actor_user_id then
        raise exception 'private inbox item is not archivable by this member' using errcode = '42501';
    end if;
    if capture_row.status <> 'open' then
        raise exception 'inbox item has already been resolved' using errcode = '55006';
    end if;

    select * into suggestion_row
    from public.inbox_suggestions
    where inbox_item_id = capture_row.id and household_id = p_household_id
    for update;
    if found and suggestion_row.status <> 'pending' then
        raise exception 'suggestion has already been reviewed' using errcode = '55006';
    end if;

    if found then
        update public.inbox_suggestions
        set status = 'rejected', reviewed_by = p_actor_user_id, reviewed_at = timezone('utc', now()), updated_at = timezone('utc', now())
        where id = suggestion_row.id
        returning * into reviewed_suggestion;

        insert into public.activity_log (household_id, actor, action, entity_type, entity_id, before_json, after_json)
        values (
            p_household_id,
            p_actor_user_id,
            'inbox.suggestion_rejected',
            'inbox_suggestion',
            suggestion_row.id,
            jsonb_build_object('status', 'pending', 'suggestion_type', suggestion_row.suggestion_type),
            jsonb_build_object('status', 'rejected', 'reason', 'archived')
        );
    end if;

    update public.inbox_items
    set status = 'archived', resolved_at = timezone('utc', now())
    where id = capture_row.id
    returning * into reviewed_capture;

    return jsonb_build_object(
        'decision', 'rejected',
        'suggestion', case when reviewed_suggestion.id is null then null else to_jsonb(reviewed_suggestion) end,
        'item', to_jsonb(reviewed_capture),
        'created', null,
        'created_type', null
    );
end;
$$;

revoke all on function public.archive_inbox_capture(uuid, uuid, uuid) from public, anon;
grant execute on function public.archive_inbox_capture(uuid, uuid, uuid) to authenticated, service_role;
