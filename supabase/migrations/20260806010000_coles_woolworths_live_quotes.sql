-- Hearthstate compares only Coles and Woolworths. Existing ALDI quote rows
-- are obsolete and are removed before narrowing the retailer contract.
delete from public.grocery_price_quotes
where retailer = 'aldi';

alter table public.grocery_price_quotes
    drop constraint if exists grocery_price_quotes_retailer_check;

alter table public.grocery_price_quotes
    add constraint grocery_price_quotes_retailer_check
    check (retailer in ('coles', 'woolworths'));

alter table public.grocery_price_quotes
    add column if not exists comparison_key text,
    add column if not exists requested_size text,
    add column if not exists product_size text,
    add column if not exists size_match text not null default 'exact',
    add column if not exists size_quantity_safe boolean not null default false;

alter table public.grocery_price_quotes
    drop constraint if exists grocery_price_quotes_size_match_check;

alter table public.grocery_price_quotes
    add constraint grocery_price_quotes_size_match_check
    check (size_match in ('exact', 'closest'));

-- Replace the earlier 12-argument function with a metadata-aware contract.
-- Keeping the old signature would allow callers to bypass the comparison key.
drop function if exists public.upsert_grocery_price_quote(uuid, uuid, uuid, text, text, text, text, numeric, timestamptz, text, text, text);

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
    p_note text,
    p_comparison_key text,
    p_requested_size text,
    p_product_size text,
    p_size_match text,
    p_size_quantity_safe boolean
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
        match_basis, note, comparison_key, requested_size, product_size,
        size_match, size_quantity_safe
    ) values (
        p_household_id, p_grocery_item_id, p_retailer, p_product_key,
        p_product_title, p_product_url, p_price, p_observed_at, p_confidence,
        coalesce(p_match_basis, 'approved retailer observation'), coalesce(p_note, ''),
        p_comparison_key, p_requested_size, p_product_size,
        coalesce(p_size_match, 'exact'), coalesce(p_size_quantity_safe, false)
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
        note = excluded.note,
        comparison_key = excluded.comparison_key,
        requested_size = excluded.requested_size,
        product_size = excluded.product_size,
        size_match = excluded.size_match,
        size_quantity_safe = excluded.size_quantity_safe
    returning *;
end;
$$;

revoke all on function public.upsert_grocery_price_quote(uuid, uuid, uuid, text, text, text, text, numeric, timestamptz, text, text, text, text, text, text, text, boolean) from public, authenticated;
grant execute on function public.upsert_grocery_price_quote(uuid, uuid, uuid, text, text, text, text, numeric, timestamptz, text, text, text, text, text, text, text, boolean) to service_role;
