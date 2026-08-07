create table if not exists public.notification_deliveries (
    id uuid primary key default gen_random_uuid(),
    household_id uuid not null references public.households(id) on delete cascade,
    user_id uuid not null references auth.users(id) on delete cascade,
    briefing_type text not null default 'morning' check (briefing_type in ('morning')),
    delivery_date date not null,
    idempotency_key text not null unique,
    channel text not null default 'email' check (channel in ('email', 'none')),
    recipient_email text not null check (char_length(trim(recipient_email)) between 3 and 320),
    subject text not null check (char_length(trim(subject)) between 1 and 240),
    body text not null check (char_length(trim(body)) between 1 and 10000),
    status text not null default 'queued' check (status in ('queued', 'sending', 'sent', 'failed', 'no_provider', 'cancelled')),
    attempts integer not null default 0 check (attempts >= 0 and attempts <= 10),
    provider_message_id text,
    last_error text,
    scheduled_for timestamptz not null default timezone('utc', now()),
    next_attempt_at timestamptz,
    lease_expires_at timestamptz,
    claim_token uuid,
    sent_at timestamptz,
    created_at timestamptz not null default timezone('utc', now()),
    updated_at timestamptz not null default timezone('utc', now()),
    unique (household_id, user_id, briefing_type, delivery_date)
);

create index if not exists notification_deliveries_due_idx
    on public.notification_deliveries(status, scheduled_for, next_attempt_at);

alter table public.notification_deliveries enable row level security;

drop policy if exists notification_deliveries_self_select on public.notification_deliveries;
create policy notification_deliveries_self_select on public.notification_deliveries
    for select to authenticated using (user_id = (select auth.uid()) and private.is_household_member(household_id));

drop policy if exists notification_deliveries_self_insert on public.notification_deliveries;
drop policy if exists notification_deliveries_self_update on public.notification_deliveries;

revoke insert, update, delete on public.notification_deliveries from authenticated;
revoke all on public.notification_deliveries from anon;
grant select on public.notification_deliveries to authenticated;
grant all on public.notification_deliveries to service_role;

create or replace function public.queue_notification_delivery(
    p_household_id uuid,
    p_actor_user_id uuid,
    p_delivery_date date
)
returns jsonb
language plpgsql
security definer
set search_path = public, private, extensions
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
    select * into actor_membership from public.memberships
    where household_id = p_household_id and user_id = p_actor_user_id for update;
    if not found then
        raise exception 'household membership required' using errcode = '42501';
    end if;
    select * into preference from public.notification_preferences
    where household_id = p_household_id and user_id = p_actor_user_id and briefing_type = 'morning'
    for update;
    if not found then
        insert into public.notification_preferences (household_id, user_id, briefing_type)
        values (p_household_id, p_actor_user_id, 'morning')
        on conflict (household_id, user_id, briefing_type) do nothing;
        select * into preference from public.notification_preferences
        where household_id = p_household_id and user_id = p_actor_user_id and briefing_type = 'morning'
        for update;
    end if;
    if not preference.enabled or preference.channel = 'none' then
        return jsonb_build_object('queued', false, 'delivery', null, 'reason', 'notifications disabled');
    end if;
    select * into auth_user from auth.users where id = p_actor_user_id;
    if not found or auth_user.email is null or auth_user.email_confirmed_at is null then
        raise exception 'a verified account email is required' using errcode = '22023';
    end if;
    if p_delivery_date = local_today then
        scheduled_at := timezone('utc', now());
    else
        begin
            scheduled_at := timezone('Australia/Sydney', (p_delivery_date::text || ' ' || preference.preferred_time)::timestamp);
        exception when others then
            scheduled_at := timezone('Australia/Sydney', (p_delivery_date::text || ' 07:00')::timestamp);
        end;
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
    if delivery_row.status in ('cancelled', 'failed', 'no_provider') then
        update public.notification_deliveries
        set status = 'queued', attempts = 0, next_attempt_at = null, lease_expires_at = null,
            claim_token = null, last_error = null, scheduled_for = scheduled_at, updated_at = timezone('utc', now())
        where id = delivery_row.id
        returning * into delivery_row;
    end if;
    return jsonb_build_object('queued', true, 'delivery', to_jsonb(delivery_row));
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
set search_path = public, private, extensions
as $$
declare
    actor_membership public.memberships;
    changed integer;
begin
    if (auth.uid() is null and coalesce(auth.role(), '') <> 'service_role')
       or (auth.uid() is not null and auth.uid() <> p_actor_user_id) then
        raise exception 'authenticated actor required' using errcode = '42501';
    end if;
    select * into actor_membership from public.memberships
    where household_id = p_household_id and user_id = p_actor_user_id for update;
    if not found then
        raise exception 'household membership required' using errcode = '42501';
    end if;
    update public.notification_deliveries
    set status = 'cancelled', last_error = 'notifications disabled by member', lease_expires_at = null,
        claim_token = null, updated_at = timezone('utc', now())
    where household_id = p_household_id and user_id = p_actor_user_id
      and briefing_type = p_briefing_type and status in ('queued', 'failed', 'no_provider');
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
set search_path = public, extensions
as $$
begin
    update public.notification_deliveries
    set status = 'failed', next_attempt_at = null, lease_expires_at = null, claim_token = null,
        last_error = 'delivery lease expired after retry limit', updated_at = timezone('utc', now())
    where status = 'sending' and attempts >= 10
      and coalesce(lease_expires_at, timezone('utc', now())) <= timezone('utc', now());

    return query
    with candidates as (
        select d.id
        from public.notification_deliveries d
        where (
            (d.status = 'queued' and d.attempts < 10 and d.scheduled_for <= timezone('utc', now()))
            or (d.status in ('failed', 'no_provider') and d.attempts < 10 and coalesce(d.next_attempt_at, timezone('utc', now())) <= timezone('utc', now()))
            or (d.status = 'sending' and d.attempts < 10 and coalesce(d.lease_expires_at, timezone('utc', now())) <= timezone('utc', now()))
        )
        and exists (
            select 1
            from public.notification_preferences p
            cross join lateral (
                select
                    case when p.preferred_time ~ '^([01][0-9]|2[0-3]):[0-5][0-9]$' then p.preferred_time::time else null::time end as preferred_time_value,
                    case when p.quiet_start ~ '^([01][0-9]|2[0-3]):[0-5][0-9]$' then p.quiet_start::time else null::time end as quiet_start_value,
                    case when p.quiet_end ~ '^([01][0-9]|2[0-3]):[0-5][0-9]$' then p.quiet_end::time else null::time end as quiet_end_value
            ) clock
            where p.household_id = d.household_id
              and p.user_id = d.user_id
              and p.briefing_type = d.briefing_type
              and p.enabled = true
              and p.channel = 'email'
              and clock.preferred_time_value is not null
              and clock.quiet_start_value is not null
              and clock.quiet_end_value is not null
              and (
                  d.delivery_date < timezone('Australia/Sydney', now())::date
                  or (d.delivery_date = timezone('Australia/Sydney', now())::date
                      and timezone('Australia/Sydney', now())::time >= clock.preferred_time_value)
              )
              and not (
                  (clock.quiet_start_value < clock.quiet_end_value
                   and timezone('Australia/Sydney', now())::time >= clock.quiet_start_value
                   and timezone('Australia/Sydney', now())::time < clock.quiet_end_value)
                  or (clock.quiet_start_value >= clock.quiet_end_value
                      and (timezone('Australia/Sydney', now())::time >= clock.quiet_start_value
                           or timezone('Australia/Sydney', now())::time < clock.quiet_end_value))
              )
        )
        and exists (
            select 1
            from public.memberships m
            where m.household_id = d.household_id and m.user_id = d.user_id
        )
        order by d.scheduled_for asc, d.id asc
        limit greatest(least(coalesce(p_limit, 25), 100), 1)
        for update skip locked
    )
    update public.notification_deliveries d
       set status = 'sending',
           attempts = d.attempts + 1,
           claim_token = gen_random_uuid(),
           lease_expires_at = timezone('utc', now()) + interval '15 minutes',
           updated_at = timezone('utc', now())
      from candidates
     where d.id = candidates.id
    returning d.*;
end;
$$;

revoke all on function public.claim_notification_deliveries(integer) from public;
grant execute on function public.claim_notification_deliveries(integer) to service_role;
