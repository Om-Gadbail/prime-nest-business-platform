# Frontend Environment Reference

## Backend (server-side — secrets stay here)

See root `.env.example`. Block 3/4 adds no new backend variables; the
dashboard origin must be listed in `PUBLIC_SITE_ORIGINS`:

```bash
PUBLIC_SITE_ORIGINS=http://localhost:5173,http://localhost:5174
```

Production dashboard domains replace the localhost entries (exact
origins, never `*`).

## Prime website (`prime-fitness-website/.env`)

| Variable | Example |
|---|---|
| `VITE_API_BASE_URL` | `http://localhost:8000` |
| `VITE_BUSINESS_SLUG` | `prime` |

Public, non-secret. See `docs/PRIME_INTEGRATION.md`.

## Nest website (`.env`)

| Variable | Example |
|---|---|
| `VITE_API_BASE_URL` | `http://localhost:8000` |
| `VITE_BUSINESS_SLUG` | `nest` |

Public, non-secret. See `docs/NEST_WEBSITE_INTEGRATION.md` and
`integrations/nest-website/`.

## Staff dashboard (`apps/staff-dashboard/.env`)

| Variable | Required | Example |
|---|---|---|
| `VITE_API_BASE_URL` | yes | `http://localhost:8000` |
| `VITE_BUSINESS_SLUG` | no | `prime` (login-screen branding hint) |
| `VITE_BUSINESS_NAME` | no | display-name override |

No tokens, no secrets — staff authenticate interactively (access token
in memory, refresh via HttpOnly cookie). Never commit any `.env`.
