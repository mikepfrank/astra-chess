# Pause new games while keeping existing games playable

The public Astra service paused new games on October 11, 2026 because of API
costs. Existing games, including suspended games, may continue. This is not a
total spending stop: accepted games and their conversations can still use the API.

## Existing Lightsail installation

Run as `ec2-user` with existing sudo access:

```sh
sudo /usr/bin/python3 -I -B \
  /home/astra/astra-chess/web-service/tools/ops/new_game_admission.py pause

# Reopen only when the operator decides to accept new-game costs again:
sudo /usr/bin/python3 -I -B \
  /home/astra/astra-chess/web-service/tools/ops/new_game_admission.py open
```

The helper uses `/run/lock/astra-caddy-config.lock`, refuses an active Astra
maintenance checkpoint, validates the entire proxy configuration, and changes
only the Astra site block. It installs:

- `/home/astra/.config/astra-chess/new-games.caddy`: a JSON 503 for new-game
  POSTs and a public policy GET; no wildcard game-action block.
- `/etc/systemd/system/astra-caddy.service.d/30-new-game-admission.conf`: exposes
  only that fragment read-only through Caddy's `ProtectHome` sandbox.
- `/home/astra/.local/share/astra-chess/new-games-paused`: persistent application
  admission marker, also recognized by the later backend implementation.

It restarts **only Caddy**, whose admin API is disabled. Shared web connections
can briefly reconnect, but neither chess app nor its AI workers are restarted.
It verifies HTTPS health, policy and denial, rolling back only its own site
block on failure. Backups remain private under `/var/lib/astra-chess-ops/`.
The optional read-only bind and unused fragment may remain after reopening.

Do not remove the marker alone while this proxy gate is installed: run `open`
to remove the import and marker together. The lifecycle helper supports the
exact fragment import and preserves it through maintenance down/up cycles.

The October 11 rollout updates static assets and operator helpers without
restarting or changing the loaded Python application. Its public gate works
independently of the application version. Keep port 8788 loopback-only.

## Application marker for other deployments

The separately prepared backend update checks `ASTRA_DATA_DIR/new-games-paused`
on each creation request. Creating that file pauses admission; removing it
reopens admission without a restart. Missing marker means new games are open.
An installed application guard rejects both colors before game creation or AI
scheduling, and does not block existing-game endpoints. It publishes the policy
at `/api/new-game-policy` and in `/api/config`.

The frontend accepts a 404 policy endpoint for compatibility with older apps.
Proxy policy takes precedence while the Lightsail gate is installed. Do not
use a whole-site shutdown just to change admission.

The notice points to the [deployment guide](../../DEPLOYMENT.md) and explains
that people with their own OpenAI API key and hosting can ask their coding
agent to deploy their own instance.
