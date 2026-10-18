# Local Postgres Runbook

This runbook targets a Fedora server running rootless Podman on a local LAN.
Do not expose Postgres to the public internet.

## Start Postgres

```bash
podman volume create local_budget_pgdata

podman run -d \
  --name local-budget-postgres \
  -e POSTGRES_DB=local_budget \
  -e POSTGRES_USER=local_budget \
  -e POSTGRES_PASSWORD='change-this-password' \
  -p 5432:5432 \
  -v local_budget_pgdata:/var/lib/postgresql/data:Z \
  docker.io/library/postgres:17
```

Use a DHCP reservation for the server so the LAN IP remains stable.

## Firewall

Allow Postgres from the LAN subnet only:

```bash
sudo firewall-cmd --permanent --add-rich-rule='rule family="ipv4" source address="192.168.1.0/24" service name="postgresql" accept'
sudo firewall-cmd --reload
```

Adjust `192.168.1.0/24` to match the LAN.

## App Connection

```bash
export DATABASE_URL='postgresql://local_budget:change-this-password@SERVER_LAN_IP:5432/local_budget'
alembic upgrade head
flask --app wsgi:app run
```

The migration chain creates the local `auth.users` compatibility table needed
by existing foreign keys.

## systemd User Service

```bash
mkdir -p ~/.config/systemd/user
podman generate systemd --name local-budget-postgres --files --new
mv container-local-budget-postgres.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now container-local-budget-postgres.service
sudo loginctl enable-linger "$USER"
```

## Backups

Run full logical dumps. Budget data is small enough that full backups are the
right default.

```bash
pg_dump -Fc "$DATABASE_URL" > "local_budget_$(date +%Y-%m-%d).dump"
```

Restore into a scratch database at least quarterly:

```bash
pg_restore --clean --if-exists -d "$DATABASE_URL" local_budget_YYYY-MM-DD.dump
```

Keep at least one backup copy on a different machine.

## Operational Checks

- `podman ps` shows the database container running.
- `alembic current` matches the repository head.
- `pytest -v` passes.
- DB-gated tests run when `DATABASE_URL` points at this database.
