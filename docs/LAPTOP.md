# Running Edgewise on your own computer

Your laptop becomes the server. Everything runs inside **Docker Desktop**, a free app
that runs Edgewise's parts (database, background worker, app) in sealed boxes, so
nothing else on your computer is changed. The steps are the same on Mac and Windows
apart from steps 1 and 3.

You'll need about 20 minutes and an authenticator app on your phone (Google
Authenticator, Microsoft Authenticator or 1Password).

## 1. Install Docker Desktop (once)

Go to **https://www.docker.com/products/docker-desktop/** and download Docker Desktop.
It's free for personal use.

**Mac**
1. Pick the right download. To check which chip you have, click the Apple logo at the top-left of
   the screen > **About This Mac**: "Apple M…" means **Apple Silicon**; "Intel" means **Intel chip**.
2. Open the downloaded `Docker.dmg` and drag **Docker** into **Applications**.
3. Open **Docker** from Applications. Accept the terms and skip the sign-in (no
   account needed).
4. Wait until the whale icon in the menu bar at the top of the screen stops moving.

**Windows**
1. Run the downloaded **Docker Desktop Installer**. Keep **Use WSL 2** ticked.
2. Restart the computer when it asks.
3. Open **Docker Desktop** from the Start menu. Accept the terms and skip the sign-in.
4. Wait until the bottom-left corner of the Docker Desktop window says
   **Engine running**.

Then, on both: in Docker Desktop, open **Settings** (gear icon) > **General** and tick
**Start Docker Desktop when you sign in**, so Edgewise is there whenever the laptop is.

## 2. Download Edgewise (once)

Download the code as a ZIP file:
**https://github.com/Kairon-vairon/betmodel/archive/refs/heads/main.zip**

Until the first version is approved into `main`, use this link instead:
**https://github.com/Kairon-vairon/betmodel/archive/refs/heads/build/phase-1-foundations.zip**

Unzip it (Mac: double-click it in Downloads; Windows: right-click it > **Extract All**).
Move the folder that comes out into **Documents** and rename it to **betmodel**.

## 3. Open a terminal in the betmodel folder

A terminal is a window where you type commands. Each command below is one line: copy
it, paste it into the terminal, press **Enter**, and wait for it to finish.

**Mac:** open **Terminal** (press **⌘ Space**, type `Terminal`, press Enter). Type `cd `
(with a space after it), drag the **betmodel** folder from Finder into the Terminal
window, and press **Enter**.

**Windows:** open the **betmodel** folder in File Explorer. Click the address bar at the
top, type `powershell` and press **Enter**. A blue PowerShell window opens in the folder.

## 4. Start Edgewise

```bash
docker compose up -d --build
```

The first time takes 5–10 minutes (it downloads and builds everything). Then check:

```bash
docker compose ps
```

You should see four lines, `api`, `db`, `web` and `worker`, all **Up**, and `api`
**(healthy)**. If `api` says **(health: starting)**, wait 30 seconds and check again.

## 5. Create your login (once)

```bash
docker compose exec api edgewise create-owner
```

It asks for:
1. **Your email.** This is your sign-in name.
2. **A password**, twice (at least 12 characters). Nothing appears while you type.
   That's normal.
3. Then it shows a **QR code**. Scan it with your authenticator app. If the QR code
   looks garbled, add the account by hand instead: in the app choose **Enter a setup
   key** and type the key shown under the QR code.
4. **The 6-digit code** the app now shows for Edgewise.

## 6. Record your starting bankroll (once)

Use the amount you've set aside for betting:

```bash
docker compose exec api edgewise deposit 2000 --note "opening bankroll"
```

## 7. Open it

Open **http://localhost:8080** in Chrome or Edge on the laptop and sign in with your
email, password and a code from the authenticator app.

To get an Edgewise icon like any other app: click the **install** icon at the right
end of the address bar (or the browser menu > **Install**).

## Every day

Edgewise runs by itself whenever Docker Desktop is running. While the laptop is asleep
or off, nothing runs.

Run these commands in a terminal in the betmodel folder (step 3):

| To | Run |
|---|---|
| See if it's running | `docker compose ps` |
| Stop it | `docker compose stop` |
| Start it again | `docker compose start` |
| Read the background worker's log | `docker compose logs --tail 100 worker` |
| Add money to the bankroll record | `docker compose exec api edgewise deposit 500` |
| Take money out of the bankroll record | `docker compose exec api edgewise withdraw 500` |
| New phone or lost authenticator | `docker compose exec api edgewise reset-2fa --username YOUR-EMAIL` |
| Forgot password | `docker compose exec api edgewise set-password --username YOUR-EMAIL` |

**Updating to a new version:** download the new ZIP, replace the betmodel folder with
it, then run `docker compose up -d --build`. Your bets, bankroll and login are kept:
they're stored in Docker, not in the folder.

## Backups

Make a copy of everything in a file called `edgewise-backup.sql` in the betmodel folder,
then keep that file somewhere safe (a USB stick or cloud drive):

```bash
docker compose exec db pg_dump -U edgewise -f /tmp/edgewise-backup.sql edgewise
```

```bash
docker compose cp db:/tmp/edgewise-backup.sql edgewise-backup.sql
```

## Good to know

- **Only this laptop can open the app.** `http://localhost:8080` means "this computer",
  so your phone can't open it, and nobody on the same Wi-Fi can either. Phone access
  needs a private, secure link to the laptop (for example with Tailscale); ask Claude
  when you want to set that up.
- **The laptop has to be awake to work.** That's fine while the data feeds aren't
  connected. Once Edgewise starts scanning prices, a laptop that sleeps overnight will
  miss most kick-offs (11pm–7am Sydney time). Keep it plugged in with sleep turned off,
  or move to a small server later (see `docs/SETUP.md`).

## If something goes wrong

| What you see | What to do |
|---|---|
| `docker: command not found`, `Cannot connect to the Docker daemon`, `error during connect`, or (Windows) `failed to connect to the docker API at npipe:...dockerDesktopLinuxEngine` | Docker Desktop isn't running. Open it from the Start menu (Mac: Applications) and wait until it says **Engine running** (step 1, point 4). Check with `docker version`: it should list a **Server** section. Then try again. |
| Windows: Docker Desktop shows an error mentioning **WSL** | Open PowerShell as administrator (Start menu, type `PowerShell`, right-click > **Run as administrator**), run `wsl --update` (or `wsl --install` if it says WSL isn't installed), restart the computer, then open Docker Desktop again. |
| Windows: **Virtualization support not detected** | Virtualization is switched off in the laptop's start-up (BIOS) settings and has to be turned on there. The steps depend on the laptop brand: ask Claude, with the make and model. |
| Windows: the tray whale menu offers **Switch to Linux containers** | Click it. Edgewise needs Linux containers (the default). |
| `port is already allocated` | Another app uses port 8080. Mac: `echo "EDGEWISE_PORT=8081" > .env`. Windows: `Set-Content .env "EDGEWISE_PORT=8081"`. Then run `docker compose up -d` and open http://localhost:8081. |
| The page doesn't open | Run `docker compose ps`. If something isn't **Up**, run `docker compose up -d` and wait a minute. |
| "Too many attempts" when signing in | Wait 15 minutes. Five wrong tries lock sign-in for 15 minutes. |

To delete Edgewise and **all its data** (bets, bankroll, login) for good:
`docker compose down -v`
