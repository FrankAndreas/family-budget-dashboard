# Deploying Family Budget on a Synology NAS (or any Docker system)

The app runs as two containers from images on GitHub Container Registry (GHCR):

- **backend** (`ghcr.io/frankandreas/family-budget-dashboard/backend`): the API, with the SQLite
  database in `./data`
- **frontend** (`ghcr.io/frankandreas/family-budget-dashboard/frontend`): nginx serving the app on
  port 8080 inside the container, forwarding `/api` to the backend

Same setup as the family-chore app (SQLite variant), so both run side by side on one NAS.

## Prerequisites
- A Synology NAS with **Container Manager** (Docker) installed.
- SSH access to the NAS (**Control Panel → Terminal & SNMP → Enable SSH**).
- If the GitHub repository or its packages are **private**, a GitHub token with `read:packages`
  (see [Automatic Updates](#automatic-updates)).

## Installation

1. **Choose the user the app runs as** (recommended). The backend container runs as a DSM user, so
   the app's files belong to a real, unprivileged account. Reuse the user you created for family-chore,
   or create one in **Control Panel → User & Group → Create** (e.g. `familyapps`), with a random password
   and no application permissions. On the shared folder that holds the app folder (e.g. `docker`), give
   it **Read only** (or no access): the nightly update runs as root, so the app's user must not be able
   to change `compose.yaml` or `nas-update.sh`. It still writes `data/`, because it owns it. Look up
   its IDs over SSH:
   ```bash
   id familyapps    # e.g. uid=1031(familyapps) gid=100(users)
   ```
   Skip this step to run as the image's built-in user instead (999:999).
2. **Prepare the folder.** Create the app folder (e.g. `/volume1/docker/family-budget`) and upload
   `docker-compose.yml` into it **renamed to `compose.yaml`**. Then create the data folder, owned by the
   app's user:
   ```bash
   cd /volume1/docker/family-budget
   sudo mkdir -p data
   sudo chown -R 1031:100 data    # the IDs from step 1, or 999:999
   ```
3. **Create `.env`** with the user's IDs, the port and the family hub (see `.env.example` for all settings, and
   [Logging in: the family hub](#logging-in-the-family-hub)):
   ```bash
   printf 'PUID=1031\nPGID=100\nPORT=8081\nHUB_URL=http://<NAS_IP>:8086\nHUB_PUBLIC_URL=https://home.local.<domain>\n' | sudo tee .env
   sudo chmod 600 .env
   ```
   `PORT` is the port on the NAS (default 8081; family-chore uses 8080).
4. **Start** it:
   ```bash
   sudo docker-compose pull
   sudo docker-compose up -d
   ```
   Or in Container Manager: **Project → Create**, choose the folder (it must contain `compose.yaml`
   and `.env`), **Next → Done**.
5. Set up [HTTPS at home](#https-at-home-recommended) and open `https://budget.local.<domain>`: the family hub's
   login only reaches the app at an address under `local.<domain>`.

### Logging in: the family hub

The app has no PINs or users of its own: the family logs in at the family hub (FrankAndreas/family-hub, its
README_DOCKER.md), which sets its login for every app at `*.local.<domain>`. Set it up first, then in the hub's
**Einstellungen → Apps**:

1. Add the app (or edit its tile): home address `https://budget.local.<domain>`, **App key** `budget` (the app's
   `HUB_APP_KEY`), and tick everyone who uses it, including younger children (they see their own costs, read-only).
2. Opening the app without a login sends you to the hub and back. The people come from the hub within a minute; in
   **Settings → Family** you set what only this app knows: Jugendlohn or not, and receipt-mail addresses.

Someone whose access is taken away (or who is deactivated) in the hub is hidden here with all their data; if they get
access again, it is all back. **Settings → Family → Removed in the family hub** deletes their data for good.

PINs, the language and logging out on every device are in the hub; **Log out** here goes to the hub, which ends the login for all
family apps and shows its login. For English as the default of a new database's categories, set `DEFAULT_LANGUAGE=en` in `.env`.

**Switching an existing installation** to the hub: add `HUB_URL`, `HUB_PUBLIC_URL`, and `HUB_APP_KEY` to
the backend's `environment:` in the NAS's `compose.yaml` (as in `docker-compose.yml`; a value only
in `.env` doesn't reach the container), set them in `.env`, then `sudo docker-compose up -d`. A person from before the
hub is linked to the hub person with the same name and role at the first login, and only then (rename one of them
first if they differ; tick everyone who had an account here before that first login). Someone left unlinked stays
under **Removed in the family hub**, where a parent deletes their data;
`SECRET_KEY` and `INITIAL_ADMIN_PIN` are no longer used.

`data/` holds everything worth keeping: the database `budget.db` and the stored receipts in
`data/attachments/`. Back up the whole folder: the update script's database backup does not include the receipts.

### HTTPS at home (recommended)

The family hub's login only reaches the app at `https://budget.local.<domain>` (its cookie is for `local.<domain>`
and needs HTTPS), and on plain HTTP it would cross the Wi-Fi unencrypted, where any device on the network (guest
Wi-Fi, a smart-home gadget) could read it. The NAS's own reverse proxy fixes this
with a free Let's Encrypt certificate. You need a domain whose DNS is at Cloudflare (the one the receipt mails use is
fine). Nothing is opened to the internet: the names point to the NAS's home address, and the router forwards no port.

The example names are `budget.local.<domain>` for the app and `nas.local.<domain>` for DSM. One wildcard
certificate for `*.local.<domain>` covers all of them.

1. **DNS record.** In the Cloudflare dashboard: your domain → **DNS → Records → Add record**: type `A`, name
   `*.local` (with the star), IPv4 address `<NAS_IP>`, proxy status **DNS only** (grey cloud). Records you already
   have, such as the tunnel's, keep working: a name of its own wins over the wildcard. Check from a home device:
   ```bash
   nslookup budget.local.<domain>    # must answer <NAS_IP>
   ```
   If it answers but the browser can't connect, or it answers nothing although the record is there, the router
   blocks DNS answers with home addresses. Then use the **DNS Server** package on the NAS instead.
2. **Certificate.** DSM's built-in Let's Encrypt can't issue a wildcard certificate for your own domain, so use
   [acme.sh](https://github.com/acmesh-official/acme.sh) on the NAS with a Cloudflare API token that may edit that
   zone's DNS (acme.sh adds a short-lived `_acme-challenge` record and removes it again). Keep the token in
   acme.sh's config, never in this folder. As root (`sudo -i`; acme.sh refuses `sudo <command>`), with acme.sh in
   `~/.acme.sh` of your DSM user:
   ```bash
   ACME=/var/services/homes/<user>/.acme.sh
   $ACME/acme.sh --issue --dns dns_cf -d '<domain>' -d '*.local.<domain>' --ecc --home $ACME
   # Copy it into DSM; acme.sh remembers this, so every renewal updates DSM too
   env SYNO_USE_TEMP_ADMIN=1 SYNO_CERTIFICATE="<domain>" $ACME/acme.sh --deploy -d '<domain>' --ecc \
     --deploy-hook synology_dsm --home $ACME
   ```
   `SYNO_CERTIFICATE` is the description of the certificate in **Control Panel → Security → Certificate**; a new
   one is created if none has it. For renewals, add a daily task in **Control Panel → Task Scheduler → Create →
   Scheduled Task → User-defined script**, user `root`:
   `/var/services/homes/<user>/.acme.sh/acme.sh --cron --home /var/services/homes/<user>/.acme.sh`.
   Certificates last 90 days and are renewed after 60, so a failed renewal leaves a month to notice it.
3. **Reverse proxy.** **Control Panel → Login Portal → Advanced → Reverse Proxy → Create**:

   | | Source | Destination |
   |---|---|---|
   | App | HTTPS, `budget.local.<domain>`, port 443, **Enable HSTS** | HTTP, `localhost`, port 8081 |
   | DSM (optional) | HTTPS, `nas.local.<domain>`, port 443, **Enable HSTS** | **HTTPS**, `localhost`, port 5001 |

   For DSM also add **Custom Header → Create → WebSocket**. HSTS makes a browser use HTTPS on its own after the
   first visit.
4. **Assign the certificate.** **Control Panel → Security → Certificate → Settings**: pick the `*.local.<domain>`
   certificate for both reverse proxy entries.
5. **Open** `https://budget.local.<domain>` on each phone (type `https://` the first time) and save it to the home
   screen, or open it from the family hub's start page.

Port 8081 stays open on plain HTTP: the Cloudflare tunnel for [receipt mails](#receipt-mails-cloudflare-email-worker-optional)
reaches the app there. That last step stays inside the NAS when the tunnel runs on it; the logins never take it.

### Reading receipts with the Infomaniak AI (optional)

A receipt (photo, PDF, or an e-mail saved as `.eml`) becomes one booking with its items; the AI reads it and you
check everything before it is booked. Only the file and the names of your expense categories and tags are sent.

What the AI service sees (Infomaniak processes it in Switzerland and says it doesn't use it for training):

- **Photos:** the whole picture (without the phone's location data), so everything printed on the receipt, including
  what was bought. Pharmacy or doctor bills reveal health information: scan those with **Read with AI** off.
- **PDFs and mails:** their text without e-mail addresses, phone numbers and the From/To lines of a forwarded mail;
  names and street addresses in the text still go.
- **Bank statements** (category suggestions): only the booking texts no rule knows, without IBANs, card numbers or
  amounts. TWINT and transfer texts between people (they carry the person's name) are never sent.

1. In the Infomaniak Manager, create an API token with **only the `ai-tools` scope** and a lifetime (e.g. one year),
   and note the AI product's ID (*Cloud Computing → AI Tools*). Set a **spending limit** on the AI product.
2. Put both in `.env` on the NAS (never in the repository):
   `INFOMANIAK_AI_TOKEN=…` and `INFOMANIAK_AI_PRODUCT_ID=…`, then `sudo docker-compose up -d`.
3. Optional: `RECEIPT_AI_MODEL` (default `google/gemma-4-31B-it`) and `RECEIPT_AI_READS_PER_HOUR` (default 30 per
   person; `0` turns reading off while keeping the token).

The NAS needs outgoing HTTPS to `api.infomaniak.com`. Without a token, receipts can still be typed in and attached.

**Settings → Data Management** exports your data as a ZIP of CSV files for analysis (pandas, Jupyter, a
local LLM; a README inside explains the columns) and imports transactions in bulk from a CSV or JSON file,
for example one written by a receipt-reading tool. The import format is described in
[`docs/import-format.md`](docs/import-format.md).

### Scanning a pile of receipts with the phone

Parents open the app on the phone (home Wi-Fi) and tap **📷 Scan receipts** in the inbox or above the bookings. The
phone's camera opens; after each photo, **📷 Next receipt** opens it again. Each photo is uploaded right away and
waits in the inbox; the AI reads it in the background (it counts toward the hourly reads of whoever took it). With
**Read with AI** off (e.g. for doctor bills), the photos are never sent to the AI and are typed in when checked.
Later, **Check next** opens the photos one after another in the order they were taken, next to the photo to check
against, and **Book & next** books one and opens the next. Photos stay in the inbox until they are booked or deleted: nothing removes them automatically.

The photos are meant to stay in the app only. After the first deploy, check once on each phone that photos taken
this way don't show up in the phone's gallery (some camera apps keep a copy).

### Receipt mails (Cloudflare Email Worker, optional)

Parents forward receipt mails (webshop orders, invoices) to e.g. `invoice@<domain>`. They wait unopened in an inbox
on the **Accounts** tab; a parent picks the account and **releases** one, then the AI reads it (if set up) and the
usual receipt form opens. Mails are taken only

- if Cloudflare found them authentic (`dmarc=pass`; the worker checks this), and
- from an address registered for a family member in **Settings → Family** (the app checks this).

Everything else is rejected, and the sender gets a bounce. The app stays home-network only: the tunnel opens just
the one path the worker posts to, behind Cloudflare Access. Unreleased mails are deleted after 30 days.

The setup is the same as family-job-tracking's "Incoming e-mails", with these names. Cloudflare renames dashboard
menus from time to time.

1. **Secret for the app.** Add it to `.env`. If your `compose.yaml` is older than this feature, also add the line
   `- INBOUND_SECRET=${INBOUND_SECRET:-}` to the backend's `environment:` (see [Updates](#updates)). Then restart:
   ```bash
   echo "INBOUND_SECRET=$(openssl rand -hex 32)" | sudo tee -a .env
   sudo docker-compose up -d
   sudo docker logs budget-backend 2>&1 | grep "Receipt mails"
   ```
   The log must say `Receipt mails: configured`; `not configured` means the container doesn't get the variable.
   Mails then bounce or go to the fallback address, and the backend answers the worker with 503.
2. **Tunnel route for the worker only.** In **Zero Trust → Networks → Connectors → Cloudflare Tunnels**, open the
   NAS's tunnel → **Published application routes** → **Add**:
   - subdomain e.g. `budget-inbound`, your domain, **path `^/api/v1/inbound$`**
   - service `HTTP`, URL `<NAS_IP>:8081` (the frontend container passes `/api` on to the backend)

   Every other path on this hostname has no route and gets a 404 from the tunnel; the app itself is not
   reachable from outside.
3. **Service token.** **Access controls → Service credentials → Service Tokens → Create Service Token**, name
   `family-budget-inbound`, **Non-expiring**; note the Client ID and Client Secret (shown once).
4. **Policy.** **Access controls → Policies → Add a policy**: name `family-budget-inbound-token`, action
   **Service Auth**, include **Service Token** = `family-budget-inbound`.
5. **Access application.** **Access controls → Applications → Create new application → Public DNS**: subdomain
   `budget-inbound`, your domain, path `api/v1/inbound`, policy `family-budget-inbound-token`; optionally turn on
   **401 Response for Service Auth policies**. Check both layers:
   ```bash
   # without token: 302 or 401 from Cloudflare
   curl -s -o /dev/null -w "%{http_code}\n" -X POST https://budget-inbound.<domain>/api/v1/inbound
   # with token but without the secret: 401 from the app
   curl -s -o /dev/null -w "%{http_code}\n" -X POST -H "CF-Access-Client-Id: <id>" \
     -H "CF-Access-Client-Secret: <secret>" https://budget-inbound.<domain>/api/v1/inbound
   ```
6. **Deploy the worker** from a checkout of this repository, then set its secrets from environment variables, so
   they stay out of the shell history:
   ```bash
   cd cloudflare/email-worker
   npm ci
   npx wrangler login
   npx wrangler deploy
   # APP_URL=https://budget-inbound.<domain>, INBOUND_SECRET from step 1, the token from step 3
   for name in APP_URL INBOUND_SECRET CF_ACCESS_CLIENT_ID CF_ACCESS_CLIENT_SECRET; do
     printf %s "${!name}" | npx wrangler secret put "$name"
   done
   ```
   Optional: `FALLBACK_ADDRESS`, a verified Email Routing destination outside the domain, gets a mail when the app
   can't take it (NAS down, mail over 10 MB) instead of a bounce. Mails from unregistered senders never go there.
7. **Route the address to the worker.** In the regular dashboard: your domain → **Email → Email Routing → Routing
   rules → Custom addresses → Create address** `invoice`, action **Send to a Worker**, `family-budget-inbound`.
8. **Register the addresses** you forward from in **Settings → Family** (one or more per person).
9. **Test:** forward a receipt mail from your registered mailbox to `invoice@<domain>`; it shows on the Accounts tab
   within a few seconds. A mail from an unregistered address must bounce. The first accepted mail also proves that
   Cloudflare puts its check result (`mx.cloudflare.net; … dmarc=pass`) on mails it hands to the worker: without it
   the worker rejects every mail with "Absender nicht bestätigt" (see `npx wrangler tail` while you send one).

The waiting mails are files in `data/attachments/inbox`; they are part of the attachments backup.

## Updates
New images are published as `latest` whenever a change is pushed to `main` and CI passes.
Set up [Automatic Updates](#automatic-updates) to install them nightly, or update by hand:

```bash
sudo docker-compose pull
sudo docker-compose up -d
```

Updates never change your `compose.yaml` or `.env`. When a new feature needs a setting, it is listed in the
backend's `environment:` of this repository's [`docker-compose.yml`](docker-compose.yml): add the same line to the
`environment:` of `budget-backend` in your `compose.yaml`, put the value in `.env`, and run
`sudo docker-compose up -d`. A value only in `.env` doesn't reach the app. To see which settings the backend gets
(names only, no values):

```bash
sudo docker exec budget-backend printenv | cut -d= -f1 | sort
```

## Automatic Updates

`scripts/nas-update.sh` checks for new app images and installs them. Run nightly by DSM's Task Scheduler, it:

1. pulls the backend and frontend images; if nothing is new, it only checks that the backend is healthy
   and stops,
2. backs up the database to `db-backups/` with SQLite's online-backup API (a consistent copy while
   the app runs; keeps at least the newest 5 and everything from the last 7 days),
3. keeps the running images tagged as `:previous` for [rolling back](#rolling-back-an-update),
4. restarts the app and waits until the backend is healthy, logging to `logs/update.log`.

It finds the compose file by its usual names (`compose.yaml`, `docker-compose.yml`, ...) and never
changes it or `.env`. It also removes dangling (untagged) Docker images to save space, including
those of other projects on the NAS.

### Setup
1. Copy `scripts/nas-update.sh` into the app folder (next to `compose.yaml`) and make it executable,
   or let [`deploy-nas.sh`](#deploying-from-your-computer) upload it:
   ```bash
   sudo chmod +x /volume1/docker/family-budget/nas-update.sh
   ```
2. Run it once by hand and check that it ends with "Up to date" or "Update complete":
   ```bash
   sudo /volume1/docker/family-budget/nas-update.sh
   ```
3. In DSM, open **Control Panel → Task Scheduler → Create → Scheduled Task → User-defined script**:
   - **General**: any name (e.g. `Family Budget update`), user **root**
   - **Schedule**: daily, at a quiet time, a few minutes apart from family-chore's update (e.g. 03:45)
   - **Task Settings**: tick **Send run details by email** and **only when the script terminates abnormally**,
     and enter the command:
     ```bash
     bash /volume1/docker/family-budget/nas-update.sh
     ```

If the images are private, log in to the registry once **as root**, since the task runs as root:
`sudo docker login ghcr.io -u <github-user>` with a token that has `read:packages`.

### Database updates
A new version brings its database changes as migrations (`backend/app/migrations`), and the backend applies them
itself when it starts. Nothing to do by hand. `nas-update.sh` backs up the database first.

- A database from before migrations existed is brought up to date on its first start.
- The backend's log shows a warning if old data has broken links between records (e.g. `Broken links in the database:
  budgets: 1 row`). The app still runs; report it as an issue.
- An older version doesn't understand a newer database, so a rollback also restores the backup (below).

### Rolling back an update
If a new version misbehaves, go back to the previous one. First **disable the scheduled task**,
otherwise the next night installs the same version again. Then, in the app folder:

```bash
cd /volume1/docker/family-budget
# 1. Point latest at the previous images (frontend only if it was updated; see logs/update.log)
sudo docker tag ghcr.io/frankandreas/family-budget-dashboard/backend:previous ghcr.io/frankandreas/family-budget-dashboard/backend:latest
sudo docker tag ghcr.io/frankandreas/family-budget-dashboard/frontend:previous ghcr.io/frankandreas/family-budget-dashboard/frontend:latest

# 2. Restore the database from the backup taken right before the update
#    (the new version may have changed it). Changes made since the update are lost.
sudo docker stop budget-backend
sudo sh -c 'gunzip -c db-backups/budget-YYYYMMDD-HHMMSS.sqlite.gz > data/budget.db'

# 3. Start the previous version
sudo docker-compose up -d backend frontend
```

Re-enable the task once a fixed version is published.

### Deploying from your computer
To install the latest version right away, or to roll out a new version of `nas-update.sh`, run from a
checkout of this repository:

```bash
cp .deploy.env.example .deploy.env   # once; then set NAS_HOST and NAS_DIR in it
scripts/deploy-nas.sh
```

It shows how the NAS's `nas-update.sh` differs from the repository's, uploads it after you confirm, and
runs the update. Add `--force` to restart the app even without a new version, e.g. after editing the
compose file on the NAS. The compose file and `.env` belong to your deployment and are never copied.

- Connect once by hand (`ssh user@<NAS_IP>`) to verify and accept the NAS's host key; the script never
  accepts unknown keys.
- **Password:** without further setup, ssh and sudo ask for it. To avoid typing it, set `NAS_PASS_CMD` in
  `.deploy.env` to a command that prints it, e.g. `NAS_PASS_CMD=pass show nas` for the
  [pass](https://www.passwordstore.org/) password manager. The password is piped straight to ssh and
  `sudo` and never stored, shown or logged.
- `.deploy.env` is gitignored, so your NAS address stays out of the repository.

## Running it locally
`docker compose up -d --build` builds both images from your checkout and starts them on
`http://localhost:8081`, with the database in `./data` (create it first, owned by `PUID:PGID`
from `.env`, or run as yourself with `PUID=$(id -u)` and `PGID=$(id -g)`).

For development, run the backend with `uvicorn app.main:app --reload` in `backend/` and the
frontend with `npm run dev` in `frontend/` (http://localhost:3000) instead.

To change the database schema: change `backend/app/models.py`, then from `backend/` let Alembic compare the models
with a database at the latest version and write the migration:

```bash
rm -f /tmp/schema.db && DATABASE_URL=sqlite:////tmp/schema.db alembic upgrade head
DATABASE_URL=sqlite:////tmp/schema.db alembic revision --autogenerate -m "what changed"
```

Check the generated file in `app/migrations/versions/`, and add a test in `tests/test_database.py` if it moves data.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `budget-backend` restarts with *unable to open database file* | `data/` doesn't belong to `PUID:PGID`, or the IDs in `.env` are wrong (check with `id <user>`) | Fix `.env` or `sudo chown -R <PUID>:<PGID> data`, then `sudo docker-compose up -d` and `sudo docker restart budget-frontend` |
| The app keeps sending you to the family hub, or the hub sends you back to its start page | The app isn't opened at `https://budget.local.<domain>`, or the hub's `COOKIE_DOMAIN` is missing in its `.env` | Open the app at its `local.<domain>` address; check the hub's `COOKIE_DOMAIN=local.<domain>` |
| *No access* after logging in | The hub doesn't list the person for the app | In the hub, **Einstellungen → Apps**: the tile needs the key `budget` and the person ticked |
| *The family hub can't be reached* | `HUB_URL` is wrong or the hub is down | Check `HUB_URL` in the backend's environment (`sudo docker exec budget-backend env \| grep HUB`) and the hub's container |
| *Bind for 0.0.0.0:8081 failed: port is already allocated* | Another app uses the port | Set another `PORT` in `.env` |
| Email from Task Scheduler: *up to date, but the backend is not healthy* | The backend keeps crashing without an update, e.g. after a change to `.env` (wrong `PUID`/`PGID`) | Check `logs/update.log`, fix the cause, then `sudo docker-compose up -d` and `sudo docker restart budget-frontend` |
| Email from Task Scheduler: *backend not healthy* | A new version fails to start | Check `logs/update.log` (it ends with the backend's log), then [roll back](#rolling-back-an-update) |
| `http://<name>.local.<domain>` shows *Welcome to Synology Web Station* | The reverse proxy entries listen on HTTPS only; plain HTTP lands on Web Station | Type `https://`; with **Enable HSTS** the browser does it by itself after the first visit |
| *400 The plain HTTP request was sent to HTTPS port* on `nas.local.<domain>` | The reverse proxy talks HTTP to DSM's HTTPS port 5001 | Set the entry's destination protocol to **HTTPS** |
| `nslookup <name>.local.<domain>` says *NXDOMAIN* | The DNS record is named `local` instead of `*.local` | Rename it to `*.local` |
