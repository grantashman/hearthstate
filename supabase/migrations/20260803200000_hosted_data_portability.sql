-- Owner-authorized data portability for the hosted household boundary.
-- Export is complete for household-owned records but deliberately omits
-- invitation bearer hashes and channel integration token hashes.
create or replace function public.export_household(target_household_id uuid)
returns jsonb
language plpgsql
security definer
set search_path = public, private, extensions
as $$
declare
    exported jsonb;
begin
    if not exists (
        select 1 from public.memberships
        where household_id = target_household_id
          and user_id = (select auth.uid())
          and role = 'owner'
    ) then
        raise exception 'owner access required' using errcode = '42501';
    end if;

    select jsonb_build_object(
        'format_version', 1,
        'exported_at', timezone('utc', now()),
        'household', (select to_jsonb(h) from public.households h where h.id = target_household_id),
        'memberships', coalesce((select jsonb_agg(to_jsonb(m) order by m.created_at) from public.memberships m where m.household_id = target_household_id), '[]'::jsonb),
        'profiles', coalesce((select jsonb_agg(to_jsonb(p) order by p.created_at) from public.profiles p where p.user_id in (select m.user_id from public.memberships m where m.household_id = target_household_id)), '[]'::jsonb),
        'inbox_items', coalesce((select jsonb_agg(to_jsonb(i) order by i.created_at) from public.inbox_items i where i.household_id = target_household_id), '[]'::jsonb),
        'tasks', coalesce((select jsonb_agg(to_jsonb(t) order by t.created_at) from public.tasks t where t.household_id = target_household_id), '[]'::jsonb),
        'events', coalesce((select jsonb_agg(to_jsonb(e) order by e.created_at) from public.events e where e.household_id = target_household_id), '[]'::jsonb),
        'meals', coalesce((select jsonb_agg(to_jsonb(m) order by m.created_at) from public.meals m where m.household_id = target_household_id), '[]'::jsonb),
        'grocery_items', coalesce((select jsonb_agg(to_jsonb(g) order by g.created_at) from public.grocery_items g where g.household_id = target_household_id), '[]'::jsonb),
        'activity_log', coalesce((select jsonb_agg(to_jsonb(a) order by a.created_at) from public.activity_log a where a.household_id = target_household_id), '[]'::jsonb),
        'planner_settings', coalesce((select jsonb_agg(to_jsonb(s)) from public.planner_settings s where s.household_id = target_household_id), '[]'::jsonb),
        'recipes', coalesce((select jsonb_agg(to_jsonb(r) order by r.created_at) from public.recipes r where r.household_id = target_household_id), '[]'::jsonb),
        'saved_recipes', coalesce((
            select jsonb_agg(to_jsonb(sr) order by sr.saved_at)
            from public.saved_recipes sr
            join public.recipes r on r.id = sr.recipe_id
            where r.household_id = target_household_id
        ), '[]'::jsonb),
        'notification_preferences', coalesce((select jsonb_agg(to_jsonb(n) order by n.updated_at) from public.notification_preferences n where n.household_id = target_household_id), '[]'::jsonb),
        'chore_templates', coalesce((select jsonb_agg(to_jsonb(c) order by c.created_at) from public.chore_templates c where c.household_id = target_household_id), '[]'::jsonb),
        'invitations', coalesce((
            select jsonb_agg(jsonb_build_object(
                'id', i.id,
                'household_id', i.household_id,
                'email', i.email,
                'role', i.role,
                'invited_by', i.invited_by,
                'expires_at', i.expires_at,
                'accepted_at', i.accepted_at,
                'accepted_user_id', i.accepted_user_id,
                'revoked_at', i.revoked_at,
                'created_at', i.created_at
            ) order by i.created_at)
            from public.invitations i
            where i.household_id = target_household_id
        ), '[]'::jsonb),
        'channel_identities', coalesce((
            select jsonb_agg(jsonb_build_object(
                'integration_id', ci.integration_id,
                'external_user_id', ci.external_user_id,
                'user_id', ci.user_id,
                'household_id', ci.household_id,
                'created_at', ci.created_at
            ) order by ci.created_at)
            from public.channel_identities ci
            where ci.household_id = target_household_id
        ), '[]'::jsonb),
        'channel_integrations', coalesce((
            select jsonb_agg(jsonb_build_object(
                'id', integration.id,
                'channel', integration.channel,
                'name', integration.name,
                'allowed_email', integration.allowed_email,
                'enabled', integration.enabled,
                'created_at', integration.created_at
            ) order by integration.created_at)
            from public.channel_integrations integration
            where integration.id in (
                select ci.integration_id from public.channel_identities ci where ci.household_id = target_household_id
            )
        ), '[]'::jsonb)
    ) into exported;

    return exported;
end;
$$;

revoke all on function public.export_household(uuid) from public, anon, authenticated;
grant execute on function public.export_household(uuid) to authenticated;

create or replace function public.delete_household(target_household_id uuid, confirmation_name text)
returns boolean
language plpgsql
security definer
set search_path = public, private, extensions
as $$
declare
    current_name text;
begin
    select h.name into current_name
    from public.households h
    join public.memberships m on m.household_id = h.id
    where h.id = target_household_id
      and m.user_id = (select auth.uid())
      and m.role = 'owner'
    for update;

    if not found then
        raise exception 'owner access required' using errcode = '42501';
    end if;
    if trim(coalesce(confirmation_name, '')) <> current_name then
        raise exception 'household confirmation does not match' using errcode = '22023';
    end if;

    delete from public.households where id = target_household_id;
    if not found then
        raise exception 'household not found' using errcode = '22023';
    end if;
    return true;
end;
$$;

revoke all on function public.delete_household(uuid, text) from public, anon, authenticated;
grant execute on function public.delete_household(uuid, text) to authenticated;
