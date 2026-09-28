# Business Onboarding (future-client reuse)

New businesses are provisioned as **data**, never code forks.

## Provisioning path (implemented, API/CLI wiring deferred)

```python
from app.services.business_templates import provision_business

provision_business(db, slug="gurukul-gym", name="Gurukul Gym",
                   template="fitness",          # or "self_study_center"
                   timezone="Asia/Kolkata", currency="INR")
```

This creates (idempotently): the `businesses` row, settings row with
template capabilities, the template plan catalogue, and seat areas
(where the template defines them). Explicit staff edits always win
over template defaults on re-runs.

## Templates (`app/services/business_templates.py`)

| Template | `business_type` | Plans | Seat areas | Capabilities differ |
|---|---|---|---|---|
| `fitness` | `fitness` | 4 starter plans | — | `seat_management: false`, `fitness_tracking: true` |
| `self_study_center` | `library` | 20 Nest plans | ground/first floor | `seat_management: true`, `fitness_tracking: false` |

Plan pricing inside templates is **seed data** (editable post-
provision via `membership_plans.manage`); history stays safe via
membership price snapshots + plan versioning.

## Capability model (`app/services/capabilities.py`)

Resolution: explicit `business_settings.operational.capabilities` over
template defaults by `business_type`, else conservative `false`.
Valid keys are allowlisted (`KNOWN_CAPABILITIES`); unknown keys fail
loudly. Owners toggle modules via `PATCH /api/v1/business/settings`:

```json
{"operational": {"capabilities": {"seat_management": true}}}
```

## What a new client needs beyond provisioning

1. Users + role memberships (existing auth/RBAC).
2. Branding/contact/hours via settings sections (existing).
3. Catalogue review (prices in local currency).
4. Seat inventory import (if `seat_management`).
5. Staff training on the shared dashboard (no new app needed).

No new backend, no new database, no new dashboard codebase.
