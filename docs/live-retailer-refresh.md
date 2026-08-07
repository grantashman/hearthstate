# Live Coles and Woolworths retailer refresh

Hearthstate's grocery comparison supports **Coles** and **Woolworths** only. The dashboard always renders a per-item price card for each store and a separate full-cart total for each store. A best-value item is shown only when both observations have the same comparison key and an exact size/variant match.

## Provider boundary

The hosted API does not scrape retailer pages directly. Live observations come from an approved provider configured with:

- `HEARTHSTATE_LIVE_RETAILER_URL` — an HTTPS provider endpoint.
- `HEARTHSTATE_LIVE_RETAILER_API_KEY` — optional bearer credential for that provider; keep it in Vercel environment secrets.

The provider receives a POST request like:

```json
{
  "version": 1,
  "search_policy": {
    "mode": "live",
    "preserve_user_query": true,
    "preserve_explicit_constraints": true,
    "prefer_retailer_own_brand_when_generic": true,
    "retailer_brands": {"coles": ["Coles"], "woolworths": ["Woolworths"]}
  },
  "retailers": ["coles", "woolworths"],
  "items": [
    {"item_id": "<household grocery UUID>", "name": "eggs", "query": "eggs", "quantity": 1, "unit": "each"}
  ]
}
```

`query` is the stored user entry, after only the API's surrounding-whitespace
trim. The provider must search that text as entered rather than replacing it
with a small alias list. It must preserve explicit size, pack, brand, dietary,
and variant constraints. For a generic query, it should rank the retailer's
own brand first (`Coles` for Coles and `Woolworths` for Woolworths), then fall
back to the best safe comparable product if no own-brand item exists.

It must return the same two retailers and zero or more safe matches:

```json
{
  "checked_at": "2026-08-06T02:30:00+00:00",
  "retailers": {
    "coles": {
      "matches": [
        {
          "item_id": "<household grocery UUID>",
          "product_key": "coles-eggs-700g",
          "comparison_key": "eggs-12-pack-700g",
          "title": "Coles Cage Free Eggs 12 Pack 700g",
          "price": 5.70,
          "url": "https://www.coles.com.au/product/…",
          "confidence": "live",
          "match_basis": "approved provider exact match",
          "size_match": "exact",
          "size_quantity_safe": true
        }
      ]
    },
    "woolworths": {"matches": []}
  }
}
```

`comparison_key` is required. It is the provider's assertion that the product family, variant, and pack size are equivalent across stores; a retailer product URL by itself is not enough. Product URLs are accepted only over HTTPS and only on the corresponding Coles or Woolworths domain.

## Safety and freshness behavior

- Live refresh is explicit: an ordinary grocery GET never calls the provider.
- Adding an item in the dashboard performs an item-scoped live search immediately after the item is persisted through `POST /api/groceries/search`; a failed or unconfigured provider falls back to curated matching without losing the item.
- The full **Refresh Coles + Woolworths** action searches the complete open list.
- Full-list refreshes are rate-limited to one provider request per household per 30 seconds per warm API process. Item searches use an item-scoped bucket so adding a second distinct item does not suppress the first search; the provider must still enforce its own account-level quota.
- Successful observations are persisted through the service-role-only quote RPC and read back as household-scoped cached quotes.
- Cached live quotes remain visible for planning, but are marked stale after 48 hours and cannot drive a retailer recommendation.
- Curated catalog matching remains the fallback when the provider is absent, unavailable, malformed, rate-limited, or missing an item.
- Manual prices are never overwritten by curated or live observations.
- A live closest-pack result may be displayed as planning information but cannot become an automatic item price or equivalent comparison.
- Provider failures return a generic safe fallback status; provider response bodies, credentials, and household data are not sent to the browser.

The repository intentionally does not scrape Coles or Woolworths pages from the
Vercel function. The configured provider is the place to implement approved
retailer search adapters (or connect a permitted retailer-search service),
including product extraction, own-brand ranking, unit/pack normalization, and
comparison-key generation. Without that provider configuration, Hearthstate
can only provide its deterministic curated fallback.

## Deployment order

1. Apply `supabase/migrations/20260806010000_coles_woolworths_live_quotes.sql` to the hosted Supabase project. It removes obsolete ALDI quote rows, narrows the retailer check constraint, adds comparison metadata, and replaces the old quote upsert function signature.
2. Configure the approved provider URL and optional API key in the Vercel project environment for the relevant deployment.
3. Deploy the API and dashboard together.
4. Open `/groceries`, verify both retailer cards and totals, then use **Refresh Coles + Woolworths** and confirm the status changes to live for returned matches.

If the provider is not configured, the feature remains functional with curated Coles and Woolworths observations and clearly reports that it is using the curated fallback.
