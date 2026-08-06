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
  "retailers": ["coles", "woolworths"],
  "items": [
    {"item_id": "<household grocery UUID>", "name": "eggs", "quantity": 1, "unit": "each"}
  ]
}
```

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
- Refreshes are rate-limited to one provider request per household per 30 seconds per warm API process.
- Successful observations are persisted through the service-role-only quote RPC and read back as household-scoped cached quotes.
- Cached live quotes remain visible for planning, but are marked stale after 48 hours and cannot drive a retailer recommendation.
- Curated catalog matching remains the fallback when the provider is absent, unavailable, malformed, rate-limited, or missing an item.
- Manual prices are never overwritten by curated or live observations.
- A live closest-pack result may be displayed as planning information but cannot become an automatic item price or equivalent comparison.
- Provider failures return a generic safe fallback status; provider response bodies, credentials, and household data are not sent to the browser.

## Deployment order

1. Apply `supabase/migrations/20260806010000_coles_woolworths_live_quotes.sql` to the hosted Supabase project. It removes obsolete ALDI quote rows, narrows the retailer check constraint, adds comparison metadata, and replaces the old quote upsert function signature.
2. Configure the approved provider URL and optional API key in the Vercel project environment for the relevant deployment.
3. Deploy the API and dashboard together.
4. Open `/groceries`, verify both retailer cards and totals, then use **Refresh Coles + Woolworths** and confirm the status changes to live for returned matches.

If the provider is not configured, the feature remains functional with curated Coles and Woolworths observations and clearly reports that it is using the curated fallback.
