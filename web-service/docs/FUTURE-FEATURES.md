# Deferred Arcturus features

## Image attachments in chat — assessed September 14, 2026

**Status: deferred by Mike; not implemented, not deployed.** After discussing
feasibility, Mike asked to keep this as a possible future feature and complete
repository/handoff housekeeping first. This note is not authorization to start
the feature in a resumed session.

The proposed interaction is a `+` button beside the composer, a device file
picker, thumbnail preview and removal, followed by Send with optional accompanying
text. A reasonable first scope is one JPEG, PNG or WebP per message, automatically
resized. Clipboard paste or multiple attachments can be considered separately.

### Verified interfaces and unverified compatibility

- The [OpenRouter GLM-5.3 Flash model page](https://openrouter.ai/z-ai/glm-5.3-flash)
  listed text, image and video input at the September 14 check.
- [Codex app-server turn input](https://learn.chatgpt.com/docs/app-server#turns)
  accepts `text`, `image` with a URL, and `localImage` with a file path. The locally
  generated 0.154.0-alpha.6.2 schema also contains these input variants; it is not
  a substitute for testing the deployed stable 0.154.0 executable.
- The [OpenRouter image guide](https://openrouter.ai/docs/guides/overview/multimodal/image-understanding)
  documents URL and inline base64 input through Chat Completions. Our service
  uses the Responses endpoint, so that guide alone does not prove our exact
  route's image compatibility.
- No image has been sent through the complete deployed **Codex → gateway →
  OpenRouter Responses → GLM** chain for this proposal. The first implementation
  step should be a disposable harmless-image compatibility test, including a
  tool continuation and saved-thread resume. Keep the selected model and
  throughput-routing intent; verify image support for eligible providers rather
  than assuming every endpoint supports identical capabilities.

### Existing code boundaries

The composer and message API are text-only. The API accepts JSON bodies up to
16 KiB, rejects unexpected fields, and requires text. `chess_game.message`
persists only message ID, author, text, ply and timestamp. `codex_bridge.py`
supplies one native text item at `turn/start`; status-tool output is also JSON
inside text. Adding an image URL or base64 to those text fields would not be
native visual input.

The gateway's `_prepare_request` forwards the input content while validating
the model, instructions and tools; it does **not** currently strip images. Its
8 MiB request cap and the bridge's 2 MiB JSON-RPC frame cap are separate from
token/context limits. The archive reader has a separate 12 MB record bound.
Do not simply raise all limits to accommodate original camera photos.

### Implementation considerations

1. Add authenticated, game-owned upload and image-read endpoints with the
   existing session, ownership and CSRF boundaries. Decode and validate allowed
   formats, normalize orientation, resize, strip unnecessary metadata, and bound
   bytes, pixels, count and aggregate storage. Do not accept client-selected
   server filesystem paths or fetch arbitrary user-supplied URLs.
2. Store image blobs separately from SQLite game JSON; save attachment IDs and
   metadata with messages. Render private thumbnails and preserve unsent text
   and attachment selections after recoverable submission errors.
3. Pass the associated image as native Codex input beside its accompanying text.
   A `localImage` path refers to a server-side upload, not the user's device.
   Built-in `view_image` need not be enabled for this design. Keep the High-chat /
   Max-move selection derived from authoritative game state.
4. Define delivery across retries, messages arriving during a response, process
   restart, resumed threads and compaction. Avoid duplicating image bytes in
   every text snapshot or indefinitely growing request history. Preserve the
   harness board as authoritative if an uploaded screenshot disagrees with it.
5. Decide attachment lifetime and public-replay behavior explicitly. Current
   replay schemas/renderers export text only. The proposed default is private
   attachments, with publication requiring an explicit image-sharing choice;
   omission markers can preserve conversational context until image replay
   support exists. This sharing policy is a proposal, not a deployed feature.

This is moderate work across UI, persistence, transport and replay behavior.
The provider/native-Codex compatibility test should precede the complete upload
implementation. Images may add input cost and latency; no performance claim
was tested during the feasibility discussion.
