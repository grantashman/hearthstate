-- Keep protected grocery mutations behind server-controlled, membership-checked
-- RPCs. The API passes the actor ID obtained from the authenticated session;
-- each function locks that membership row before changing household data. A
-- concurrent membership revocation therefore cannot pass a stale preflight
-- check and then mutate through the service role.
revoke insert, update on public.grocery_items from authenticated;
grant insert (household_id, name, quantity, unit, category, status, created_by)
    on public.grocery_items to authenticated;
grant update (name, quantity, unit, category, status)
    on public.grocery_items to authenticated;
grant select, delete on public.grocery_items to authenticated;
grant select, insert, update, delete on public.grocery_items to service_role;

revoke insert, update, delete on public.grocery_price_quotes from authenticated;
grant select on public.grocery_price_quotes to authenticated;
grant select, insert, update, delete on public.grocery_price_quotes to service_role;

create or replace function public.set_grocery_manual_price(
    p_actor_user_id uuid,
    p_household_id uuid,
    p_item_id uuid,
    p_price numeric,
    p_checked_at timestamptz default null
)
returns setof public.grocery_items
language plpgsql
security definer
set search_path = public
as $$
begin
    if p_actor_user_id is null then
        raise exception 'actor is required' using errcode = '42501';
    end if;
    perform 1
    from public.memberships
    where household_id = p_household_id
      and user_id = p_actor_user_id
    for update;
    if not found then
        raise exception 'household membership required' using errcode = '42501';
    end if;
    if p_price is null or p_price < 0 or p_price > 99999999.99 then
        raise exception 'price must be a non-negative numeric(10,2) value' using errcode = '22023';
    end if;

    return query
    update public.grocery_items
    set price = p_price,
        price_source = 'Manual entry',
        price_url = null,
        price_checked_at = coalesce(p_checked_at, timezone('utc', now())),
        price_confidence = 'manual',
        price_note = 'Entered by household'
    where id = p_item_id
      and household_id = p_household_id
    returning *;
end;
$$;

create or replace function public.apply_grocery_automatic_price(
    p_actor_user_id uuid,
    p_household_id uuid,
    p_item_id uuid,
    p_expected_name text,
    p_expected_quantity numeric,
    p_expected_unit text,
    p_expected_category text,
    p_expected_price_confidence text,
    p_expected_price_source text,
    p_price numeric,
    p_price_source text,
    p_price_url text,
    p_price_confidence text,
    p_price_checked_at timestamptz,
    p_price_note text
)
returns setof public.grocery_items
language plpgsql
security definer
set search_path = public
as $$
begin
    if p_actor_user_id is null then
        raise exception 'actor is required' using errcode = '42501';
    end if;
    perform 1
    from public.memberships
    where household_id = p_household_id
      and user_id = p_actor_user_id
    for update;
    if not found then
        raise exception 'household membership required' using errcode = '42501';
    end if;
    if p_price is null or p_price < 0 or p_price > 99999999.99 then
        raise exception 'price must be a non-negative numeric(10,2) value' using errcode = '22023';
    end if;

    return query
    update public.grocery_items
    set price = p_price,
        price_source = p_price_source,
        price_url = p_price_url,
        price_checked_at = p_price_checked_at,
        price_confidence = p_price_confidence,
        price_note = p_price_note
    where id = p_item_id
      and household_id = p_household_id
      and name is not distinct from p_expected_name
      and quantity is not distinct from p_expected_quantity
      and unit is not distinct from p_expected_unit
      and category is not distinct from p_expected_category
      and price_confidence is not distinct from p_expected_price_confidence
      and price_source is not distinct from p_expected_price_source
      and lower(trim(coalesce(price_confidence, ''))) <> 'manual'
      and lower(trim(coalesce(price_source, ''))) not like 'manual%'
    returning *;
end;
$$;

create or replace function public.upsert_grocery_price_quote(
    p_actor_user_id uuid,
    p_household_id uuid,
    p_grocery_item_id uuid,
    p_retailer text,
    p_product_key text,
    p_product_title text,
    p_product_url text,
    p_price numeric,
    p_observed_at timestamptz,
    p_confidence text,
    p_match_basis text,
    p_note text
)
returns setof public.grocery_price_quotes
language plpgsql
security definer
set search_path = public
as $$
begin
    if p_actor_user_id is null then
        raise exception 'actor is required' using errcode = '42501';
    end if;
    perform 1
    from public.memberships
    where household_id = p_household_id
      and user_id = p_actor_user_id
    for update;
    if not found then
        raise exception 'household membership required' using errcode = '42501';
    end if;
    perform 1
    from public.grocery_items
    where id = p_grocery_item_id
      and household_id = p_household_id
    for key share;
    if not found then
        raise exception 'grocery item is outside the household' using errcode = '42501';
    end if;

    return query
    insert into public.grocery_price_quotes (
        household_id, grocery_item_id, retailer, product_key,
        product_title, product_url, price, observed_at, confidence,
        match_basis, note
    ) values (
        p_household_id, p_grocery_item_id, p_retailer, p_product_key,
        p_product_title, p_product_url, p_price, p_observed_at, p_confidence,
        coalesce(p_match_basis, 'normalized alias'), coalesce(p_note, '')
    )
    on conflict (grocery_item_id, retailer) do update
    set household_id = excluded.household_id,
        product_key = excluded.product_key,
        product_title = excluded.product_title,
        product_url = excluded.product_url,
        price = excluded.price,
        observed_at = excluded.observed_at,
        confidence = excluded.confidence,
        match_basis = excluded.match_basis,
        note = excluded.note
    returning *;
end;
$$;

create or replace function public.delete_grocery_price_quote(
    p_actor_user_id uuid,
    p_household_id uuid,
    p_grocery_item_id uuid,
    p_retailer text
)
returns setof public.grocery_price_quotes
language plpgsql
security definer
set search_path = public
as $$
begin
    if p_actor_user_id is null then
        raise exception 'actor is required' using errcode = '42501';
    end if;
    perform 1
    from public.memberships
    where household_id = p_household_id
      and user_id = p_actor_user_id
    for update;
    if not found then
        raise exception 'household membership required' using errcode = '42501';
    end if;
    perform 1
    from public.grocery_items
    where id = p_grocery_item_id
      and household_id = p_household_id
    for key share;
    if not found then
        raise exception 'grocery item is outside the household' using errcode = '42501';
    end if;

    return query
    delete from public.grocery_price_quotes
    where household_id = p_household_id
      and grocery_item_id = p_grocery_item_id
      and retailer = p_retailer
    returning *;
end;
$$;

revoke all on function public.set_grocery_manual_price(uuid, uuid, uuid, numeric, timestamptz) from public, authenticated;
revoke all on function public.apply_grocery_automatic_price(uuid, uuid, uuid, text, numeric, text, text, text, text, numeric, text, text, text, timestamptz, text) from public, authenticated;
revoke all on function public.upsert_grocery_price_quote(uuid, uuid, uuid, text, text, text, text, numeric, timestamptz, text, text, text) from public, authenticated;
revoke all on function public.delete_grocery_price_quote(uuid, uuid, uuid, text) from public, authenticated;
grant execute on function public.set_grocery_manual_price(uuid, uuid, uuid, numeric, timestamptz) to service_role;
grant execute on function public.apply_grocery_automatic_price(uuid, uuid, uuid, text, numeric, text, text, text, text, numeric, text, text, text, timestamptz, text) to service_role;
grant execute on function public.upsert_grocery_price_quote(uuid, uuid, uuid, text, text, text, text, numeric, timestamptz, text, text, text) to service_role;
grant execute on function public.delete_grocery_price_quote(uuid, uuid, uuid, text) to service_role;
