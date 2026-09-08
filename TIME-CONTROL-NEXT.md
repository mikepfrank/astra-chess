# User-selected time control for future games

During the continuation of game 10, Mike suggested adopting:

- 90 minutes for Astra's first 40 moves;
- 30 additional minutes after Astra completes move 40;
- a 30-second increment per Astra move, from move 1.

Astra accepted this for future games. The bot's thinking remains excluded.
This records the chosen experimental policy; it is not a claim that every
FIDE classical tournament uses the same control.

Implement and test staged time controls and increments before initializing the
next game. The present ledger's one-hour fixed total and 120-second extension
allocation do not themselves implement stages or increments. Display the exact
effective settings and keep append-only per-move evidence.

Game 10 remains under its original 3600-second allowance plus the separately
authorized 900-second extension. Do not retrospectively apply the new control,
erase the initial overrun, or treat the paused waiting interval as deliberation.
