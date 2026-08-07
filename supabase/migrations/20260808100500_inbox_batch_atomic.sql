create or replace function public.create_inbox_captures_batch(
    p_household_id uuid,
    p_actor_user_id uuid,
    p_captures jsonb
)
returns jsonb
language plpgsql
security definer
set search_path = public, private, extensions
as $$
declare
    capture_input jsonb;
    capture_row public.inbox_items;
    suggestion_row public.inbox_suggestions;
    results jsonb := '[]'::jsonb;
    actor_membership public.memberships;
    source_text text;
    original_text text;
    suggestion_type text;
    proposed_payload jsonb;
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
    if p_captures is null or jsonb_typeof(p_captures) <> 'array' or jsonb_array_length(p_captures) not between 1 and 8 then
        raise exception 'Inbox batch must contain between 1 and 8 items' using errcode = '22023';
    end if;

    -- Validate the complete batch before inserting any row.
    for capture_input in select value from jsonb_array_elements(p_captures)
    loop
        if jsonb_typeof(capture_input) <> 'object' then
            raise exception 'Inbox batch items must be objects' using errcode = '22023';
        end if;
        original_text := trim(coalesce(capture_input->>'original_text', ''));
        source_text := trim(coalesce(capture_input->>'source', ''));
        suggestion_type := capture_input->>'suggestion_type';
        proposed_payload := capture_input->'proposed_payload';
        if char_length(original_text) not between 1 and 4000 then
            raise exception 'original text is required' using errcode = '22023';
        end if;
        if char_length(source_text) not between 1 and 80 then
            raise exception 'source is invalid' using errcode = '22023';
        end if;
        if jsonb_typeof(capture_input->'private') <> 'boolean' then
            raise exception 'private must be a boolean' using errcode = '22023';
        end if;
        if suggestion_type is null or suggestion_type not in ('task', 'event', 'meal', 'grocery', 'note') then
            raise exception 'suggestion type is invalid' using errcode = '22023';
        end if;
        if proposed_payload is null or jsonb_typeof(proposed_payload) <> 'object' or pg_column_size(proposed_payload) > 16384 then
            raise exception 'suggestion payload is invalid' using errcode = '22023';
        end if;
    end loop;

    for capture_input in select value from jsonb_array_elements(p_captures)
    loop
        insert into public.inbox_items (household_id, original_text, source, private, created_by)
        values (
            p_household_id,
            trim(capture_input->>'original_text'),
            trim(capture_input->>'source'),
            (capture_input->>'private')::boolean,
            p_actor_user_id
        )
        returning * into capture_row;

        insert into public.inbox_suggestions (household_id, inbox_item_id, suggestion_type, proposed_payload, created_by)
        values (
            p_household_id,
            capture_row.id,
            capture_input->>'suggestion_type',
            capture_input->'proposed_payload',
            p_actor_user_id
        )
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

        insert into public.pilot_events (household_id, actor, event_name, entity_type, entity_id, metadata, dedupe_key)
        values (
            p_household_id,
            p_actor_user_id,
            'capture_created',
            'capture',
            capture_row.id,
            jsonb_build_object('private', capture_row.private)
                || case when capture_row.source in ('setup', 'dashboard', 'email', 'photon', 'notification', 'client', 'unknown')
                        then jsonb_build_object('source', capture_row.source)
                        else '{}'::jsonb end,
            'capture:' || capture_row.id::text
        )
        on conflict (household_id, event_name, dedupe_key) where dedupe_key is not null do nothing;

        results := results || jsonb_build_array(jsonb_build_object('item', to_jsonb(capture_row), 'suggestion', to_jsonb(suggestion_row)));
    end loop;
    return jsonb_build_object('captures', results);
end;
$$;

revoke all on function public.create_inbox_captures_batch(uuid, uuid, jsonb) from public, anon;
grant execute on function public.create_inbox_captures_batch(uuid, uuid, jsonb) to authenticated, service_role;
