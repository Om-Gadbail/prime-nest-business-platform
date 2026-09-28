# Local Development Ports (LOCKED)

All five frontend applications run simultaneously on separate fixed Vite
ports and talk to the ONE canonical FastAPI backend. Do not change these
ports, do not share a port between two applications.

| Application | URL | Local source |
|---|---|---|
| Prime Fitness Website | http://localhost:5173 | `C:\Users\ossag\OneDrive\Desktop\prime-fitness-website` |
| Nest Library Website | http://localhost:5174 | `C:\Users\ossag\OneDrive\Desktop\nest-library-website` |
| Prime Fitness Staff Dashboard | http://localhost:5175 | `C:\Users\ossag\OneDrive\Desktop\prime-fitness-staff-dashboard` ([repo](https://github.com/Om-Gadbail/prime-fitness-staff-dashboard)) |
| Nest Library Staff Dashboard | http://localhost:5176 | `C:\Users\ossag\OneDrive\Desktop\nest-library-staff-dashboard` ([repo](https://github.com/Om-Gadbail/nest-library-staff-dashboard)) |
| Owner Dashboard | http://localhost:5177 | `C:\Users\ossag\OneDrive\Desktop\prime-nest-owner-dashboard\apps\owner-dashboard` ([repo](https://github.com/Om-Gadbail/prime-nest-owner-dashboard)) |
| Shared FastAPI Backend | http://localhost:8000 (`/health` → 200) | `prime-nest-business-platform\backend` |

Database / cache:

| Service | Windows host | Docker internal (NEVER change) |
|---|---|---|
| PostgreSQL | `localhost:5433` | `db:5432` |
| Redis | `localhost:6380` | `redis:6379` |

Backend internal URLs stay `postgresql+psycopg://…@db:5432/…` and
`redis://redis:6379/0`. `5433`/`6380` are host-access ports ONLY — never
put them in `DATABASE_URL` / `REDIS_URL` inside Docker.

## Staff dashboards: separate repos, fixed ports

Each staff dashboard is its own GitHub repository (cloned to Desktop,
never merged into the platform repo). Both default to the canonical
backend `http://localhost:8000/api/v1` with their own business identity
(`prime-fitness-001` / `nest-library-001`). Their `VITE_ENABLE_MSW` mock
adapter MUST be `false` for real-backend local work — set in the
gitignored `.env.local` of each clone (never commit it).

```bash
# Prime Staff → :5175
cd C:\Users\ossag\OneDrive\Desktop\prime-fitness-staff-dashboard; npm run dev
# Nest Staff → :5176
cd C:\Users\ossag\OneDrive\Desktop\nest-library-staff-dashboard; npm run dev
# Owner → :5177
cd C:\Users\ossag\OneDrive\Desktop\prime-nest-owner-dashboard\apps\owner-dashboard; npm run dev
```

(`apps/staff-dashboard` inside the platform repo is the older shared
single-codebase prototype; the dedicated per-business repositories above
are the canonical runnable dashboards.)

## Owner Dashboard (:5177)

Recovered from https://github.com/Om-Gadbail/prime-nest-owner-dashboard
(runnable app at `apps/owner-dashboard`). No `apps/owner-dashboard` copy
ever existed inside the platform repo (verified: absent from disk and git
history), so nothing was overwritten or lost. It defaults to
`http://localhost:8000/api/v1` with the shared auth/refresh-token flow;
the platform owner (`owner@prime-nest-dashboard.com`) holds OWNER
memberships in both businesses, so RBAC stays server-side.

## OSG Growth AI Ops coexistence (DO NOT TOUCH)

The separate `osg-growth-ai-ops` Compose project owns host ports
`5432` (PostgreSQL) and `6379` (Redis). Never `down`, delete, rename, or
re-port its containers/volumes/networks, and never merge the two Compose
projects. Prime/Nest deliberately uses `5433`/`6380` on the host.

## Start commands

```bash
# Backend + db + redis + worker + scheduler (from repo root):
docker compose up -d --build
docker compose ps
Invoke-WebRequest http://localhost:8000/health -UseBasicParsing  # → 200

# Frontends (one terminal each):
# Prime Website:
cd C:\Users\ossag\OneDrive\Desktop\prime-fitness-website; npm run dev          # :5173
# Nest Website:
cd C:\Users\ossag\OneDrive\Desktop\nest-library-website; npm run dev           # :5174
# Prime Staff:
cd C:\Users\ossag\OneDrive\Desktop\prime-fitness-staff-dashboard; npm run dev    # :5175
# Nest Staff:
cd C:\Users\ossag\OneDrive\Desktop\nest-library-staff-dashboard; npm run dev     # :5176
# Owner:
cd C:\Users\ossag\OneDrive\Desktop\prime-nest-owner-dashboard\apps\owner-dashboard; npm run dev  # :5177
```

Frontend API base: websites use bare `http://localhost:8000` (their API
clients append `/api/v1/public/…`); the three dashboards use
`http://localhost:8000/api/v1` (their clients append `/auth/…`,
`/leads/…`, etc.). Never produce `…/api/v1/api/v1`. Business identity:
Prime site `prime`, Nest site `nest`, staff dashboards
`prime-fitness-001` / `nest-library-001` via `VITE_BUSINESS_ID`
(memberships resolve server-side).

## Warnings

- NEVER change Docker internal ports (`db:5432`, `redis:6379`).
- NEVER give two Vite applications the same port — every `server.port`
  uses `strictPort: true` so a collision fails loudly instead of
  silently hijacking another app.
- NEVER commit `.env` files, credentials, `node_modules`, `dist`, logs,
  or screenshots.
- `integrations/nest-website/` is a drop-in integration package, NOT the
  Nest frontend — do not serve it as the website.
