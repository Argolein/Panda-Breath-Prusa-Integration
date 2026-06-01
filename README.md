# Panda Breath Prusa Bridge

Use a Raspberry Pi as a small Moonraker-style bridge so a BigTreeTech Panda Breath can follow the bed target of a Prusa Core One over PrusaLink.

## TL;DR

Clone the repo on the Pi and run:

```bash
git clone https://github.com/Argolein/Panda-Breath-Prusa-Integration.git
cd Panda-Breath-Prusa-Integration
chmod +x install.sh
./install.sh
```

The installer asks for:

- the PrusaLink URL
- the auth method
- your PrusaLink login or API key

At the end it writes `config.json`, installs a `systemd` service, and can start it right away.

It installs into the cloned repo directory and runs the service as the current Linux user.

Then point the Panda Breath to:

- `Printer IP`: your Pi IP
- `Port`: `7126`

The bridge itself always listens on `0.0.0.0:7126`. You do not need to set that manually in the installer.

## What it does

The Panda Breath expects a Klipper or Moonraker-like target. The Prusa Core One does not speak that protocol directly, so this bridge does the translation:

1. Panda Breath opens a WebSocket to `/websocket`
2. The bridge answers the small JSON-RPC subset the Panda actually uses
3. The bridge reads `temp_bed` and `target_bed` from PrusaLink
4. Those values are exposed back as `heater_bed.temperature` and `heater_bed.target`

## Why this works

This setup was tested against a real Panda Breath and a real Core One. The Panda does not need a full Moonraker server here. It repeatedly asks for `printer.objects.query` over WebSocket, and that is what this bridge serves.

## Safety behavior

If PrusaLink times out, rejects auth, returns bad JSON, or is otherwise unavailable, the bridge does not crash. It falls back to:

- `heater_bed.target = 0.0`
- `heater_bed.temperature = 0.0`

Requests are cached for a short time to avoid hammering PrusaLink on every Panda poll.

## Files that matter

- `app.py` starts the bridge
- `panda_prusa_bridge/` contains the server, config loader, and PrusaLink client
- `install.sh` handles setup and `systemd` installation

## Manual checks

Check PrusaLink directly:

```bash
curl --digest -u 'YOUR_USER:YOUR_PASSWORD' -sS http://YOUR-PRUSA-IP/api/v1/status
```

Check the bridge:

```bash
curl -sS http://YOUR-PI-IP:7126/healthz
curl -sS http://YOUR-PI-IP:7126/server/info
curl -sS http://YOUR-PI-IP:7126/printer/objects/query
```

Watch logs:

```bash
sudo journalctl -u panda-prusa-bridge.service -f
```

Re-run the installer later if you want to change the target printer or credentials.

## Notes

- Default port is `7126` to stay out of the way of the usual Moonraker port `7125`.
- The bridge uses Python standard library only. No Python package install is required.
