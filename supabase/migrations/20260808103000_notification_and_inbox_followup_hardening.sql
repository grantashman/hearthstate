-- Follow-up hardening for already-applied Release 2 migrations.
-- Keep these replacements in a new migration: Supabase does not re-run edited
-- migration files whose versions are already recorded as applied.

create or replace function public.queue_notification_delivery(
    p_household_id uuid,
    p_actor_user_id uuid,
    p_delivery_date date
)
returns jsonb
language plpgsql
security definer
set search_path = public, private, extensions, pg_temp
as $$
declare
    actor_membership public.memberships;
    preference public.notification_preferences;
    auth_user auth.users;
    delivery_row public.notification_deliveries;
    scheduled_at timestamptz;
    local_today date := timezone('Australia/Sydney', now())::date;
    delivery_key text;
begin
    if (auth.uid() is null and coalesce(auth.role(), '') <> 'service_role')
       or (auth.uid() is not null and auth.uid() <> p_actor_user_id) then
        raise exception 'authenticated actor required' using errcode = '42501';
    end if;
    if p_delivery_date is null or p_delivery_date < local_today or p_delivery_date > local_today + 7 then
        raise exception 'delivery date is outside the allowed window' using errcode = '22023';
    end if;
    select * into preference from public.notification_preferences
    where household_id = p_household_id and user_id = p_actor_user_id and briefing_type = 'morning'
    for update;
    if not found then
        select * into actor_membership from public.memberships
        where household_id = p_household_id and user_id = p_actor_user_id for update;
        if not found then
            raise exception 'household membership required' using errcode = '42501';
        end if;
        insert into public.notification_preferences (household_id, user_id, briefing_type)
        values (p_household_id, p_actor_user_id, 'morning')
        on conflict (household_id, user_id, briefing_type) do nothing;
        select * into preference from public.notification_preferences
        where household_id = p_household_id and user_id = p_actor_user_id and briefing_type = 'morning'
        for update;
    else
        select * into actor_membership from public.memberships
        where household_id = p_household_id and user_id = p_actor_user_id for update;
        if not found then
            raise exception 'household membership required' using errcode = '42501';
        end if;
    end if;
    if not preference.enabled or preference.channel = 'none' then
        return jsonb_build_object('queued', false, 'delivery', null, 'reason', 'notifications disabled');
    end if;
    if preference.preferred_time is null
       or preference.preferred_time !~ '^([01][0-9]|2[0-3]):[0-5][0-9]$'
       or preference.quiet_start is null
       or preference.quiet_start !~ '^([01][0-9]|2[0-3]):[0-5][0-9]$'
       or preference.quiet_end is null
       or preference.quiet_end !~ '^([01][0-9]|2[0-3]):[0-5][0-9]$' then
        return jsonb_build_object('queued', false, 'delivery', null, 'reason', 'notification preferences invalid');
    end if;
    select * into auth_user from auth.users where id = p_actor_user_id;
    if not found or auth_user.email is null or auth_user.email_confirmed_at is null then
        raise exception 'a verified account email is required' using errcode = '22023';
    end if;
    if p_delivery_date = local_today then
        scheduled_at := timezone('utc', now());
    else
        scheduled_at := timezone('Australia/Sydney', (p_delivery_date::text || ' ' || preference.preferred_time)::timestamp);
    end if;
    delivery_key := format('morning:%s:%s:%s', p_household_id, p_actor_user_id, p_delivery_date);
    insert into public.notification_deliveries (
        household_id, user_id, briefing_type, delivery_date, idempotency_key,
        channel, recipient_email, subject, body, status, scheduled_for
    ) values (
        p_household_id, p_actor_user_id, 'morning', p_delivery_date, delivery_key,
        'email', lower(trim(auth_user.email)), 'Your Hearthstate morning briefing',
        'Your Hearthstate morning briefing is ready. Open your Hearthstate dashboard: https://hearthstate.vercel.app/',
        'queued', scheduled_at
    ) on conflict (idempotency_key) do nothing;
    select * into delivery_row from public.notification_deliveries d where d.idempotency_key = delivery_key for update;
    -- A manual queue or cron preparation is idempotent. It may re-enable an
    -- explicitly cancelled row, but never resets retry state on failed rows.
    if delivery_row.status = 'cancelled' then
        update public.notification_deliveries
        set status = 'queued', attempts = 0, next_attempt_at = null, lease_expires_at = null,
            claim_token = null, last_error = null, scheduled_for = scheduled_at, updated_at = timezone('utc', now())
        where id = delivery_row.id
        returning * into delivery_row;
    end if;
    return jsonb_build_object('queued', delivery_row.status = 'queued', 'delivery', to_jsonb(delivery_row));
end;
$$;

revoke all on function public.queue_notification_delivery(uuid, uuid, date) from public, anon;
grant execute on function public.queue_notification_delivery(uuid, uuid, date) to authenticated, service_role;

create or replace function public.cancel_notification_deliveries(
    p_household_id uuid,
    p_actor_user_id uuid,
    p_briefing_type text default 'morning'
)
returns integer
language plpgsql
security definer
set search_path = public, private, extensions, pg_temp
as $$
declare
    actor_membership public.memberships;
    preference public.notification_preferences;
    changed integer;
begin
    if (auth.uid() is null and coalesce(auth.role(), '') <> 'service_role')
       or (auth.uid() is not null and auth.uid() <> p_actor_user_id) then
        raise exception 'authenticated actor required' using errcode = '42501';
    end if;
    select * into preference from public.notification_preferences
    where household_id = p_household_id and user_id = p_actor_user_id and briefing_type = p_briefing_type
    for update;
    select * into actor_membership from public.memberships
    where household_id = p_household_id and user_id = p_actor_user_id for update;
    if not found then
        raise exception 'household membership required' using errcode = '42501';
    end if;
    update public.notification_deliveries
    set status = 'cancelled', last_error = 'notifications disabled by member', lease_expires_at = null,
        claim_token = null, updated_at = timezone('utc', now())
    where household_id = p_household_id and user_id = p_actor_user_id
      and briefing_type = p_briefing_type and status in ('queued', 'failed', 'no_provider', 'sending');
    get diagnostics changed = row_count;
    return changed;
end;
$$;

revoke all on function public.cancel_notification_deliveries(uuid, uuid, text) from public, anon;
grant execute on function public.cancel_notification_deliveries(uuid, uuid, text) to authenticated, service_role;

create or replace function public.claim_notification_deliveries(p_limit integer default 25)
returns setof public.notification_deliveries
language plpgsql
security definer
set search_path = public, extensions, pg_temp
as $$
declare
    candidate_id uuid;
    delivery_row public.notification_deliveries;
    preference_row public.notification_preferences;
    membership_row public.memberships;
    preference_found boolean;
    membership_found boolean;
    preferred_time_value time;
    quiet_start_value time;
    quiet_end_value time;
    now_local time := timezone('Australia/Sydney', now())::time;
    today_local date := timezone('Australia/Sydney', now())::date;
    claim_limit integer := greatest(least(coalesce(p_limit, 25), 100), 1);
    claimed_count integer := 0;
begin
    -- Recover terminal leases with the same preference -> membership -> delivery
    -- lock order used by queue and cancellation. Do not return these rows.
    for candidate_id in
        select d.id
        from public.notification_deliveries d
        where d.status = 'sending'
          and d.attempts >= 10
          and coalesce(d.lease_expires_at, timezone('utc', now())) <= timezone('utc', now())
        order by d.household_id asc, d.user_id asc, d.id asc
        limit claim_limit * 4
    loop
        select * into delivery_row from public.notification_deliveries where id = candidate_id;
        if not found then
            continue;
        end if;
        select * into preference_row
        from public.notification_preferences
        where household_id = delivery_row.household_id
          and user_id = delivery_row.user_id
          and briefing_type = delivery_row.briefing_type
        for update;
        preference_found := found;
        select * into membership_row
        from public.memberships
        where household_id = delivery_row.household_id and user_id = delivery_row.user_id
        for update;
        membership_found := found;
        update public.notification_deliveries
        set status = 'failed', next_attempt_at = null, lease_expires_at = null, claim_token = null,
            last_error = 'delivery lease expired after retry limit', updated_at = timezone('utc', now())
        where id = candidate_id and status = 'sending' and attempts >= 10
          and coalesce(lease_expires_at, timezone('utc', now())) <= timezone('utc', now());
    end loop;

    for candidate_id in
        select d.id
        from public.notification_deliveries d
        where d.channel = 'email'
          and (
            (d.status = 'queued' and d.attempts < 10 and d.scheduled_for <= timezone('utc', now()))
            or (d.status in ('failed', 'no_provider') and d.attempts < 10 and coalesce(d.next_attempt_at, timezone('utc', now())) <= timezone('utc', now()))
            or (d.status = 'sending' and d.attempts < 10 and coalesce(d.lease_expires_at, timezone('utc', now())) <= timezone('utc', now()))
          )
          and exists (
            select 1
            from public.notification_preferences p
            join public.memberships m
              on m.household_id = d.household_id and m.user_id = d.user_id
            where p.household_id = d.household_id
              and p.user_id = d.user_id
              and p.briefing_type = d.briefing_type
              and p.enabled = true
              and p.channel = 'email'
              and p.preferred_time ~ '^([01][0-9]|2[0-3]):[0-5][0-9]$'
              and p.quiet_start ~ '^([01][0-9]|2[0-3]):[0-5][0-9]$'
              and p.quiet_end ~ '^([01][0-9]|2[0-3]):[0-5][0-9]$'
              and (
                  d.delivery_date < timezone('Australia/Sydney', now())::date
                  or (d.delivery_date = timezone('Australia/Sydney', now())::date
                      and timezone('Australia/Sydney', now())::time >=
                          case when p.preferred_time ~ '^([01][0-9]|2[0-3]):[0-5][0-9]$' then p.preferred_time::time end)
              )
              and not (
                  (case when p.quiet_start ~ '^([01][0-9]|2[0-3]):[0-5][0-9]$' then p.quiet_start::time end
                   < case when p.quiet_end ~ '^([01][0-9]|2[0-3]):[0-5][0-9]$' then p.quiet_end::time end
                   and timezone('Australia/Sydney', now())::time >= case when p.quiet_start ~ '^([01][0-9]|2[0-3]):[0-5][0-9]$' then p.quiet_start::time end
                   and timezone('Australia/Sydney', now())::time < case when p.quiet_end ~ '^([01][0-9]|2[0-3]):[0-5][0-9]$' then p.quiet_end::time end)
                  or (case when p.quiet_start ~ '^([01][0-9]|2[0-3]):[0-5][0-9]$' then p.quiet_start::time end
                      >= case when p.quiet_end ~ '^([01][0-9]|2[0-3]):[0-5][0-9]$' then p.quiet_end::time end
                      and (timezone('Australia/Sydney', now())::time >= case when p.quiet_start ~ '^([01][0-9]|2[0-3]):[0-5][0-9]$' then p.quiet_start::time end
                           or timezone('Australia/Sydney', now())::time < case when p.quiet_end ~ '^([01][0-9]|2[0-3]):[0-5][0-9]$' then p.quiet_end::time end))
              )
          )
        order by d.household_id asc, d.user_id asc, d.id asc
        limit claim_limit * 4
    loop
        -- Explicit individual locks make acquisition order deterministic.
        select * into delivery_row from public.notification_deliveries
        where id = candidate_id;
        if not found then
            continue;
        end if;
        select * into preference_row
        from public.notification_preferences
        where household_id = delivery_row.household_id
          and user_id = delivery_row.user_id
          and briefing_type = delivery_row.briefing_type
        for update;
        preference_found := found;
        select * into membership_row
        from public.memberships
        where household_id = delivery_row.household_id and user_id = delivery_row.user_id
        for update;
        membership_found := found;
        if not preference_found or not membership_found
           or not preference_row.enabled or preference_row.channel <> 'email'
           or preference_row.preferred_time is null
           or preference_row.preferred_time !~ '^([01][0-9]|2[0-3]):[0-5][0-9]$'
           or preference_row.quiet_start is null
           or preference_row.quiet_start !~ '^([01][0-9]|2[0-3]):[0-5][0-9]$'
           or preference_row.quiet_end is null
           or preference_row.quiet_end !~ '^([01][0-9]|2[0-3]):[0-5][0-9]$' then
            continue;
        end if;
        preferred_time_value := preference_row.preferred_time::time;
        quiet_start_value := preference_row.quiet_start::time;
        quiet_end_value := preference_row.quiet_end::time;
        if not (
            delivery_row.delivery_date < today_local
            or (delivery_row.delivery_date = today_local and now_local >= preferred_time_value)
        ) then
            continue;
        end if;
        if (
            (quiet_start_value < quiet_end_value and now_local >= quiet_start_value and now_local < quiet_end_value)
            or (quiet_start_value >= quiet_end_value and (now_local >= quiet_start_value or now_local < quiet_end_value))
        ) then
            continue;
        end if;
        select * into delivery_row
        from public.notification_deliveries d
        where d.id = candidate_id
          and d.channel = 'email'
          and (
            (d.status = 'queued' and d.attempts < 10 and d.scheduled_for <= timezone('utc', now()))
            or (d.status in ('failed', 'no_provider') and d.attempts < 10 and coalesce(d.next_attempt_at, timezone('utc', now())) <= timezone('utc', now()))
            or (d.status = 'sending' and d.attempts < 10 and coalesce(d.lease_expires_at, timezone('utc', now())) <= timezone('utc', now()))
          )
        for update skip locked;
        if not found then
            continue;
        end if;
        update public.notification_deliveries
        set status = 'sending', attempts = delivery_row.attempts + 1,
            claim_token = gen_random_uuid(), lease_expires_at = timezone('utc', now()) + interval '15 minutes',
            updated_at = timezone('utc', now())
        where id = delivery_row.id
        returning * into delivery_row;
        return next delivery_row;
        claimed_count := claimed_count + 1;
        exit when claimed_count >= claim_limit;
    end loop;
end;
$$;

revoke all on function public.claim_notification_deliveries(integer) from public;
grant execute on function public.claim_notification_deliveries(integer) to service_role;

create or replace function public.create_inbox_captures_batch(
    p_household_id uuid,
    p_actor_user_id uuid,
    p_captures jsonb
)
returns jsonb
language plpgsql
security definer
set search_path = public, private, extensions, pg_temp
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
    if p_captures is null or jsonb_typeof(p_captures) <> 'array' then
        raise exception 'Inbox batch must contain between 1 and 8 items' using errcode = '22023';
    end if;
    if jsonb_array_length(p_captures) not between 1 and 8 then
        raise exception 'Inbox batch must contain between 1 and 8 items' using errcode = '22023';
    end if;

    -- Validate the complete batch before inserting any row.
    for capture_input in select value from jsonb_array_elements(p_captures)
    loop
        if jsonb_typeof(capture_input) <> 'object' then
            raise exception 'Inbox batch items must be objects' using errcode = '22023';
        end if;
        if jsonb_typeof(capture_input->'original_text') is distinct from 'string'
           or jsonb_typeof(capture_input->'source') is distinct from 'string'
           or jsonb_typeof(capture_input->'private') is distinct from 'boolean' then
            raise exception 'Inbox batch field types are invalid' using errcode = '22023';
        end if;
        original_text := trim(capture_input->>'original_text');
        source_text := trim(capture_input->>'source');
        suggestion_type := capture_input->>'suggestion_type';
        proposed_payload := capture_input->'proposed_payload';
        if char_length(original_text) not between 1 and 4000 then
            raise exception 'original text is required' using errcode = '22023';
        end if;
        if char_length(source_text) not between 1 and 80 then
            raise exception 'source is invalid' using errcode = '22023';
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
