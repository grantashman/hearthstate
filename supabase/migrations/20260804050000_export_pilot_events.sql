-- Extend the already-deployed owner export after pilot_events exists.
create or replace function public.export_household(target_household_id uuid)
returns jsonb
language plpgsql
security definer
set search_path = public, private, extensions
as $$
declare
    exported jsonb;
    owner_membership public.memberships;
begin
    select * into owner_membership
    from public.memberships
    where household_id = target_household_id
      and user_id = (select auth.uid())
      and role = 'owner'
    for update;
    if not found then
        raise exception 'owner access required' using errcode = '42501';
    end if;

    select jsonb_build_object(
        'format_version', 2,
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
        'pilot_events', coalesce((select jsonb_agg(jsonb_build_object(
            'id', p.id,
            'household_id', p.household_id,
            'actor', p.actor,
            'event_name', p.event_name,
            'entity_type', p.entity_type,
            'entity_id', p.entity_id,
            'metadata', p.metadata,
            'dedupe_key', p.dedupe_key,
            'occurred_at', p.occurred_at
        ) order by p.occurred_at) from public.pilot_events p where p.household_id = target_household_id), '[]'::jsonb),
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
        ), '[]'::jsonb)
    ) into exported;

    return exported;
end;
$$;

revoke all on function public.export_household(uuid) from public, anon, authenticated;
grant execute on function public.export_household(uuid) to authenticated;
