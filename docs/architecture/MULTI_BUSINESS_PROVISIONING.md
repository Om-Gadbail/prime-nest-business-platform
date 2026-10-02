# MULTI-BUSINESS PROVISIONING (same backend, no new codebase)

New businesses (gym, library, salon, restaurant, clinic, coaching, real estate,
local service, …) are **tenants**, not deployments.

## Provision a business (configuration, not code)

1. Create `business_id` (e.g. `salon-001`) + `business` row: name, slug, branding,
   domain, feature flags, staff roles, automation config.
2. Create staff users + `business_memberships` (role STAFF scoped to that
   `business_id` only). Owner gets a membership per business.
3. Set business-scoped integration creds (`<BUS>_WHATSAPP_*`, payment accounts —
   each client owns their own external accounts).
4. Point the business frontend's `VITE_API_BASE_URL` at the shared Worker domain
   and `VITE_BUSINESS_SLUG` at the slug. No backend deploy needed.
5. Verify tenant isolation with the security matrix (cross-business reads must fail).

## Invariants (never break)

- One backend, one Worker, one deployment engine, one auth/RBAC, one Neon project.
- Every query resolves the DB key via `db_routing.resolve_database_key` from the
  authenticated membership — request input (business_id/slug) is untrusted.
- Analytics reconcile exactly with the DB; no demo numbers in production.
- Client-owned assets rule: domains, Cloudflare, Meta, payments, email,
  analytics stay in the client's name; OSG operates only with authorization.
