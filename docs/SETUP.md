# Setting up the server

Plain steps to get Edgewise running on your own server. You only do this once. Every
command is copy-paste: run it, wait for it to finish, then do the next one.

## What you need first

1. **A small server (VPS)** with Ubuntu 24.04 and at least 2 GB of memory. Pick a Sydney
   data centre if the provider offers one.
2. **A web address** for the app, such as `edgewise.yourname.com`. In your domain
   provider's settings, add an **A record** for it pointing at the server's IP address.
3. **An authenticator app** on your phone: Google Authenticator, Microsoft Authenticator
   or 1Password all work.

## 1. Connect to the server

On your computer, open a terminal (on Windows: PowerShell) and run, using your server's IP:

```bash
ssh root@YOUR-SERVER-IP
```

## 2. Install Docker and a firewall

```bash
curl -fsSL https://get.docker.com | sh
```

```bash
ufw allow OpenSSH && ufw allow 80 && ufw allow 443 && ufw --force enable
```

## 3. Get Edgewise

```bash
git clone https://github.com/Kairon-vairon/betmodel.git && cd betmodel
```

## 4. Fill in the settings file

```bash
cp .env.example .env && nano .env
```

Fill in these four lines (leave the rest for now):

| Setting | What to put |
|---|---|
| `APP_SECRET_KEY` | Run `openssl rand -hex 32` in a second terminal and paste the result |
| `OWNER_EMAIL` | Your email address: this is your sign-in name |
| `DOMAIN` | Your web address, e.g. `edgewise.yourname.com` (no `https://`) |
| `POSTGRES_PASSWORD` | Run `openssl rand -hex 24` and paste the result |

Save with **Ctrl+O**, **Enter**, then exit with **Ctrl+X**.

Keep a copy of `APP_SECRET_KEY` in your password manager. Without it, the sign-in code
setup can't be read and you would have to set up the authenticator app again.

## 5. Start it

```bash
infra/stack live up -d --build
```

The first time takes a few minutes. Then check everything is running:

```bash
infra/stack live ps
```

You should see `db`, `api`, `worker`, `web` and `caddy`, all `Up`, with `api` showing
`(healthy)`.

## 6. Create your login

```bash
infra/stack live exec api edgewise create-owner
```

It asks for a password (at least 12 characters), then shows a QR code. Scan it with your
authenticator app and type the 6-digit code it shows. If the QR code is too big for the
window, make the terminal larger or type in the key shown under it by hand.

## 7. Record your starting bankroll

Use the amount you've set aside for betting:

```bash
infra/stack live exec api edgewise deposit 2000 --note "opening bankroll"
```

## 8. Open it on your phone and computer

Go to `https://` + your web address. Sign in with your email, password and the code from
the authenticator app.

- **Android (Chrome):** menu **⋮**, then **Install app** (or **Add to Home screen**).
- **Computer (Chrome or Edge):** the install icon at the right of the address bar.

## Everyday commands

Run these from the `betmodel` folder on the server.

| To | Run |
|---|---|
| Update to the latest version | `git pull && infra/stack live up -d --build` |
| See what's running | `infra/stack live ps` |
| Read the worker's log | `infra/stack live logs --tail 100 worker` |
| Restart everything | `infra/stack live restart` |
| Stop everything | `infra/stack live stop` |
| Add money to the bankroll record | `infra/stack live exec api edgewise deposit 500` |
| Take money out of the bankroll record | `infra/stack live exec api edgewise withdraw 500` |
| New phone or lost authenticator | `infra/stack live exec api edgewise reset-2fa --username YOUR-EMAIL` |
| Forgot password | `infra/stack live exec api edgewise set-password --username YOUR-EMAIL` |

Resetting the authenticator or password signs you out on every device.

## Backups

Automatic nightly backups to off-server storage are planned. Until then, make a copy
by hand and download it to your computer:

```bash
infra/stack live exec -T db pg_dump -U edgewise edgewise | gzip > edgewise-$(date +%F).sql.gz
```

## The lab version

The lab is Claude's copy of the software. It runs as a separate stack with its own
database, can't send alerts, and has no public address. It is set up later, once Phase 1
is collecting real data (see `docs/RELEASE_PROCESS.md`).
