# Optional Future Infrastructure (PostgreSQL 16 + PostGIS 3.4 & Redis)

> **Phase 2 Status:** **Optional / Deferred.** Phase 2 runs natively on Windows with SQLite and an in-memory cache without Docker or WSL. Use this directory only when migrating to PostgreSQL 16 + PostGIS 3.4 in Phase 3+ (see `POSTGIS_MIGRATION_PLAN.md`).

## Security & Networking Rules
- All database credentials are loaded from the root `.env` file (copied from `.env.example`, never committed).
- Both PostgreSQL (`5432`) and Redis (`6379`) are bound strictly to `127.0.0.1` so they are unreachable from external networks.

## Usage (from repository root)

1. Create `.env` from `.env.example` and replace `CHANGE_ME_LOCAL_DEV_PASSWORD` with a strong local password.
2. Start the database and wait until healthy:
   ```powershell
   docker compose --env-file .env -f infra/docker-compose.yml up -d
   docker compose --env-file .env -f infra/docker-compose.yml ps
   ```
3. Verify PostGIS version:
   ```powershell
   docker compose --env-file .env -f infra/docker-compose.yml exec db psql -U $env:POSTGRES_USER -d $env:POSTGRES_DB -c "SELECT version(), PostGIS_Full_Version();"
   ```

