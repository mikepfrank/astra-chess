# Player instructions and personas

The model profile chooses the model, provider, routing, reasoning and tool
interface. The persona chooses the player's name, voice and optional chess
preferences. They are independent: changing a persona never changes the model.

`ASTRA_PERSONA=astra` or `ASTRA_PERSONA=arcturus` selects the persona for **new
games**. Without that setting, the Astra model profile uses Astra and the
OpenRouter GLM profile uses Arcturus. The UI shows the persona name separately
from the model identity. A configured persona can be used with either model;
the trusted runtime identity always states the actual model.

- [player.md](player.md) contains the common chess method and host boundaries.
  It has no model-specific persona name.
- [personas/astra-v1.md](personas/astra-v1.md) contains Astra's concise persona.
- [personas/arcturus-v1.md](personas/arcturus-v1.md) preserves Mike's supplied
  Arcturus v1.0 handoff block verbatim as the version 1 **draft** source. Its
  UTF-8 text SHA-256 is
  `304f40730cb7a77126694d0125eb9fa1bafb0cb8e624ae4b5180a7b1028c347a`.
- [personas/integration-v1.md](personas/integration-v1.md) scopes that creative
  source under the shared host rules. Names, anecdotes and prices in the lore
  are not verified current facts. `chess_status` governs the board; engine scores
  favor the query root. Opening preferences use the model's own knowledge and
  permitted chess tools. Museum captions do not authorize filesystem work,
  replay generation or publication. Costs are never guaranteed by the persona.
- [legacy/player-v1.md](legacy/player-v1.md) is the immutable pre-persona prompt.
  Its normalized-text hash is checked when an older game resumes.

`new_player_binding(config)` composes the selected source, integration note,
common method and model-specific tool interface into trusted base instructions.
Each newly created game privately saves the complete prompt, persona metadata,
prompt/source hashes, model profile and tool-schema hash. The supervisor passes
this binding privately to Codex; `chess_status` and public snapshots expose only
the player name, persona ID/version and model identity, never prompt text or
persona source.

`game_player_binding(state, config)` resumes the recorded persona and prompt,
including after game end. A changed default or edited source affects later games
only. Earlier experimental games that lack a full snapshot use their exact
hash-matched legacy prompt and retain the names Astra or GLM 5.3 Flash. This
resolution is read-only: it does not rewrite game or Codex recovery records.
Underlying model, tool-schema, runtime-version and engine checks still apply.
Missing or inconsistent snapshot fields fail closed rather than selecting a
new persona silently.

For future revisions, add a versioned persona or integration source and update
the registry in `astra_web/player_profiles.py`; keep old sources and the legacy
prompt. The Arcturus source stays separate from the integration note so its
wording can be reviewed independently of how the chess host interprets it.
