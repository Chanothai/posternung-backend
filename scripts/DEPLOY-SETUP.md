# Deploy posternung to the server — Milestone 1 (app running + validated)

Goal of M1: get the app image running on the hardened server and prove it works
via `localhost` **on the server**. External HTTPS (reverse proxy) and CI/CD
auto-deploy are Milestones 2 & 3 (later).

> Target env for this guide: **sit** (lowest risk). To use `uat`/`production`
> instead, swap `sit` → the env name everywhere (override file, `.env.<env>`,
> container names follow automatically).

---

## Prerequisites

**A GHCR image must exist for the code you want to run.** The `build` job only
runs on push to **master**, and master is currently at commit #6 (before F2). So
to deploy the current F2 code:

1. Open a PR `develop → master` and merge it (this is your release decision).
2. That push to master triggers `build` → pushes `ghcr.io/chanothai/posternung-backend:<sha>`.
3. Note that `<sha>` — it's your `IMAGE_TAG`.

(If you just want to test the mechanics with whatever image already exists, use
any available tag — but F2 endpoints won't be there unless the image is post-F2.)

---

## Step 1 — Install Docker on the server
Copy and run the setup script (as root):
```bash
scp 03-server-docker-setup.sh deploy@<server-ip>:/tmp/
ssh deploy@<server-ip>
sudo bash /tmp/03-server-docker-setup.sh
```
Then **log out and back in** so the `docker` group takes effect, and confirm:
```bash
docker run --rm hello-world      # must work WITHOUT sudo
docker compose version
```

## Step 2 — Get the compose files onto the server
The server needs `docker-compose.yml` + `docker-compose.sit.yml` (not the source —
we pull a prebuilt image). Easiest, since the repo is public:
```bash
cd /opt/posternung
git clone https://github.com/Chanothai/posternung-backend.git .
# or scp just the two compose files if you prefer not to clone
```

## Step 3 — GHCR image access
The image is in GitHub Container Registry. Two options:

- **Recommended (simplest): make the package public.**
  GitHub → your profile/org → Packages → `posternung-backend` → Package settings
  → Change visibility → Public. Then no login is needed to pull.
- **Keep it private:** create a PAT (classic) with scope `read:packages`, then on
  the server:
  ```bash
  echo "<YOUR_PAT>" | docker login ghcr.io -u Chanothai --password-stdin
  ```

## Step 4 — Create `.env.sit` (you fill the real secrets)
In `/opt/posternung`, create `.env.sit`. Use the template below. **Do not commit
it** (`.env.*` is gitignored). Fill every `CHANGE_ME`:

```dotenv
# ---- PostgreSQL (the db container) ----
POSTGRES_USER=poster_app
POSTGRES_PASSWORD=CHANGE_ME_strong_db_password
POSTGRES_DB=poster_db
POSTGRES_PORT=5432

# ---- DB connection for the app ----
# host MUST be "db" (compose service name), NOT localhost — app talks to the db
# container over the compose network. user/pw/db must match the block above.
DATABASE_URL=postgresql+asyncpg://poster_app:CHANGE_ME_strong_db_password@db:5432/poster_db

# ---- JWT / Auth ----
# generate with:  openssl rand -hex 32   (do this yourself; never reuse across env)
JWT_SECRET=CHANGE_ME_run_openssl_rand_hex_32
JWT_ALGORITHM=HS256
JWT_ACCESS_EXPIRE_MINUTES=30
JWT_REFRESH_EXPIRE_DAYS=7

# ---- Environment ----
ENVIRONMENT=sit
DEBUG=false
DOCS_ENABLED=true          # ok for sit; production forces both false

# ---- Firebase (public project id, not a secret) ----
FIREBASE_PROJECT_ID=posternung

# ---- OTP / rate-limit ----
OTP_RATE_LIMIT_PER_10MIN=5
OTP_MAX_ATTEMPTS=5

# ---- Reservation TTL (F3) ----
RESERVE_TTL_MINUTES=15

# ---- CORS ----
CORS_ORIGINS=https://your-sit-frontend.example

# ---- Image to run (set to the sha you built in Prerequisites) ----
IMAGE_REGISTRY=ghcr.io/chanothai/posternung-backend
IMAGE_TAG=CHANGE_ME_git_sha
```

> Security: never commit `.env.sit`, don't reuse `JWT_SECRET`/DB password across
> environments, and generate `JWT_SECRET` yourself with `openssl rand -hex 32`.

## Step 5 — Pull the image and start
```bash
cd /opt/posternung
docker compose -f docker-compose.yml -f docker-compose.sit.yml --env-file .env.sit pull app
docker compose -f docker-compose.yml -f docker-compose.sit.yml --env-file .env.sit up -d --no-build
```
The app container runs `alembic upgrade head` on start (migrations are automatic),
then serves on port 8000. Watch it come up:
```bash
docker compose -f docker-compose.yml -f docker-compose.sit.yml --env-file .env.sit logs -f app
# look for: "alembic ... running upgrade" then "Uvicorn running on http://0.0.0.0:8000"
```

## Step 6 — Smoke test (on the server, via localhost)
UFW only allows 22/80/443, so port 8000 is **not** reachable from outside yet —
test locally on the server:
```bash
curl -s localhost:8000/health                 # -> {"status":"ok"}
curl -s localhost:8000/ready                   # -> database "up"
curl -s localhost:8000/api/v1/posters          # -> {"items":[],"total":0,...}
```
If all three return correctly, M1 is done — the app is deployed and running.

---

## What's next (later milestones)
- **M2 — external HTTPS:** put a reverse proxy (Caddy recommended — automatic
  Let's Encrypt TLS) on 80/443 → `app:8000`, matching the UFW rules. Then the API
  is reachable at `https://<domain>`.
- **M3 — CI/CD auto-deploy:** wire the existing GitHub Actions pipeline to this
  host (docker context over SSH recommended, so no CI runner lives on the hardened
  box), set `vars.DEPLOY_TARGET` + Environment secrets + required-reviewer gates,
  then a merge to master deploys automatically.

## Useful operations
```bash
# status / logs / restart / stop
docker compose -f docker-compose.yml -f docker-compose.sit.yml --env-file .env.sit ps
docker compose -f docker-compose.yml -f docker-compose.sit.yml --env-file .env.sit logs --tail=100 app
docker compose -f docker-compose.yml -f docker-compose.sit.yml --env-file .env.sit restart app
docker compose -f docker-compose.yml -f docker-compose.sit.yml --env-file .env.sit down   # stop (keeps pgdata-sit volume)

# deploy a new image sha later: edit IMAGE_TAG in .env.sit, then:
docker compose -f docker-compose.yml -f docker-compose.sit.yml --env-file .env.sit pull app
docker compose -f docker-compose.yml -f docker-compose.sit.yml --env-file .env.sit up -d --no-build
```
The `pgdata-sit` volume persists across `down`/`up`, so DB data survives redeploys.
