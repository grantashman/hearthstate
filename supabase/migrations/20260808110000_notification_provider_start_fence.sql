alter table public.notification_deliveries
    add column if not exists provider_started_at timestamptz;

create or replace function public.guard_notification_provider_started()
returns trigger
language plpgsql
set search_path = public, pg_temp
as $$
begin
    if new.status <> 'sending' then
        new.provider_started_at := null;
    elsif old.claim_token is distinct from new.claim_token then
        new.provider_started_at := null;
    end if;
    return new;
end;
$$;

grant execute on function public.guard_notification_provider_started() to service_role;

drop trigger if exists notification_delivery_provider_started_guard on public.notification_deliveries;
create trigger notification_delivery_provider_started_guard
before update of status, claim_token, provider_started_at on public.notification_deliveries
for each row execute function public.guard_notification_provider_started();

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
    preference_found boolean;
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

    -- Serialize preference initialization for this household member without exposing
    -- whether the preference row exists before membership is checked.
    perform pg_advisory_xact_lock(hashtextextended(format('notification:%s:%s', p_household_id, p_actor_user_id), 0));
    select * into preference
    from public.notification_preferences
    where household_id = p_household_id and user_id = p_actor_user_id and briefing_type = 'morning'
    for update;
    preference_found := found;
    select * into actor_membership
    from public.memberships
    where household_id = p_household_id and user_id = p_actor_user_id
    for update;
    if not found then
        raise exception 'household membership required' using errcode = '42501';
    end if;
    if not preference_found then
        insert into public.notification_preferences (household_id, user_id, briefing_type)
        values (p_household_id, p_actor_user_id, 'morning')
        on conflict (household_id, user_id, briefing_type) do nothing;
        select * into preference
        from public.notification_preferences
        where household_id = p_household_id and user_id = p_actor_user_id and briefing_type = 'morning'
        for update;
    end if;
    if preference.enabled is distinct from true or preference.channel is distinct from 'email' then
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
    if delivery_row.status = 'cancelled' then
        update public.notification_deliveries
        set status = 'queued', attempts = 0, next_attempt_at = null, lease_expires_at = null,
            claim_token = null, provider_started_at = null, last_error = null,
            scheduled_for = scheduled_at, updated_at = timezone('utc', now())
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
    perform pg_advisory_xact_lock(hashtextextended(format('notification:%s:%s', p_household_id, p_actor_user_id), 0));
    select * into preference
    from public.notification_preferences
    where household_id = p_household_id and user_id = p_actor_user_id and briefing_type = p_briefing_type
    for update;
    select * into actor_membership
    from public.memberships
    where household_id = p_household_id and user_id = p_actor_user_id
    for update;
    if not found then
        raise exception 'household membership required' using errcode = '42501';
    end if;
    update public.notification_deliveries
    set status = 'cancelled', last_error = 'notifications disabled by member', lease_expires_at = null,
        claim_token = null, provider_started_at = null, updated_at = timezone('utc', now())
    where household_id = p_household_id and user_id = p_actor_user_id
      and briefing_type = p_briefing_type
      and (
          status in ('queued', 'failed', 'no_provider')
          or (status = 'sending' and provider_started_at is null)
      );
    get diagnostics changed = row_count;
    return changed;
end;
$$;

revoke all on function public.cancel_notification_deliveries(uuid, uuid, text) from public, anon;
grant execute on function public.cancel_notification_deliveries(uuid, uuid, text) to authenticated, service_role;

create or replace function public.begin_notification_delivery(
    p_delivery_id uuid,
    p_claim_token uuid
)
returns jsonb
language plpgsql
security definer
set search_path = public, private, extensions, pg_temp
as $$
declare
    delivery_row public.notification_deliveries;
    preference_row public.notification_preferences;
    membership_row public.memberships;
    preference_found boolean;
    membership_found boolean;
    eligible boolean := true;
    preferred_time_value time;
    quiet_start_value time;
    quiet_end_value time;
    now_utc timestamptz;
    now_local time;
    today_local date;
    changed integer;
begin
    if coalesce(auth.role(), '') <> 'service_role' then
        raise exception 'service role required' using errcode = '42501';
    end if;

    -- Read the identity needed for the lock sequence without locking delivery first.
    select * into delivery_row
    from public.notification_deliveries
    where id = p_delivery_id;
    if not found then
        return jsonb_build_object('authorized', false, 'reason', 'delivery not found');
    end if;
    perform pg_advisory_xact_lock(hashtextextended(format('notification:%s:%s', delivery_row.household_id, delivery_row.user_id), 0));

    -- Match queue, claim, cancel, and membership administration lock order.
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

    select * into delivery_row
    from public.notification_deliveries
    where id = p_delivery_id
    for update;
    if not found
       or delivery_row.status <> 'sending'
       or delivery_row.claim_token is distinct from p_claim_token
       or delivery_row.provider_started_at is not null then
        return jsonb_build_object('authorized', false, 'reason', 'claim is no longer active');
    end if;

    -- Use wall-clock time after all locks are acquired; transaction-time now() may be stale after waits.
    now_utc := clock_timestamp();
    now_local := (now_utc at time zone 'Australia/Sydney')::time;
    today_local := (now_utc at time zone 'Australia/Sydney')::date;

    if delivery_row.attempts >= 10
       or delivery_row.lease_expires_at is null
       or delivery_row.lease_expires_at <= now_utc
       or not preference_found
       or not membership_found
       or preference_row.enabled is distinct from true
       or preference_row.channel is distinct from 'email'
       or delivery_row.channel is distinct from 'email' then
        eligible := false;
    end if;

    if eligible then
        if preference_row.preferred_time is null
           or preference_row.preferred_time !~ '^([01][0-9]|2[0-3]):[0-5][0-9]$' then
            eligible := false;
        else
            preferred_time_value := preference_row.preferred_time::time;
        end if;
    end if;

    if eligible then
        if preference_row.quiet_start is null
           or preference_row.quiet_start !~ '^([01][0-9]|2[0-3]):[0-5][0-9]$'
           or preference_row.quiet_end is null
           or preference_row.quiet_end !~ '^([01][0-9]|2[0-3]):[0-5][0-9]$' then
            eligible := false;
        else
            quiet_start_value := preference_row.quiet_start::time;
            quiet_end_value := preference_row.quiet_end::time;
        end if;
    end if;

    if eligible and (
        delivery_row.delivery_date > today_local
        or (delivery_row.delivery_date = today_local and now_local < preferred_time_value)
    ) then
        eligible := false;
    end if;

    if eligible and (
        (quiet_start_value < quiet_end_value and now_local >= quiet_start_value and now_local < quiet_end_value)
        or (quiet_start_value >= quiet_end_value and (now_local >= quiet_start_value or now_local < quiet_end_value))
    ) then
        eligible := false;
    end if;

    if not eligible then
        update public.notification_deliveries
        set status = 'cancelled', lease_expires_at = null, claim_token = null,
            provider_started_at = null, last_error = 'notification consent or schedule no longer permits delivery',
            updated_at = now_utc
        where id = p_delivery_id and status = 'sending'
          and claim_token = p_claim_token and provider_started_at is null;
        return jsonb_build_object('authorized', false, 'reason', 'notification is no longer eligible');
    end if;

    update public.notification_deliveries
    set provider_started_at = now_utc, updated_at = now_utc
    where id = p_delivery_id and status = 'sending'
      and claim_token = p_claim_token and provider_started_at is null;
    get diagnostics changed = row_count;
    return jsonb_build_object('authorized', changed = 1, 'provider_started_at', now_utc);
end;
$$;

revoke all on function public.begin_notification_delivery(uuid, uuid) from public, anon, authenticated;
grant execute on function public.begin_notification_delivery(uuid, uuid) to service_role;
