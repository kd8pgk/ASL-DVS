#!/usr/bin/env python3
# =============================================================================
# ASL-DVS-M17 44 Helper  —  asl_dvs_m17_44helper_v0.0.10.py
# =============================================================================
#
# STAGE:      Response to an external audit (not one of the original 8
#             stages, and not a self-initiated fact-check pass like the
#             v0.0.9 one — this is a response to a third-party review
#             of the tunnel-setup logic).
# STATUS:     Reference copy — extensively commented on purpose. Still
#             pre-release.
#
# EXTERNAL AUDIT RESPONSE — each claim checked against the actual code
# and, where the claim was about a source document, against that
# document's real content (not memory of it):
#
#   CONFIRMED ACCURATE, no change needed:
#     - Pi Install's systemd-resolved, wg0.conf/chmod 600, fallback unit,
#       and verify-endpoint claims all matched — consistent with the
#       v0.0.9 pass, re-confirmed here.
#     - Router Install's uci translations (LuCI install, WG interface,
#       LAN IP, firewall zone, port-forwards, static DHCP binding) were
#       correctly characterized as syntactically-standard-OpenWrt but
#       untested against physical hardware — matches this file's own
#       v0.0.9 provenance note.
#     - Security section (private key handling, SSH BatchMode, shlex
#       quoting throughout) — all confirmed accurate against the actual
#       code; nothing to add.
#
#   ONE REAL GAP CONFIRMED AND FIXED:
#     - The audit correctly noted that Step 5's `_build_uci_wg_apply_cmd`
#       commits the new `firewall.wgzone` to uci's config but doesn't
#       reload the firewall — the zone only became live once a LATER
#       step (Model C's zone-fix, or Model B's first port-forward)
#       happened to reload it. The audit called this "a minor sequencing
#       issue, not a functional error," which was fair for the intended
#       in-order flow, but it meant Step 5 could report success/verified
#       while the zone wasn't actually live yet if steps were ever run
#       out of order. Fixed by adding `/etc/init.d/firewall reload` to
#       the end of Step 5 itself — see the fix comment at that exact
#       line for detail.
#
#   TWO CLAIMS CHECKED AND NOT SUPPORTED BY THE ACTUAL SOURCE —
#   corrected here rather than silently accepted or silently ignored:
#     - The audit stated "ARDC guide also suggests adding DNS = 44.1.1.1
#       to the [Interface] section." The full text of
#       https://wiki.ampr.org/wiki/44Net_Connect/Quick_Start/Raspberry_Pi
#       was fetched directly (v0.0.9 pass) and its "Configure your
#       WireGuard client" section says only to create the file and paste
#       the portal-provided config — no DNS line is mentioned anywhere
#       on that page. A web search for this specific claim found no ARDC
#       source for it either; the one hit with a DNS= line was an
#       unrelated third-party blog using a different address entirely
#       (1.1.1.1, not 44.1.1.1). Not incorporated, since it doesn't
#       appear to be a real ARDC recommendation.
#     - The audit stated the "Create zone"/"Attach interface" steps
#       match "the ARDC guide['s] public zone." The same fetched RPi
#       guide page has zero mentions of firewalld, zones, or firewall
#       configuration of any kind — that material is exclusively from
#       the uploaded ASL3 manual, exactly as this file's own §1a.2
#       fact-check note already stated before this audit arrived. Not
#       changed, since the original attribution was already correct.
#
#   ACKNOWLEDGED AS A KNOWN LIMITATION, not fixed (low severity, matches
#   this file's existing pattern of documenting scope boundaries rather
#   than silently having them):
#     - The audit noted Router Install doesn't check for a pre-existing
#       WireGuard interface or conflicting firewall zone before creating
#       one — true. `uci set network.wgclient=interface` against an
#       already-correct existing section is idempotent (uci won't error
#       or duplicate), so this isn't a sharp landmine, but there's no
#       explicit "this already exists, here's what's different" warning
#       either. Left as-is rather than adding speculative conflict-
#       detection UI this pass wasn't scoped for.
#
# VERSIONING: continues the per-change version bump convention.
# =============================================================================
#
# v0.0.11 — Nodes tab, Stage 1 (constants/state only; no parsing, no UI yet).
#
#   SCOPE LOCKED: Scenario B only — separate ASL boxes on the same LAN
#   behind one NAT/public IP (per AllStarLink's "Multiple Nodes on the
#   Same Network" manual page). NOT the single-box/multi-stanza scenario.
#   This instance can only read/write config on the box it runs on; peer
#   boxes need their own running copy. Peer cards in this box's UI can
#   only ever edit THIS box's neighbor-line pointer to a peer, never the
#   peer's own files (matches the existing LAN-only threat model — no
#   SSH/remote-write capability exists or is planned for this tool).
#
#   Added:
#     - [nodes] config section: ASL conf file paths (iax.conf, rpt.conf,
#       extensions.conf, allmon3.ini), bindport recommended range
#       (4560-4580, per the ASL3-appliance-permitted range cited in the
#       manual), and two newline-delimited/pipe-separated storage fields
#       — "peers" and "peer_links" — following the exact shape convention
#       already established by sysmon's services.pinned.
#     - "nodes" added to ui.enabled_tabs and to the TABS list.
#     - RPT_CONF_RESERVED_STANZAS: the non-node-number top-level stanza
#       names in rpt.conf, needed by Stage 2's node-detection pass to
#       distinguish local node stanzas from structural ones.
#
#   Deliberately NOT done in this stage (later stages per the plan):
#     - No rpt.conf/iax.conf/extensions.conf/allmon3.ini parsing yet
#       (Stage 2).
#     - No node detection/merge logic yet (Stage 3).
#     - No guardrail checks yet (Stage 4).
#     - No API endpoints, no writes, no HTML/JS yet (Stages 5-8).
#     - peer_links (Phase 2 cross-instance read-only status fetch) is
#       declared but unused until Stage 9 — Phase 2 stays parked until
#       Phase 1 (Stages 1-8) is complete and confirmed working.
#
# v0.0.12 — Nodes tab, Stage 2 (read-only parsers). Still no detection/
#   merge logic, no guardrails, no API endpoints, no HTML/JS.
#
#   Added:
#     - _parse_asterisk_conf_stanzas(): generic line-aware Asterisk-conf
#       parser (iax.conf/rpt.conf share syntax). Deliberately not
#       configparser — see docstring — and line numbers are captured on
#       every entry specifically so Stage 6's targeted single-line write
#       engine has exact positions to work with, without diffing later.
#     - _read_conf_stanzas(): exists/unreadable/parsed three-state file
#       read, matching the existing _parse_wg0_conf() convention.
#     - parse_iax_conf(): bindport, with the Asterisk-documented implicit
#       default (4569) reported when unset rather than "unknown".
#     - parse_rpt_conf(): full raw stanza structure plus the [nodes]
#       addressing map extracted separately (node -> radio@host[:port]/
#       node,FLAGS). No local-vs-peer classification yet — Stage 3.
#     - parse_extensions_conf(): first `NODE = ` declaration, scanned
#       line-by-line since ASL3's default template doesn't confine it to
#       a stanza.
#     - parse_allmon3_ini(): configparser-based (this file IS standard
#       INI, unlike the other two) — per-node host/port/monport.
#     - build_nodes_parse_snapshot(): runs all four, returns one dict.
#       This is the function Stage 3 (detection) and the eventual
#       /api/nodes/status endpoint (Stage 5) will call.
#
# v0.0.13 — Nodes tab, Stage 3 (detection/merge). Still no guardrail
#   evaluation, no API endpoints, no writes, no HTML/JS.
#
#   SCOPE NOTE: mid-build, decided to pull the "44helper link button"
#   idea (originally Phase 2 / Stage 9) forward rather than deferring it
#   to after Phase 1 is fully done. This stage carries peer_links (the
#   per-peer 44helper URL storage already declared in Stage 1) through
#   the merge so peer cards have the data a link button will need, but
#   does NOT add reachability probing, the button itself, or any UI —
#   those still land whenever peer card rendering is built. Detection/
#   merge logic itself is otherwise exactly per the original Stage 3
#   plan (Scenario B: separate boxes, same LAN/NAT).
#
#   Added:
#     - _parse_rpt_node_target(): parses a [nodes] line's right-hand
#       side ("radio@host[:port]/node,FLAGS") into host/port/flags.
#     - parse_stored_peers(): manually-entered peer bookkeeping
#       (node|ip|port|label), same shape convention as sysmon's
#       services.pinned.
#     - parse_peer_links(): per-peer 44helper URL (node|url) — the
#       pulled-forward Phase 2 data, structural parse only.
#     - _local_node_numbers(): numeric rpt.conf stanzas minus
#       RPT_CONF_RESERVED_STANZAS = this box's own hosted nodes.
#     - build_local_node_cards(): one dict per local node — own [nodes]
#       line, rxchannel, extensions.conf NODE= match. No guardrail
#       verdicts yet (Stage 4).
#     - build_peer_node_cards(): one dict per peer, merged from
#       auto-detected [nodes] entries (ground truth for "wired"),
#       stored peer bookkeeping, and stored peer_links. Locally-hosted
#       nodes are excluded even if their [nodes] entry has a
#       non-loopback host — that mismatch is a Stage 4 guardrail, not a
#       reclassification.
#     - build_nodes_tab_data(): top-level entry point combining box
#       summary + both card lists + the raw Stage 2 snapshot (kept for
#       Stage 4's guardrail pass).
#
# v0.0.14 — Nodes tab, Stage 4 (guardrail engine). Still no API
#   endpoints, no writes, no HTML/JS.
#
#   Added:
#     - build_nodes_guardrails(): evaluates Stage 3's box/local/peer
#       data into findings, same {"level","msg"} shape as the existing
#       _run_self_check() convention, plus a "scope" field
#       ("box"/"local:<node>"/"peer:<node>"/"peers") so Stage 7's HTML
#       can route each finding to its card. Reuses the existing
#       _self_check_worst_level() reducer as-is (it was already generic,
#       not Overview-specific) rather than duplicating it.
#     - Checks implemented: bindport range/default-with-peers-present,
#       local node's own [nodes] line missing/malformed/non-loopback,
#       extensions.conf NODE= mismatch (single-local-node case) or
#       missing, peer not-wired-in, peer line malformed, peer neighbor
#       line missing :port while peer's own bindport isn't the IAX
#       default, this-box-bindport-vs-peer-port collision, and
#       peer-vs-peer port collision.
#     - build_nodes_tab_data() now runs guardrails automatically and
#       includes both "guardrails" (list) and "guardrail_level"
#       (single worst level, for a banner) in its return.
#
# v0.0.15 — Nodes tab, Stage 5 (backend API). Still no HTML/JS — the tab
#   itself won't render anything yet.
#
#   Added, fully functional (bookkeeping only, never touches ASL conf
#   files):
#     - action_upsert_peer() / _serialize_stored_peers(): add-or-update
#       a manually-entered peer. peer_add and peer_edit both call this.
#     - action_remove_peer() / _serialize_peer_links(): removes a stored
#       peer and its associated peer_links URL, if any.
#     - GET /api/nodes/status -> build_nodes_tab_data(), same pattern as
#       /api/overview.
#     - POST /api/nodes/peer_add, /api/nodes/peer_edit, /api/nodes/peer_remove.
#
#   Added, read-only and fully functional:
#     - build_node_snippet() / GET /api/nodes/edit_snippet?scope=... —
#       computes the Save/Copy/Close editor's textarea contents from
#       already-parsed Stage 2/3/4 data. Returns a suggested new line
#       (not an empty editor) when the target line doesn't exist yet.
#
#   Added, deliberately a stub (per plan, the real implementation is
#   Stage 6's write engine):
#     - action_save_node_snippet() / POST /api/nodes/save_snippet — route
#       is wired end-to-end so Stage 7/8's frontend has a stable
#       contract to build against, but returns success=False with an
#       explicit "not implemented yet" message. No backup, no diff, no
#       write happens. This is intentional, not an oversight — matches
#       the file's existing convention of being explicit about what's
#       actually implemented at each stage rather than silently no-op'ing.
# =============================================================================

# =============================================================================
# v0.0.16 — Nodes tab, Stage 6 (write engine). Still no HTML/JS.
#
#   action_save_node_snippet() is no longer a stub — real implementation:
#     - _apply_targeted_conf_edit(): the write primitive. Backs up the
#       target file (timestamped .bak.<YYYYMMDD_HHMMSS> copy) before
#       any write; either replaces one exact line by its 1-indexed line
#       number, or — when the line doesn't exist yet — inserts the new
#       line at the end of the relevant stanza's entries. Every other
#       line in the file is byte-identical before/after. Returns a
#       unified diff (difflib) alongside the result.
#     - action_save_node_snippet() re-resolves path/line_no fresh from
#       disk via build_node_snippet() rather than trusting anything the
#       client sent — protects against writing to a stale line number
#       if the file changed between opening the editor and saving.
#       Validates the submitted text actually matches its scope
#       ('bindport = <number>' for box, '<node> = radio@...' for
#       local/peer) before ever touching the file. Logs to the Actions
#       Log on success, same convention as every other mutating action.
#     - New import: difflib (shutil was already imported).
# =============================================================================

# =============================================================================
# v0.0.17 — Nodes tab, Stage 7 (HTML/CSS/JS). The tab is now live —
#   Stage 1's placeholder card is gone, replaced with real content.
#
#   Small Stage 5 addendum made here (needed once the peer form existed
#   to actually use it): action_upsert_peer() gained a helper_url
#   parameter, persisting to peer_links (parsed since Stage 3, but never
#   settable via the API until now). Empty helper_url clears any
#   previously-stored link rather than leaving a stale one.
#
#   Added:
#     - _render_nodes_panel(): server-rendered stable containers only,
#       same convention as every other Stage-2+ tab (Overview/Pi
#       Install/etc.) — content filled client-side.
#     - CSS: .step-pill.danger (red variant, didn't exist yet — only
#       not_started/attempted_unconfirmed/done did); .nd-editor-wrap /
#       .nd-editor-bar (collapsible per-card editor, same max-height-
#       transition technique as sysmon's .stfu-editor-wrap, just
#       renamed for this file's own class prefix); .nd-link-btn (the
#       44helper link button, using the same --teal accent as
#       .btn-recheck).
#     - JS: renderNodes() builds the guardrail banner, box summary, and
#       one card per local/peer node from GET /api/nodes/status.
#       ndToggleEditor()/ndSave()/ndCopy()/ndClose() are the Save/Copy/
#       Close trio, lazy-loading content on first open via GET
#       /api/nodes/edit_snippet (same "load on first open" behavior as
#       stfuToggleEditor()), confirm-before-save, POST
#       /api/nodes/save_snippet backed by Stage 6's write engine.
#       ndPeerSave()/ndPeerRemove() drive the Add/Update Peer form.
#       ndOpenHelper() is the pulled-forward-from-Phase-2 link button —
#       opens in a reused named tab ('asl_dvs_44h'), same tab-reuse
#       technique as the dashboard's Last-Heard button. No reachability
#       probing yet: the button shows whenever a helper_url is stored,
#       full stop — that's still a deferred piece of work, not
#       implemented in this stage.
#     - Nodes tab is NOT auto-polled like Overview's 5s timer — an open
#       inline editor would get wiped out from under the user on every
#       tick. Refreshed on load, via the Re-check button, and after any
#       save/peer action completes (matching how Pi Install/Firewall
#       already behave — this file doesn't auto-poll anything with a
#       mutating-action panel except Overview, which has none).
#
#   Still not implemented: reachability probing for the 44helper link
#   button (deferred, per the original Phase-2 discussion), and no
#   guardrail "Fix in editor" auto-scroll/highlight — the scope-routed
#   findings are shown inline per-card, but clicking a finding doesn't
#   yet jump-and-open its editor automatically.
#
#   Two real bugs caught during Stage 7 verification, fixed before this
#   version shipped (not left for a later patch):
#     - Astral emoji (💾⎘✕🔗) were written as JS-style UTF-16 surrogate
#       pairs (\uD83D\uDCBE) inside a Python string. Python doesn't
#       decode surrogate pairs the way JS does, so that produced two
#       invalid lone-surrogate codepoints instead of one character —
#       fixed with proper single-codepoint \U0001F4BE-style escapes.
#     - Every onclick="func('...')" built inside the _JS Python
#       triple-quoted string used \' to escape the JS string's quote,
#       but Python's own parser consumes \' down to a bare ' before the
#       JS ever sees it — silently stripping the backslash every JS
#       string escape depended on. Fixed by doubling to \\' so the
#       backslash survives into the actual JS. Caught by actually
#       running the extracted _JS through `node --check` and executing
#       renderNodes() against sample data in a stubbed DOM, not just
#       py_compile — a reminder that this file's own compile+AST checks
#       only validate the Python half of a page that ships JS as data.
# =============================================================================

# =============================================================================
# v0.0.18 — Nodes tab, Phase 1 CLOSED (Stages 1-8 all done). No new
#   functionality — this version is the consolidation/verification pass:
#     - TABS entry's stage label updated (was stale since Stage 3 —
#       still read "Stage 2 parsers next").
#     - Full re-verification: py_compile, AST duplicate-function scan,
#       `node --check` on the extracted _JS, and a fresh end-to-end HTTP
#       test covering page load -> tab wiring present -> placeholder
#       gone -> status fetch -> peer add with helper_url -> edit_snippet
#       -> save_snippet -> re-fetch confirms wired+helper_url intact.
#     - Scoped diff reviewed from v0.0.10 (pre-Nodes-tab baseline)
#       through this version: purely additive, no unrelated lines
#       touched anywhere in the 8-stage build.
#
#   Nodes tab (Scenario B) is now feature-complete per the original
#   design plan: parses iax.conf/rpt.conf/extensions.conf/allmon3.ini,
#   classifies local vs. peer nodes, evaluates guardrails (bindport
#   range, missing/malformed lines, not-wired peers, port collisions),
#   exposes it all through a live UI with working inline editors backed
#   by a real backup+diff+targeted-write engine, and peer bookkeeping
#   including the pulled-forward 44helper link button.
#
#   Phase 2 (parked, not started): cross-instance read-only status
#   fetch (a peer's own /api/nodes/status, given its helper URL) and,
#   as part of that same pass, reachability probing for the link
#   button so it can distinguish "configured" from "actually running."
# =============================================================================

# =============================================================================
# v0.0.19 — Nodes tab, Phase 2, Stage 9 (peer reachability probe). The
#   full "peer reports its own live status" enrichment is still Stage 10
#   — this stage only adds the reachable/unreachable signal itself.
#
#   Added:
#     - probe_peer_helper(url, timeout=1.5): GETs {url}/api/version —
#       small, fast, already exists on every 44helper instance, and
#       doesn't touch the peer's ASL config. Same exception-handling
#       convention as check_myip() (catches URLError/OSError/
#       TimeoutError/JSONDecodeError/ValueError, never raises). Returns
#       reachable/error/remote_version.
#     - probe_all_peer_helpers(): sequential probe across all peer
#       cards with a configured helper_url, mutating in place. Documented
#       tradeoff: sequential not parallel, since this is LAN-scale peer
#       counts and only runs on an explicit refresh, never a timer.
#     - build_nodes_tab_data() gained a probe_peers parameter, default
#       False. This matters: the function is also called internally by
#       build_node_snippet() on every editor-open and every save — those
#       don't need a live probe of every peer, and paying network
#       latency on an unrelated action would be a regression. Only
#       GET /api/nodes/status passes probe_peers=True.
#     - Frontend: the link button is now genuinely three-state again
#       (matching the original design, not just "URL present"): no
#       helper_url -> hidden; helper_url + probe unreachable -> shown,
#       dimmed (.nd-link-btn-dim), tooltip with the error; helper_url +
#       reachable -> full brightness, tooltip shows the peer's reported
#       version if available.
# =============================================================================

# =============================================================================
# v0.0.20 — Nodes tab, Phase 2, Stage 10 (enriched peer cards). This is
#   the last planned piece of the original design — Phase 2 is complete
#   after this stage.
#
#   Added:
#     - fetch_peer_node_status(url): GETs a peer's own
#       /api/nodes/status — its self-reported bindport, its own local-
#       node findings, its own overall guardrail_level. Only called
#       after Stage 9's probe already confirmed reachability. Same
#       silent-degrade-to-None convention as every other probe here.
#       Documented request-depth note: this triggers the peer's own
#       Stage-9 probing of ITS peers (one more one-hop /api/version
#       fetch each) but cannot recurse further, since
#       probe_peer_helper() never calls /api/nodes/status — bounded
#       even in a fully-meshed multi-box LAN.
#     - probe_all_peer_helpers() now also populates
#       "helper_remote_status" per peer card (Stage 9's "helper_probe"
#       is unchanged/still present alongside it).
#     - build_nodes_guardrails(): the box-vs-peer port-collision check
#       is now authoritative when a peer's live bindport was fetched —
#       compares against what the peer actually reports, not the
#       stored/typed port field, and says so explicitly ("CONFIRMED:
#       peer reports its own bindport as..."). Falls back to the old
#       stored-port best-guess comparison when no live data is
#       available (unreachable peer, or Re-check not yet run). Also
#       adds a low-severity "info" finding surfacing the peer's own
#       self-reported guardrail_level, so a healthy-looking local view
#       doesn't hide a peer that's flagging problems on its own end.
#     - Frontend: peer cards show a one-line "Peer reports: bindport X,
#       status Y" note whenever helper_remote_status is present.
#
#   Phase 2 is now complete: Stage 9 (reachability) + Stage 10
#   (enrichment) both done. Nothing further planned for the Nodes tab
#   beyond bug fixes/polish unless new requirements come up.
# =============================================================================

# =============================================================================
# v0.0.21 — Nodes tab, detailed remediation instructions. User feedback:
#   warn/danger findings were too terse — named the problem but not what
#   to actually do about it.
#
#   build_nodes_guardrails() rewritten: every warn/danger finding now
#   carries a "fix" field — numbered, concrete steps, not a restatement
#   of the "msg". ok/info findings don't get one (nothing to fix).
#   Every fix that names an ASL conf line points at the specific Edit
#   button that opens it, pre-filled correctly, where this tab actually
#   has an editor for that file (rpt.conf/iax.conf); fixes touching
#   extensions.conf say plainly that this tab doesn't edit it yet,
#   rather than implying a button exists where none does. Every fix
#   that changes bindport or a [nodes] line ends with the real-world
#   consequence: Asterisk needs restarting, and bindport changes also
#   need a matching router port-forward update.
#
#   Frontend: ndRenderFindings() renders the fix (when present) as a
#   "What to do:" block below the message, separated by a thin divider,
#   using white-space:pre-line so the numbered-step text (written with
#   embedded \n) renders with line breaks with no HTML-escaping
#   bookkeeping needed.
# =============================================================================

# =============================================================================
# v0.0.22 — Tab bar overflow fix. Eight tabs no longer fit on one row on
#   narrower viewports; .tabs previously relied on flex-shrink:0 +
#   horizontal scroll, which read as tabs "running off the page" rather
#   than an obvious scrollable strip.
#
#   .tabs gained flex-wrap: wrap. A dedicated flex-basis:100% break
#   element (.tab-break) is inserted right after the Nodes tab in
#   _render_tab_bar(), forcing a predictable two-row split (Overview
#   through Nodes on row one, Services through Actions Log on row two)
#   instead of leaving the wrap point to whatever the browser's default
#   flex-wrap behavior picks at a given width.
# =============================================================================

# =============================================================================
# v0.0.23 — Internal refactor only. No UI, endpoint, or behavior changes —
#   every stage below was verified byte-identical (CSS/JS/render_page
#   output) or exercised against a stubbed equivalence harness (route
#   dispatch) comparing this file's output to v0.0.22's, request for
#   request, before being accepted.
#
#   Stage A — _CSS split into 6 named, concern-scoped sub-constants
#     (_CSS_BASE, _CSS_LAYOUT, _CSS_COMPONENTS, _CSS_NODES, _CSS_FIREWALL,
#     _CSS_LOG), concatenated into _CSS exactly as before. Verified: same
#     90 selectors as v0.0.22, no duplicates anywhere in the sheet, so
#     the minor internal reordering (step-body/step-actions now grouped
#     with the rest of the step-card rules instead of trailing the nodes
#     block) has zero cascade effect.
#
#   Stage B — _JS split into 9 named per-tab sub-constants (_JS_TABS,
#     _JS_OVERVIEW, _JS_PI_INSTALL, _JS_NODES, _JS_INIT,
#     _JS_ROUTER_INSTALL, _JS_SERVICES_PORTS, _JS_FIREWALL,
#     _JS_ACTIONS_LOG), concatenated into _JS. Verified: character-for-
#     character identical to v0.0.22's single _JS string. _JS_INIT
#     (the DOMContentLoaded bootstrap) stays where it originally lived,
#     between the Nodes and Router Install sections — not moved to
#     file-end — since JS function declarations are hoisted, so this is
#     a pure reorganization, not a behavior change.
#
#   Stage C — render_page()'s 8-deep nested-ternary panel dispatch
#     (`_render_overview_panel() if t_id == "overview" else ...`)
#     replaced with a _PANEL_RENDERERS: dict[str, Callable[[], str]]
#     lookup table, same placeholder fallback as before for any tab_id
#     not yet in the table. Verified: full render_page() output
#     byte-identical to v0.0.22 outside the (already-verified-equivalent)
#     CSS reordering from Stage A.
#
#   Stage D — the three step/action elif chains in do_POST replaced
#     with dispatch tables:
#       - /api/pi_install/action -> _PI_INSTALL_SIMPLE_ACTIONS +
#         _PI_INSTALL_SERVICE_PORTS_ACTIONS (the one step with a
#         secondary action switch), via _dispatch_pi_install_action().
#       - /api/router_install/action -> _ROUTER_INSTALL_ACTIONS, via
#         _dispatch_router_install_action(). "verify" keeps its own
#         function (not a bare lambda) since it carries side effects —
#         writing tunnels.tunnel.router.verified on success — beyond a
#         single delegated call.
#       - /api/firewall/action -> _FIREWALL_ACTIONS, via
#         _dispatch_firewall_action().
#     do_GET's 14 sequential path checks replaced with a _GET_ROUTES
#     dict of one-line handler functions; the one genuinely
#     parameterized route (/api/actions_log/notes/<filename>) stays a
#     prefix check ahead of the table, since a dict can't express
#     "starts with" as a key. The 6x duplicated Content-Length/JSON-
#     parse/bad-JSON block in do_POST factored into one
#     Handler._read_json_body() method.
#     Verified: 42 POST cases (every step/action combination on all
#     three action routes, unknown-step/action fallbacks, the edge case
#     of a mismatched step/action pair, and malformed JSON on all 7 POST
#     routes) and 21 GET cases (every route, query-param handling, the
#     notes/<filename> prefix route found/not-found, and the 404
#     fallback) all matched v0.0.22 exactly via a stubbed test harness
#     that swapped every action_*/build_*/check_*/save_* function for a
#     call-recording stub and diffed the resulting (status, content_type,
#     body) tuples.
# =============================================================================

# =============================================================================
# v0.0.24 — New tab: ASL3 (Stage 1 of the 3-tab install-script rollout —
#   ASL3 first; DVswitch and SVXlink follow later using this same engine
#   once ASL3 is validated on real hardware).
#
#   Layout: distro dropdown (Bookworm / Trixie / Custom) at the top, a
#   Purge button next to it, then a step list. Each step is ONE shell
#   command line shown in an editable text field with its own Run
#   button — not a fixed hardcoded action like Pi Install's steps. The
#   field is pre-filled with the known-good command but can be edited
#   before sending; whatever text is in the field at Run time is what
#   gets executed, not necessarily the original default. Custom mode
#   swaps the step list for one persistent free-text field + Run + a
#   scrolling transcript, with no whitelist — this is the intentional
#   trapdoor for anything not covered by the two distro scripts.
#
#   Execution model: Option A (wait-then-show) per design discussion —
#   the Run button disables and shows a spinner, the request blocks
#   until the command finishes or times out, then full output appears.
#   No live streaming (Option B) in this stage.
#
#   All per-step "done"/"attempted" state and the Custom-mode transcript
#   are session-only (JS memory) — nothing persisted to config or disk,
#   confirmed as the desired behavior. Distro step lists and purge step
#   lists are separate per distro (Bookworm vs Trixie), since package
#   names/behavior could differ between them.
#
#   New engine pieces:
#     - _ASL3_INSTALL_BOOKWORM / _ASL3_INSTALL_TRIXIE — real step lists,
#       sourced from two user-supplied reference docs (a "complete setup
#       script" covering ASL3 + Allmon3 + Cockpit + node utilities, and a
#       shorter official-repo-method doc used to cross-check the repo
#       package names). Each list carries a source/date header comment.
#       Two known deviations from the source docs, both required by this
#       engine's per-step-independent execution model (each step is its
#       own subprocess call, so a bare `cd /tmp` on one line would not
#       carry over to the next step):
#         (1) `cd /tmp && wget ...` folded into one step instead of two
#             separate `cd` / `wget` lines;
#         (2) the following `dpkg -i` step references the deb by its
#             absolute /tmp path rather than a bare filename, since the
#             working directory does not persist between steps.
#       Two steps (`allmon3-passwd admin` and `asl-menu`) are known
#       interactive prompts — flagged with a note field since this
#       engine has no stdin channel and Option A's blocking
#       request/timeout model cannot satisfy an interactive prompt.
#       These will very likely hang until timeout when run as-is; real
#       fix (non-interactive flags, if they exist, or pulling these two
#       out of the automated list) is deferred to the live test pass.
#     - _ASL3_PURGE_BOOKWORM / _ASL3_PURGE_TRIXIE — placeholder only
#       (single dummy step, clearly labeled). No real purge script has
#       been supplied yet; these exist so the Purge button and its
#       double-confirm + step-card rendering path can be smoke-tested
#       now and swapped for real content later without re-touching the
#       engine.
#     - _run_shell_line() — new sibling to _run_argv(), using
#       subprocess.run(shell=True) instead of an argv list, since real
#       install lines need &&/pipe chaining that argv-list execution
#       can't express. Same _require_root() gate, same log() call.
#     - _ASL3_SCRIPTS — nested {mode: {distro: [steps]}} catalog,
#       served whole via GET /api/asl3/script; the browser picks the
#       right sub-list client-side based on the dropdown, rather than
#       the server doing per-request filtering.
#     - _dispatch_asl3_action() — POST /api/asl3/action. For
#       mode in (install, purge): step_id must match a real entry in
#       that mode+distro's list (can't invent new steps via the API),
#       but the *command_text* actually run is whatever the browser
#       sent (i.e. the edited field), not the catalog's default. For
#       mode == custom: no step_id, no whitelist — runs command_text
#       as-is. Both paths run through the same Actions Log call as
#       every other mutating action in this file.
#     - _render_asl3_panel() / _JS_ASL3 — one shared engine (dropdown,
#       step-card-with-editable-input renderer, Custom-mode transcript,
#       Purge toggle with double confirm) rather than one-off per-tab
#       code, so DVswitch/SVXlink can reuse it directly later.
# =============================================================================

from __future__ import annotations

import argparse
import configparser
import difflib
import ipaddress
import json
import os
import random
import re
import shlex
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable

APP_TITLE = "ASL-DVS-M17 44 Helper"
APP_VERSION = "0.0.24"
APP_STAGE = "ASL3 tab Stage 1 (engine + real Bookworm/Trixie install steps; purge lists are placeholders)"


CONFIG_DIR = Path("/etc/44helper")
CONFIG_FILE = CONFIG_DIR / "44helper.conf"

_DEFAULT_CONFIG: dict[str, dict[str, str]] = {
    "server": {
        "port": "9997",
        "host": "0.0.0.0",
    },
    "identity": {
        "callsign": "",
        "node": "",
    },
    "tunnels": {
    },
    "router": {
        "access_method": "none",
        "host": "",
        "user": "",
        "key_path": "",
        "poll_interval_sec": "60",
    },
    "ui": {
        "enabled_tabs": "overview,router_install,pi_install,nodes,asl3,services,ports,firewall,actions_log",
    },
    "nodes": {
        "iax_conf_path": "/etc/asterisk/iax.conf",
        "rpt_conf_path": "/etc/asterisk/rpt.conf",
        "extensions_conf_path": "/etc/asterisk/extensions.conf",
        "allmon3_ini_path": "/etc/allmon3/allmon3.ini",
        "bindport_range_min": "4560",
        "bindport_range_max": "4580",
        "peers": "",
        "peer_links": "",
    },
}


def load_config() -> configparser.ConfigParser:
    cfg = configparser.ConfigParser()
    cfg.read_dict(_DEFAULT_CONFIG)

    if CONFIG_FILE.exists():
        cfg.read(CONFIG_FILE)
    else:
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            with open(CONFIG_FILE, "w") as f:
                cfg.write(f)
            log(f"Created default config at {CONFIG_FILE}")
        except OSError as e:
            log(f"WARNING: could not write {CONFIG_FILE}: {e}")

    return cfg


def save_config(cfg: configparser.ConfigParser) -> None:
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_FILE, "w") as f:
            cfg.write(f)
    except OSError as e:
        log(f"WARNING: could not save {CONFIG_FILE}: {e}")



INSTALL_BIN_PATH = "/opt/44helper/asl_dvs_m17_44helper.py"
SYSTEMD_SERVICE_PATH = "/etc/systemd/system/44helper.service"

SYSTEMD_SERVICE_CONTENT = f"""[Unit]
Description=ASL-DVS-M17 44 Helper (44Net Connect / firewall / router dashboard)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 {INSTALL_BIN_PATH}
Restart=on-failure
RestartSec=3
User=root
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
"""


def install_service() -> None:
    if os.geteuid() != 0:
        print("Error: Installation requires root privileges. Run with 'sudo'.")
        sys.exit(1)

    current_script = os.path.abspath(__file__)

    print(f"Installing {APP_TITLE} v{APP_VERSION} ({APP_STAGE})...")

    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(CONFIG_DIR, 0o700)
    print(f"  [+] Ensured {CONFIG_DIR} exists with mode 700")

    install_dir = os.path.dirname(INSTALL_BIN_PATH)
    os.makedirs(install_dir, exist_ok=True)
    if current_script != INSTALL_BIN_PATH:
        shutil.copy2(current_script, INSTALL_BIN_PATH)
        print(f"  [+] Copied script to {INSTALL_BIN_PATH}")
    os.chmod(INSTALL_BIN_PATH, 0o755)

    with open(SYSTEMD_SERVICE_PATH, "w") as f:
        f.write(SYSTEMD_SERVICE_CONTENT)
    print(f"  [+] Created service file at {SYSTEMD_SERVICE_PATH}")

    subprocess.run(["systemctl", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "enable", "--now", "44helper.service"], check=True)
    print("  [+] Enabled and started 44helper.service")
    print("\nInstallation complete! View logs anytime using:")
    print("  journalctl -u 44helper -f")


def uninstall_service() -> None:
    if os.geteuid() != 0:
        print("Error: Uninstallation requires root privileges. Run with 'sudo'.")
        sys.exit(1)

    print(f"Uninstalling {APP_TITLE}...")

    subprocess.run(["systemctl", "disable", "--now", "44helper.service"], stderr=subprocess.DEVNULL)
    print("  [-] Stopped and disabled 44helper.service")

    if os.path.exists(SYSTEMD_SERVICE_PATH):
        os.remove(SYSTEMD_SERVICE_PATH)
        print(f"  [-] Removed {SYSTEMD_SERVICE_PATH}")

    subprocess.run(["systemctl", "daemon-reload"], stderr=subprocess.DEVNULL)

    if os.path.exists(INSTALL_BIN_PATH):
        os.remove(INSTALL_BIN_PATH)
        print(f"  [-] Removed {INSTALL_BIN_PATH}")

    print(f"\nUninstallation complete. {CONFIG_FILE} was left untouched.")



_LOG_MAXLEN = 500
_log_buf: deque[str] = deque(maxlen=_LOG_MAXLEN)
_log_lock = threading.Lock()


def log(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    with _log_lock:
        _log_buf.append(line)
    print(line, flush=True)


def get_log_lines() -> list[str]:
    with _log_lock:
        return list(_log_buf)



WG0_CONF_PATH = "/etc/wireguard/wg0.conf"
FIREWALLD_ZONE = "44NetConnect"

_WATCHED_DASHBOARD_PORTS: dict[int, str] = {
    9999: "sysmon dashboard",
    8989: "asl_dvs_dashboard",
    9090: "Cockpit",
}
_WATCHED_AMI_PORT = 5038


def _wg0_interface_present() -> bool:
    return os.path.exists("/sys/class/net/wg0")


def _parse_wg_conf_text(text: str, mask_private_key: bool = True) -> dict:
    result: dict = {"interface": {}, "peers": []}
    section: str | None = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        lower = line.lower()
        if lower == "[interface]":
            section = "interface"
            continue
        if lower == "[peer]":
            section = "peer"
            result["peers"].append({})
            continue
        if "=" in line and section:
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip()
            if key.lower() == "privatekey" and mask_private_key:
                val = "•••• (masked)"
            if section == "interface":
                result["interface"][key] = val
            else:
                result["peers"][-1][key] = val
    return result


def _parse_wg0_conf(path: str = WG0_CONF_PATH) -> dict | None:
    if not os.path.exists(path):
        return None

    try:
        with open(path, "r") as f:
            text = f.read()
    except OSError:
        return {"interface": {}, "peers": [], "_unreadable": True}

    return _parse_wg_conf_text(text)


def _wg0_conf_perms_ok(path: str = WG0_CONF_PATH) -> bool | None:
    try:
        mode = os.stat(path).st_mode & 0o777
    except OSError:
        return None
    return mode == 0o600


def _wg_show_wg0() -> dict | None:
    try:
        r = subprocess.run(
            ["wg", "show", "wg0"],
            capture_output=True, text=True, timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0:
        return None

    info: dict = {}
    for raw_line in r.stdout.splitlines():
        line = raw_line.strip()
        if line.lower().startswith("latest handshake:"):
            info["latest_handshake"] = line.split(":", 1)[1].strip()
        elif line.lower().startswith("transfer:"):
            info["transfer"] = line.split(":", 1)[1].strip()
        elif line.lower().startswith("endpoint:"):
            info["endpoint"] = line.split(":", 1)[1].strip()
    return info or None


def _firewalld_zone_info(zone: str = FIREWALLD_ZONE) -> dict | None:
    try:
        r = subprocess.run(
            ["firewall-cmd", f"--zone={zone}", "--list-all"],
            capture_output=True, text=True, timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0:
        return None

    info: dict = {"services": [], "ports": [], "interfaces": [], "raw": r.stdout}
    for raw_line in r.stdout.splitlines():
        line = raw_line.strip()
        if line.startswith("services:"):
            info["services"] = line.split(":", 1)[1].split()
        elif line.startswith("ports:"):
            info["ports"] = line.split(":", 1)[1].split()
        elif line.startswith("interfaces:"):
            info["interfaces"] = line.split(":", 1)[1].split()
    return info


def _configured_tunnel_names(cfg: configparser.ConfigParser) -> list[str]:
    if "tunnels" not in cfg:
        return []
    names: set[str] = set()
    for key in cfg["tunnels"]:
        parts = key.split(".")
        if len(parts) >= 2 and parts[0] == "tunnel":
            names.add(parts[1])
    return sorted(names)


def build_overview_data(cfg: configparser.ConfigParser) -> dict:
    my_port = cfg.getint("server", "port", fallback=9997)

    wg0_present = _wg0_interface_present()
    wg0_conf = _parse_wg0_conf()
    wg0_perms_ok = _wg0_conf_perms_ok()
    wg_status = _wg_show_wg0()
    fw_zone = _firewalld_zone_info()
    tunnel_names = _configured_tunnel_names(cfg)

    self_check = _run_self_check(my_port, fw_zone, wg0_perms_ok)

    return {
        "wg0_present": wg0_present,
        "wg0_conf": wg0_conf,
        "wg0_conf_perms_ok": wg0_perms_ok,
        "wg_status": wg_status,
        "firewalld_zone": fw_zone,
        "tunnel_names": tunnel_names,
        "self_check": self_check,
        "checked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def _run_self_check(my_port: int, fw_zone: dict | None, wg0_perms_ok: bool | None) -> list[dict]:
    findings: list[dict] = []

    if fw_zone is None:
        findings.append({
            "level": "info",
            "msg": (
                f"{FIREWALLD_ZONE} firewall zone not found yet — nothing to "
                "audit. Expected before Pi Install (Stage 3) has run."
            ),
        })
    else:
        exposed_ports = set(fw_zone.get("ports", []))
        exposed_services = set(fw_zone.get("services", []))

        def _port_exposed(port: int) -> bool:
            return any(str(port) == p.split("/")[0] for p in exposed_ports)

        if _port_exposed(my_port):
            findings.append({
                "level": "danger",
                "msg": (
                    f"44helper's own dashboard port ({my_port}) appears "
                    f"exposed in the {FIREWALLD_ZONE} zone. This dashboard "
                    "should never be reachable on the public 44Net address."
                ),
            })

        for port, label in _WATCHED_DASHBOARD_PORTS.items():
            if _port_exposed(port):
                findings.append({
                    "level": "danger",
                    "msg": f"{label} port ({port}) appears exposed in the {FIREWALLD_ZONE} zone.",
                })

        if _port_exposed(_WATCHED_AMI_PORT) or "astmgr" in exposed_services:
            findings.append({
                "level": "danger",
                "msg": (
                    f"Asterisk AMI ({_WATCHED_AMI_PORT}) appears exposed in the "
                    f"{FIREWALLD_ZONE} zone — the 44Net Connect manual flags "
                    "this as especially risky (§1)."
                ),
            })

        if not findings:
            findings.append({"level": "ok", "msg": f"No watched ports found exposed in the {FIREWALLD_ZONE} zone."})

    if wg0_perms_ok is None:
        pass
    elif wg0_perms_ok is False:
        findings.append({
            "level": "warn",
            "msg": f"{WG0_CONF_PATH} is not mode 600 — private key file permissions have drifted.",
        })
    else:
        findings.append({"level": "ok", "msg": f"{WG0_CONF_PATH} permissions OK (600)."})

    return findings


def _self_check_worst_level(findings: list[dict]) -> str:
    order = {"danger": 3, "warn": 2, "info": 1, "ok": 0}
    if not findings:
        return "ok"
    return max(findings, key=lambda f: order.get(f["level"], 0))["level"]



PI_INSTALL_STEPS = [
    "firewalld_prereq",
    "resolved_prereq",
    "create_zone",
    "service_ports",
    "paste_config",
    "attach_interface",
    "enable_tunnel",
]

PI_INSTALL_SERVICES = {
    "iax2": {"label": "AllStarLink IAX2", "default_on": True},
    "echolink": {"label": "EchoLink", "default_on": False},
    "rtcm": {"label": "VOTER/RTCM", "default_on": False},
}


def _run_argv(argv: list[str], timeout: int = 20) -> dict:
    log(f"RUN: {' '.join(argv)}")
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        ok = r.returncode == 0
        out = (r.stdout or "") + (r.stderr or "")
        log(f"{'OK' if ok else 'FAIL'} (exit {r.returncode}): {' '.join(argv)}")
        return {"success": ok, "returncode": r.returncode, "output": out.strip()}
    except FileNotFoundError:
        log(f"FAIL (not found): {' '.join(argv)}")
        return {"success": False, "returncode": None, "output": f"{argv[0]}: command not found"}
    except subprocess.TimeoutExpired:
        log(f"FAIL (timeout): {' '.join(argv)}")
        return {"success": False, "returncode": None, "output": "command timed out"}


def _require_root() -> dict | None:
    if os.geteuid() != 0:
        return {"success": False, "returncode": None,
                "output": "This action requires root. Run 44helper via its systemd service (installed with --install)."}
    return None


def _run_shell_line(cmd: str, timeout: int = 180) -> dict:
    """Sibling to _run_argv(), for the ASL3/DVswitch/SVXlink install-script
    tabs. Uses subprocess.run(shell=True) rather than an argv list, since
    real install lines routinely chain with && (apt update && apt install
    ...) which an argv list can't express. Same log()/timeout/not-found
    shape as _run_argv() so Actions Log entries look consistent."""
    log(f"RUN(shell): {cmd}")
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        ok = r.returncode == 0
        out = (r.stdout or "") + (r.stderr or "")
        log(f"{'OK' if ok else 'FAIL'} (exit {r.returncode}): {cmd}")
        return {"success": ok, "returncode": r.returncode, "output": out.strip()}
    except subprocess.TimeoutExpired:
        log(f"FAIL (timeout): {cmd}")
        return {"success": False, "returncode": None,
                "output": f"command timed out after {timeout}s (note: interactive prompts will hang here — "
                          f"this engine has no stdin channel)"}
    except Exception as exc:  # noqa: BLE001 - want any shell failure surfaced, not a stack trace
        log(f"FAIL (exception): {cmd} :: {exc}")
        return {"success": False, "returncode": None, "output": f"error running command: {exc}"}


# =============================================================================
# ASL3 tab — install/purge step catalogs (Stage 1).
#
# Source: user-supplied reference docs —
#   (1) "Debian 12/13 Complete Setup Script" — ASL3 core + Allmon3 +
#       Cockpit + node utilities + post-install service enablement.
#       Pulled/verified 2026-08-21.
#   (2) "AllStarLink 3 install on Bookworm/Trixie" — shorter official-
#       repo-method doc, used to cross-check package/repo names against
#       (1). Pulled/verified 2026-08-21.
#   Both docs point at the same repo.allstarlink.org .deb packages for
#   Bookworm (deb12) and Trixie (deb13), so this list follows doc (1)
#   (the more complete of the two) as the canonical step sequence.
#   NOTE — if SVXlink's step lists (later stage) turn out to live at a
#   different source entirely (e.g. sm0svx's own GitHub rather than a
#   distro packaging page), that gets its own separate attribution when
#   drafted — not assumed to share this one.
#
# Two deviations from the source docs, both required by this engine's
# per-step-independent execution model (each step is its own subprocess
# call — a bare `cd /tmp` on one line does not carry over to the next
# step the way it would in a single shell session):
#   (1) `cd /tmp && wget ...` folded into one step instead of two lines.
#   (2) the following `dpkg -i` step uses the deb's absolute /tmp path
#       rather than a bare filename.
#
# Two steps are known interactive prompts (`allmon3-passwd admin`,
# `asl-menu`) — this engine has no stdin channel, so under Option A
# (wait-then-show, blocking request/timeout) these will very likely just
# hang until timeout as written. Flagged via each step's "note" field;
# real handling (non-interactive flags if they exist, or pulling these
# two out of the automated list) is deferred to the live test pass.
# =============================================================================

def _asl3_install_steps(distro_deb_suffix: str) -> list[dict]:
    return [
        {"id": "prereqs", "num": 1, "title": "Install prerequisites",
         "cmd": "sudo apt update && sudo apt install -y wget curl git dpkg sudo firewalld alsa-utils python3-serial"},
        {"id": "fetch_repo", "num": 2, "title": "Download ASL3 repo package",
         "cmd": f"cd /tmp && sudo wget https://repo.allstarlink.org/public/asl-apt-repos.{distro_deb_suffix}_all.deb",
         "note": "Adapted from the source doc's separate `cd /tmp` line — each step here runs in its own "
                 "subprocess, so cd alone would not carry over to the next step."},
        {"id": "install_repo", "num": 3, "title": "Install ASL3 repo package",
         "cmd": f"sudo dpkg -i /tmp/asl-apt-repos.{distro_deb_suffix}_all.deb",
         "note": "Uses the absolute /tmp path rather than a bare filename, since working directory does not "
                 "persist between steps in this engine."},
        {"id": "apt_update", "num": 4, "title": "Refresh package index",
         "cmd": "sudo apt update"},
        {"id": "install_core", "num": 5, "title": "Install ASL3, Allmon3, Cockpit, node utilities",
         "cmd": "sudo apt install -y asl3 allmon3 cockpit cockpit-networkmanager cockpit-packagekit "
                "cockpit-storaged cockpit-system cockpit-ws asl3-update-nodelist asl3-tts"},
        {"id": "install_appliance", "num": 6, "title": "(Optional) Full ASL3 Appliance branding/firewall defaults",
         "cmd": "sudo apt install -y asl3-appliance",
         "note": "Optional per source doc — applies appliance branding, web rules, and pre-configured "
                 "firewall defaults. Skip if not wanted."},
        {"id": "allmon3_delete_default", "num": 7, "title": "Remove default Allmon3 account",
         "cmd": "sudo allmon3-passwd --delete allmon3"},
        {"id": "allmon3_set_admin", "num": 8, "title": "Set Allmon3 admin password",
         "cmd": "sudo allmon3-passwd admin",
         "note": "INTERACTIVE PROMPT — this engine has no stdin channel. This will very likely hang until "
                 "timeout as written. Verify during the live test pass whether a non-interactive flag exists."},
        {"id": "enable_cockpit", "num": 9, "title": "Enable Cockpit socket",
         "cmd": "sudo systemctl enable --now cockpit.socket"},
        {"id": "enable_allmon3", "num": 10, "title": "Enable Allmon3 service",
         "cmd": "sudo systemctl enable --now allmon3"},
        {"id": "enable_astdb_timer", "num": 11, "title": "Enable node database updater timer",
         "cmd": "sudo systemctl enable --now asl3-update-astdb.timer"},
        {"id": "run_asl_menu", "num": 12, "title": "Configure node settings (asl-menu)",
         "cmd": "sudo asl-menu",
         "note": "INTERACTIVE — full-screen console menu, not a one-shot command. This will very likely hang "
                 "until timeout under this engine. Likely needs to stay a manual step run over SSH/console "
                 "rather than through this button, confirm during the live test pass."},
    ]


_ASL3_INSTALL_BOOKWORM: list[dict] = _asl3_install_steps("deb12")
_ASL3_INSTALL_TRIXIE: list[dict] = _asl3_install_steps("deb13")

# Placeholder only — no real purge script supplied yet. Exists so the
# Purge button, its double-confirm, and the step-card rendering path can
# be smoke-tested now and swapped for real content later without
# re-touching the engine itself.
_ASL3_PURGE_BOOKWORM: list[dict] = [
    {"id": "purge_placeholder", "num": 1, "title": "(Placeholder — real purge steps not yet defined)",
     "cmd": "echo 'PURGE SCRIPT NOT YET DEFINED FOR BOOKWORM — this is a placeholder step only'"},
]
_ASL3_PURGE_TRIXIE: list[dict] = [
    {"id": "purge_placeholder", "num": 1, "title": "(Placeholder — real purge steps not yet defined)",
     "cmd": "echo 'PURGE SCRIPT NOT YET DEFINED FOR TRIXIE — this is a placeholder step only'"},
]

_ASL3_SCRIPTS: dict[str, dict[str, list[dict]]] = {
    "install": {"bookworm": _ASL3_INSTALL_BOOKWORM, "trixie": _ASL3_INSTALL_TRIXIE},
    "purge": {"bookworm": _ASL3_PURGE_BOOKWORM, "trixie": _ASL3_PURGE_TRIXIE},
}


def _asl3_lookup_step(mode: str, distro: str, step_id: str) -> dict | None:
    for step in _ASL3_SCRIPTS.get(mode, {}).get(distro, []):
        if step["id"] == step_id:
            return step
    return None


def _dispatch_asl3_action(payload: dict) -> dict:
    mode = payload.get("mode", "")
    command_text = str(payload.get("command_text", "")).strip()
    if not command_text:
        return {"success": False, "output": "No command text provided."}

    if mode in ("install", "purge"):
        distro = payload.get("distro", "")
        step_id = payload.get("step_id", "")
        if distro not in ("bookworm", "trixie"):
            return {"success": False, "output": f"Unknown distro: {distro}"}
        if _asl3_lookup_step(mode, distro, step_id) is None:
            return {"success": False, "output": f"Unknown step_id for {mode}/{distro}: {step_id}"}
    elif mode != "custom":
        return {"success": False, "output": f"Unknown mode: {mode}"}

    err = _require_root()
    if err:
        return err
    return _run_shell_line(command_text)



def status_firewalld_prereq() -> dict:
    installed = shutil.which("firewall-cmd") is not None
    active = False
    if installed:
        r = subprocess.run(["systemctl", "is-active", "firewalld"],
                            capture_output=True, text=True, timeout=5)
        active = r.stdout.strip() == "active"
    done = installed and active
    return {"done": done, "installed": installed, "active": active}


def _argv_install_firewalld() -> list[list[str]]:
    return [
        ["apt-get", "install", "-y", "firewalld"],
        ["systemctl", "enable", "--now", "firewalld"],
    ]


def action_install_firewalld() -> dict:
    err = _require_root()
    if err:
        return err
    results = [_run_argv(a) for a in _argv_install_firewalld()]
    ok = all(r["success"] for r in results)
    status = status_firewalld_prereq()
    return {"success": ok, "verified": status["done"], "output": "\n".join(r["output"] for r in results)}



def status_resolved_prereq() -> dict:
    r = subprocess.run(["systemctl", "is-active", "systemd-resolved"],
                        capture_output=True, text=True, timeout=5)
    active = r.stdout.strip() == "active"
    return {"done": active, "active": active}


def _argv_install_resolved() -> list[list[str]]:
    return [
        ["apt-get", "install", "-y", "wireguard", "systemd-resolved"],
        ["systemctl", "enable", "--now", "systemd-resolved"],
    ]


def action_install_resolved() -> dict:
    err = _require_root()
    if err:
        return err
    results = [_run_argv(a) for a in _argv_install_resolved()]
    ok = all(r["success"] for r in results)
    status = status_resolved_prereq()
    note = ("A reboot is recommended before bringing the tunnel up "
            "(step 6) — per §1a.1, skipping it can cause a resolve1 "
            "timeout on `wg-quick up` even with the service active.")
    return {"success": ok, "verified": status["done"], "output": "\n".join(r["output"] for r in results) + "\n" + note}



def status_create_zone() -> dict:
    try:
        r = subprocess.run(["firewall-cmd", "--get-zones"], capture_output=True, text=True, timeout=5)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return {"done": False, "zones": []}
    zones = r.stdout.split() if r.returncode == 0 else []
    return {"done": FIREWALLD_ZONE in zones, "zones": zones}


def _argv_create_zone() -> list[list[str]]:
    return [
        ["firewall-cmd", "--permanent", f"--new-zone={FIREWALLD_ZONE}"],
        ["firewall-cmd", "--reload"],
    ]


def action_create_zone() -> dict:
    err = _require_root()
    if err:
        return err
    results = []
    for argv in _argv_create_zone():
        r = _run_argv(argv)
        if not r["success"] and "already exists" in r["output"].lower():
            r["success"] = True
        results.append(r)
    ok = all(r["success"] for r in results)
    status = status_create_zone()
    return {"success": ok, "verified": status["done"], "output": "\n".join(r["output"] for r in results)}



def status_service_ports() -> dict:
    zone = _firewalld_zone_info()
    if zone is None:
        return {"done": False, "zone_exists": False, "services": [], "ports": []}
    return {"done": True, "zone_exists": True, "services": zone["services"], "ports": zone["ports"]}


def _argv_add_service(service: str) -> list[list[str]]:
    return [
        ["firewall-cmd", "--permanent", f"--zone={FIREWALLD_ZONE}", f"--add-service={service}"],
        ["firewall-cmd", "--reload"],
    ]


def _argv_add_port(port_proto: str) -> list[list[str]]:
    return [
        ["firewall-cmd", "--permanent", f"--zone={FIREWALLD_ZONE}", f"--add-port={port_proto}"],
        ["firewall-cmd", "--reload"],
    ]


def _valid_port_proto(s: str) -> bool:
    parts = s.split("/")
    if len(parts) != 2:
        return False
    port_s, proto = parts
    if proto not in ("udp", "tcp"):
        return False
    if not port_s.isdigit():
        return False
    port = int(port_s)
    return 1 <= port <= 65535


def action_add_service(service: str) -> dict:
    err = _require_root()
    if err:
        return err
    if service not in PI_INSTALL_SERVICES:
        return {"success": False, "verified": False, "output": f"Unknown service '{service}'"}
    results = [_run_argv(a) for a in _argv_add_service(service)]
    ok = all(r["success"] for r in results)
    status = status_service_ports()
    verified = service in status.get("services", [])
    return {"success": ok, "verified": verified, "output": "\n".join(r["output"] for r in results)}


def action_add_port(port_proto: str) -> dict:
    err = _require_root()
    if err:
        return err
    if not _valid_port_proto(port_proto):
        return {"success": False, "verified": False, "output": f"Invalid port/proto '{port_proto}' — expected e.g. 14569/udp"}
    results = [_run_argv(a) for a in _argv_add_port(port_proto)]
    ok = all(r["success"] for r in results)
    status = status_service_ports()
    verified = port_proto in status.get("ports", [])
    return {"success": ok, "verified": verified, "output": "\n".join(r["output"] for r in results)}



def status_paste_config() -> dict:
    exists = os.path.exists(WG0_CONF_PATH)
    perms_ok = _wg0_conf_perms_ok()
    return {"done": exists and perms_ok is True, "exists": exists, "perms_ok": perms_ok}


def _validate_wg_config_text(text: str) -> tuple[bool, str]:
    if not text or not text.strip():
        return False, "Config text is empty."
    lower = text.lower()
    if "[interface]" not in lower:
        return False, "Missing [Interface] section."
    if "[peer]" not in lower:
        return False, "Missing [Peer] section."
    if "privatekey" not in lower:
        return False, "Missing PrivateKey under [Interface]."
    if "publickey" not in lower:
        return False, "Missing PublicKey under [Peer]."
    return True, "OK"


def action_paste_config(config_text: str) -> dict:
    err = _require_root()
    if err:
        return err
    valid, msg = _validate_wg_config_text(config_text)
    if not valid:
        return {"success": False, "verified": False, "output": f"Rejected: {msg}"}

    try:
        wg_dir = os.path.dirname(WG0_CONF_PATH)
        os.makedirs(wg_dir, mode=0o700, exist_ok=True)
        with open(WG0_CONF_PATH, "w") as f:
            f.write(config_text)
        os.chmod(WG0_CONF_PATH, 0o600)
        log(f"Wrote {WG0_CONF_PATH} (private key never logged)")
    except OSError as e:
        return {"success": False, "verified": False, "output": f"Write failed: {e}"}

    status = status_paste_config()
    if status["done"]:
        if "tunnels" not in _cfg:
            _cfg["tunnels"] = {}
        _cfg["tunnels"]["tunnel.pi.mode"] = "pi"
        _cfg["tunnels"]["tunnel.pi.interface"] = "wg0"
        _cfg["tunnels"]["tunnel.pi.config_path"] = WG0_CONF_PATH
        save_config(_cfg)
    return {"success": True, "verified": status["done"], "output": "wg0.conf written, permissions set to 600."}



def status_attach_interface() -> dict:
    zone = _firewalld_zone_info()
    if zone is None:
        return {"done": False, "zone_exists": False}
    return {"done": "wg0" in zone["interfaces"], "zone_exists": True, "interfaces": zone["interfaces"]}


def _argv_attach_interface() -> list[list[str]]:
    return [
        ["firewall-cmd", "--permanent", f"--zone={FIREWALLD_ZONE}", "--add-interface=wg0"],
        ["firewall-cmd", "--reload"],
    ]


def action_attach_interface() -> dict:
    err = _require_root()
    if err:
        return err
    results = [_run_argv(a) for a in _argv_attach_interface()]
    ok = all(r["success"] for r in results)
    status = status_attach_interface()
    return {"success": ok, "verified": status["done"], "output": "\n".join(r["output"] for r in results)}



def _wg_quick_template_available() -> bool:
    try:
        r = subprocess.run(["systemctl", "list-unit-files", "wg-quick@.service"],
                            capture_output=True, text=True, timeout=5)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    return "wg-quick@.service" in r.stdout

_ARDC_FALLBACK_UNIT_PATH = "/etc/systemd/system/44net-tunnel.service"
_ARDC_FALLBACK_UNIT_CONTENT = """[Unit]
Description=WireGuard single device 44Net Connect tunnel
Requires=network-online.target

[Service]
Type=oneshot
RemainAfterExit=true
ExecStart=wg-quick up /etc/wireguard/wg0.conf
ExecStop=wg-quick down /etc/wireguard/wg0.conf

[Install]
WantedBy=multi-user.target
"""


def status_enable_tunnel() -> dict:
    wg_status = _wg_show_wg0()
    up = wg_status is not None and bool(wg_status.get("latest_handshake"))
    return {"done": up, "wg_status": wg_status, "wg0_present": _wg0_interface_present()}


def action_enable_tunnel() -> dict:
    err = _require_root()
    if err:
        return err

    if _wg_quick_template_available():
        results = [
            _run_argv(["systemctl", "enable", "wg-quick@wg0"]),
            _run_argv(["systemctl", "start", "wg-quick@wg0"]),
        ]
        used_fallback = False
    else:
        try:
            with open(_ARDC_FALLBACK_UNIT_PATH, "w") as f:
                f.write(_ARDC_FALLBACK_UNIT_CONTENT)
        except OSError as e:
            return {"success": False, "verified": False, "output": f"Could not write fallback unit: {e}"}
        results = [
            _run_argv(["systemctl", "daemon-reload"]),
            _run_argv(["systemctl", "enable", "--now", "44net-tunnel.service"]),
        ]
        used_fallback = True

    ok = all(r["success"] for r in results)
    time.sleep(2)
    status = status_enable_tunnel()
    note = " (used ARDC fallback unit, §1a.3 — standard wg-quick@.service template not found)" if used_fallback else ""
    return {"success": ok, "verified": status["done"], "output": "\n".join(r["output"] for r in results) + note}


def check_myip() -> dict:
    try:
        req = urllib.request.Request("https://connect.44net.cloud/myip", headers={"User-Agent": "44helper"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            ip = resp.read().decode("utf-8", errors="replace").strip()
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        return {"success": False, "ip": None, "output": f"myip check failed: {e}"}
    is_44 = ip.startswith("44.")
    return {"success": is_44, "ip": ip, "output": f"connect.44net.cloud/myip reports: {ip}"}


def check_rpt_registrations() -> dict:
    try:
        r = subprocess.run(["asterisk", "-rx", "rpt show registrations"],
                            capture_output=True, text=True, timeout=8)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return {"success": False, "output": "asterisk not available on this system"}
    return {"success": r.returncode == 0, "output": r.stdout.strip() or r.stderr.strip()}


def build_pi_install_status(cfg: configparser.ConfigParser) -> dict:
    steps = {
        "firewalld_prereq": status_firewalld_prereq(),
        "resolved_prereq": status_resolved_prereq(),
        "create_zone": status_create_zone(),
        "service_ports": status_service_ports(),
        "paste_config": status_paste_config(),
        "attach_interface": status_attach_interface(),
        "enable_tunnel": status_enable_tunnel(),
    }
    return {"steps": steps, "services_catalog": PI_INSTALL_SERVICES, "checked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}



_SSH_CONNECT_TIMEOUT = 6
_SSH_CMD_TIMEOUT = 10

_ROUTER_PROBES = {
    "ping": "true",
    "uci_available": "command -v uci >/dev/null 2>&1 && echo yes || echo no",
    "openwrt_release": "cat /etc/openwrt_release 2>/dev/null",
    "glinet_version": "cat /etc/glversion 2>/dev/null",
    "luci_present": "test -e /www/cgi-bin/luci && echo yes || echo no",
}

_KNOWN_GLINET_MODELS = [
    "GL-MT300N", "GL-AR300M", "GL-MT3000", "GL-XE300", "GL-MT2500A", "GL-MT2500",
]


def _ssh_base_argv(cfg: configparser.ConfigParser) -> list[str] | None:
    if shutil.which("ssh") is None:
        return None
    host = cfg.get("router", "host", fallback="").strip()
    user = cfg.get("router", "user", fallback="").strip()
    key_path = cfg.get("router", "key_path", fallback="").strip()
    if not host or not user or not key_path:
        return None
    if not os.path.exists(key_path):
        return None
    return [
        "ssh",
        "-o", "BatchMode=yes",
        "-o", f"ConnectTimeout={_SSH_CONNECT_TIMEOUT}",
        "-o", "StrictHostKeyChecking=accept-new",
        "-i", key_path,
        f"{user}@{host}",
    ]


def _ssh_run(cfg: configparser.ConfigParser, probe_key: str) -> dict:
    if probe_key not in _ROUTER_PROBES:
        return {"ok": False, "output": f"internal error: unknown probe '{probe_key}'"}

    base = _ssh_base_argv(cfg)
    if base is None:
        return {"ok": False, "output": "router access not configured or ssh client unavailable"}

    argv = base + [_ROUTER_PROBES[probe_key]]
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=_SSH_CMD_TIMEOUT)
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        return {"ok": False, "output": f"ssh failed: {e}"}

    if r.returncode != 0:
        return {"ok": False, "output": (r.stderr or r.stdout or f"ssh exited {r.returncode}").strip()}
    return {"ok": True, "output": r.stdout.strip()}


def _match_known_glinet_model(version_text: str) -> str | None:
    for model in _KNOWN_GLINET_MODELS:
        if model.lower() in version_text.lower():
            return model
    return None


def probe_router(cfg: configparser.ConfigParser) -> dict:
    result: dict = {
        "configured": _ssh_base_argv(cfg) is not None,
        "reachable": False,
        "is_openwrt": False,
        "is_glinet": False,
        "matched_model": None,
        "uci_available": False,
        "luci_present": None,
        "raw_openwrt_release": "",
        "raw_glversion": "",
    }
    if not result["configured"]:
        return result

    ping = _ssh_run(cfg, "ping")
    result["reachable"] = ping["ok"]
    if not result["reachable"]:
        return result

    uci = _ssh_run(cfg, "uci_available")
    result["uci_available"] = uci["ok"] and uci["output"].strip() == "yes"

    rel = _ssh_run(cfg, "openwrt_release")
    if rel["ok"]:
        result["raw_openwrt_release"] = rel["output"]
        result["is_openwrt"] = "openwrt" in rel["output"].lower()

    gl = _ssh_run(cfg, "glinet_version")
    if gl["ok"] and gl["output"]:
        result["raw_glversion"] = gl["output"]
        result["is_glinet"] = True
        result["matched_model"] = _match_known_glinet_model(gl["output"])
    elif result["is_openwrt"]:
        result["matched_model"] = _match_known_glinet_model(result["raw_openwrt_release"])
        result["is_glinet"] = result["matched_model"] is not None

    luci = _ssh_run(cfg, "luci_present")
    if luci["ok"]:
        result["luci_present"] = luci["output"].strip() == "yes"

    return result


_router_cache: dict = {"data": None, "ts": 0.0}
_router_cache_lock = threading.Lock()


def get_router_status(cfg: configparser.ConfigParser, force: bool = False) -> dict:
    poll_interval = cfg.getint("router", "poll_interval_sec", fallback=60)
    now = time.monotonic()
    with _router_cache_lock:
        cached = _router_cache["data"]
        age = now - _router_cache["ts"]
        if not force and cached is not None and age < poll_interval:
            result = dict(cached)
            result["_cache_age_sec"] = round(age, 1)
            return result

    result = probe_router(cfg)
    result["_cache_age_sec"] = 0.0
    with _router_cache_lock:
        _router_cache["data"] = result
        _router_cache["ts"] = now
    return result


def save_router_config(cfg: configparser.ConfigParser, access_method: str, host: str,
                        user: str, key_path: str, poll_interval_sec: str) -> dict:
    if access_method not in ("none", "ssh", "api"):
        return {"success": False, "output": f"Invalid access_method '{access_method}'"}
    if access_method == "ssh":
        if not host.strip() or not user.strip() or not key_path.strip():
            return {"success": False, "output": "host, user, and key_path are all required for SSH access"}
        if not os.path.exists(key_path):
            return {"success": False, "output": f"Key file not found: {key_path}"}
    try:
        poll = int(poll_interval_sec)
        if poll < 5:
            return {"success": False, "output": "poll_interval_sec must be at least 5"}
    except ValueError:
        return {"success": False, "output": "poll_interval_sec must be an integer"}

    if "router" not in cfg:
        cfg["router"] = {}
    cfg["router"]["access_method"] = access_method
    cfg["router"]["host"] = host.strip()
    cfg["router"]["user"] = user.strip()
    cfg["router"]["key_path"] = key_path.strip()
    cfg["router"]["poll_interval_sec"] = str(poll)
    save_config(cfg)

    with _router_cache_lock:
        _router_cache["data"] = None
        _router_cache["ts"] = 0.0

    log(f"Router config saved: access_method={access_method}, host={host}, user={user}")
    return {"success": True, "output": "Router config saved."}



ROUTER_INSTALL_STEPS = [
    "allocation_type", "capture_config", "apply_wg_config", "set_lan_ip",
    "bring_up_tunnel", "pi_address", "firewall_zone", "verify",
]

_pending_router_wg: dict | None = None
_pending_router_wg_lock = threading.Lock()



def action_install_luci(cfg: configparser.ConfigParser) -> dict:
    base = _ssh_base_argv(cfg)
    if base is None:
        return {"success": False, "verified": False, "output": "Router access not configured/reachable."}
    remote_cmd = "opkg update >/dev/null 2>&1; opkg install luci"
    try:
        r = subprocess.run(base + [remote_cmd], capture_output=True, text=True, timeout=90)
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        return {"success": False, "verified": False, "output": f"ssh failed: {e}"}
    log(f"Router LuCI install attempt: exit {r.returncode}")
    luci = _ssh_run(cfg, "luci_present")
    verified = luci["ok"] and luci["output"].strip() == "yes"
    return {"success": r.returncode == 0, "verified": verified, "output": (r.stdout + r.stderr).strip()}



def status_allocation_type(cfg: configparser.ConfigParser) -> dict:
    mode = cfg.get("tunnels", "tunnel.router.mode", fallback="")
    return {"done": mode in ("router_single", "router_subnet"), "mode": mode or None}


def action_set_allocation_type(cfg: configparser.ConfigParser, mode: str) -> dict:
    if mode not in ("router_single", "router_subnet"):
        return {"success": False, "verified": False, "output": f"Invalid allocation type '{mode}'"}
    if "tunnels" not in cfg:
        cfg["tunnels"] = {}
    cfg["tunnels"]["tunnel.router.mode"] = mode
    save_config(cfg)
    return {"success": True, "verified": True, "output": f"Allocation type set to {mode}."}



def _cidr_valid(cidr: str) -> tuple[bool, str]:
    try:
        iface = ipaddress.ip_interface(cidr)
    except ValueError as e:
        return False, str(e)
    if iface.version != 4:
        return False, "Only IPv4 CIDR is supported here."
    return True, ""


def status_capture_config(cfg: configparser.ConfigParser) -> dict:
    with _pending_router_wg_lock:
        pending = _pending_router_wg is not None
    applied = cfg.get("tunnels", "tunnel.router.wg_applied", fallback="") == "true"
    address = cfg.get("tunnels", "tunnel.router.wg_address", fallback="")
    lan_subnet = cfg.get("tunnels", "tunnel.router.lan_subnet", fallback="")
    mode = cfg.get("tunnels", "tunnel.router.mode", fallback="")
    if mode == "router_subnet":
        done = bool(address) and bool(lan_subnet)
    else:
        done = bool(address)
    return {"done": done, "pending_apply": pending,
            "applied": applied, "wg_address": address, "lan_subnet": lan_subnet, "mode": mode}


def action_capture_router_config(cfg: configparser.ConfigParser, config_text: str, lan_subnet_cidr: str = "") -> dict:
    mode = cfg.get("tunnels", "tunnel.router.mode", fallback="")

    valid, msg = _validate_wg_config_text(config_text)
    if not valid:
        return {"success": False, "verified": False, "output": f"Rejected: {msg}"}

    if mode == "router_subnet":
        if not lan_subnet_cidr:
            return {"success": False, "verified": False, "output": "LAN subnet CIDR is required for Model C (routed subnet)."}
        cidr_ok, cidr_msg = _cidr_valid(lan_subnet_cidr)
        if not cidr_ok:
            return {"success": False, "verified": False, "output": f"Invalid LAN subnet CIDR: {cidr_msg}"}
    else:
        lan_subnet_cidr = ""

    parsed = _parse_wg_conf_text(config_text, mask_private_key=False)
    address = parsed["interface"].get("Address", "")
    allowed_ips = parsed["peers"][0].get("AllowedIPs", "") if parsed["peers"] else ""
    endpoint = parsed["peers"][0].get("Endpoint", "") if parsed["peers"] else ""

    note = ""
    if mode == "router_subnet":
        expected_split = {"44.0.0.0/9", "44.128.0.0/10"}
        given = {p.strip() for p in allowed_ips.split(",")}
        if given and given != expected_split and "0.0.0.0/0" in given:
            note = (" Note: AllowedIPs looks like full-tunnel (0.0.0.0/0), not the "
                    "44.0.0.0/9, 44.128.0.0/10 split-tunnel shape §1b.3 describes for "
                    "a routed-subnet allocation — double check this is really a Model C config.")

    global _pending_router_wg
    with _pending_router_wg_lock:
        _pending_router_wg = {"config_text": config_text, "captured_at": time.time()}

    if "tunnels" not in cfg:
        cfg["tunnels"] = {}
    cfg["tunnels"]["tunnel.router.wg_address"] = address
    cfg["tunnels"]["tunnel.router.wg_allowed_ips"] = allowed_ips
    cfg["tunnels"]["tunnel.router.wg_endpoint"] = endpoint
    if lan_subnet_cidr:
        cfg["tunnels"]["tunnel.router.lan_subnet"] = lan_subnet_cidr
    save_config(cfg)

    subnet_note = f"; LAN subnet: {lan_subnet_cidr}" if lan_subnet_cidr else " (Model B — no LAN subnet needed)"
    return {"success": True, "verified": True,
            "output": f"Captured. Interface address: {address or '(none parsed)'}{subnet_note}.{note}"}



def _build_uci_wg_apply_cmd(iface_name: str, wg: dict) -> str | None:
    iface = wg["interface"]
    if not wg["peers"]:
        return None
    peer = wg["peers"][0]

    private_key = iface.get("PrivateKey", "")
    address = iface.get("Address", "")
    public_key = peer.get("PublicKey", "")
    allowed_ips = peer.get("AllowedIPs", "")
    endpoint = peer.get("Endpoint", "")
    preshared_key = peer.get("PresharedKey", "")

    if not (private_key and address and public_key and allowed_ips and endpoint):
        return None

    endpoint_host, _, endpoint_port = endpoint.partition(":")
    q = shlex.quote

    cmds = [
        f"uci set network.{iface_name}=interface",
        f"uci set network.{iface_name}.proto='wireguard'",
        f"uci set network.{iface_name}.private_key={q(private_key)}",
        f"uci delete network.{iface_name}.addresses 2>/dev/null",
        f"uci add_list network.{iface_name}.addresses={q(address)}",
        f"uci set network.wgpeer_{iface_name}=wireguard_{iface_name}",
        f"uci set network.wgpeer_{iface_name}.public_key={q(public_key)}",
        f"uci set network.wgpeer_{iface_name}.allowed_ips={q(allowed_ips)}",
        f"uci set network.wgpeer_{iface_name}.endpoint_host={q(endpoint_host)}",
        f"uci set network.wgpeer_{iface_name}.route_allowed_ips='1'",
        f"uci set network.wgpeer_{iface_name}.persistent_keepalive='25'",
    ]
    if endpoint_port.strip().isdigit():
        cmds.append(f"uci set network.wgpeer_{iface_name}.endpoint_port={q(endpoint_port.strip())}")
    if preshared_key:
        cmds.append(f"uci set network.wgpeer_{iface_name}.preshared_key={q(preshared_key)}")
    cmds.append("uci commit network")

    cmds += [
        "uci set firewall.wgzone=zone",
        "uci set firewall.wgzone.name='wireguard'",
        "uci set firewall.wgzone.input='ACCEPT'",
        "uci set firewall.wgzone.output='ACCEPT'",
        "uci set firewall.wgzone.forward='REJECT'",
        "uci set firewall.wgzone.masq='1'",
        f"uci delete firewall.wgzone.network 2>/dev/null",
        f"uci add_list firewall.wgzone.network={q(iface_name)}",
        "uci commit firewall",
        "/etc/init.d/firewall reload",
    ]

    return " && ".join(cmds)


def status_apply_wg_config(cfg: configparser.ConfigParser) -> dict:
    applied = cfg.get("tunnels", "tunnel.router.wg_applied", fallback="") == "true"
    return {"done": applied}


def action_apply_router_wg_config(cfg: configparser.ConfigParser) -> dict:
    global _pending_router_wg
    with _pending_router_wg_lock:
        pending = _pending_router_wg

    if pending is None:
        return {"success": False, "verified": False, "output": "No captured config to apply — run step 4 first."}

    parsed = _parse_wg_conf_text(pending["config_text"], mask_private_key=False)
    cmd = _build_uci_wg_apply_cmd("wgclient", parsed)
    if cmd is None:
        return {"success": False, "verified": False, "output": "Captured config is missing required fields (private key/address/public key/allowed IPs/endpoint)."}

    base = _ssh_base_argv(cfg)
    if base is None:
        return {"success": False, "verified": False, "output": "Router access not configured/reachable."}

    try:
        r = subprocess.run(base + [cmd], capture_output=True, text=True, timeout=30)
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        return {"success": False, "verified": False, "output": f"ssh failed: {e}"}

    ok = r.returncode == 0
    if ok:
        with _pending_router_wg_lock:
            _pending_router_wg = None
        cfg["tunnels"]["tunnel.router.wg_applied"] = "true"
        save_config(cfg)
        log("Router WireGuard interface applied via uci (private key not logged)")

    return {"success": ok, "verified": ok, "output": (r.stdout + r.stderr).strip() or ("OK" if ok else "uci command failed")}



def status_set_lan_ip(cfg: configparser.ConfigParser) -> dict:
    done = cfg.get("tunnels", "tunnel.router.lan_ip_applied", fallback="") == "true"
    return {"done": done}


def action_set_router_lan_ip(cfg: configparser.ConfigParser) -> dict:
    lan_subnet = cfg.get("tunnels", "tunnel.router.lan_subnet", fallback="")
    if not lan_subnet:
        return {"success": False, "verified": False, "output": "No LAN subnet captured — run step 4 first."}

    ok, msg = _cidr_valid(lan_subnet)
    if not ok:
        return {"success": False, "verified": False, "output": f"Stored LAN subnet is invalid: {msg}"}

    iface = ipaddress.ip_interface(lan_subnet)
    ip_only = str(iface.ip)
    netmask = str(iface.netmask)
    q = shlex.quote

    base = _ssh_base_argv(cfg)
    if base is None:
        return {"success": False, "verified": False, "output": "Router access not configured/reachable."}

    cmd = (
        f"uci set network.lan.proto='static' && "
        f"uci set network.lan.ipaddr={q(ip_only)} && "
        f"uci set network.lan.netmask={q(netmask)} && "
        f"uci commit network && "
        f"/etc/init.d/network reload"
    )
    try:
        subprocess.run(base + [cmd], capture_output=True, text=True, timeout=8)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    cfg["tunnels"]["tunnel.router.lan_ip_applied"] = "true"
    save_config(cfg)
    log(f"Router LAN IP change attempted to {lan_subnet} (session likely dropped, per §1b.5)")

    return {
        "success": True,
        "verified": False,
        "output": (
            f"Change sent (new LAN IP {ip_only}, netmask {netmask}). The router's admin "
            "session and this Pi's own network connection may now be disrupted. "
            "Renew this Pi's DHCP lease (or reboot it), update the router host field "
            f"on step 1 to {ip_only}, then use Re-probe to confirm."
        ),
    }



def status_bring_up_tunnel(cfg: configparser.ConfigParser) -> dict:
    done = cfg.get("tunnels", "tunnel.router.tunnel_up", fallback="") == "true"
    return {"done": done}


def action_bring_up_router_tunnel(cfg: configparser.ConfigParser) -> dict:
    base = _ssh_base_argv(cfg)
    if base is None:
        return {"success": False, "verified": False, "output": "Router access not configured/reachable."}
    cmd = "ifup wgclient 2>&1; sleep 2; ifstatus wgclient 2>/dev/null | head -c 400"
    try:
        r = subprocess.run(base + [cmd], capture_output=True, text=True, timeout=20)
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        return {"success": False, "verified": False, "output": f"ssh failed: {e}"}
    ok = r.returncode == 0
    out = (r.stdout + r.stderr).strip()
    verified = '"up":true' in out.replace(" ", "")
    if verified:
        cfg["tunnels"]["tunnel.router.tunnel_up"] = "true"
        save_config(cfg)
    return {"success": ok, "verified": verified, "output": out}



def _pi_primary_mac() -> str | None:
    for iface in ("eth0", "wlan0"):
        path = f"/sys/class/net/{iface}/address"
        if os.path.exists(path):
            try:
                with open(path) as f:
                    return f.read().strip()
            except OSError:
                continue
    return None


def status_pi_address(cfg: configparser.ConfigParser) -> dict:
    mac = _pi_primary_mac()
    return {"done": False, "pi_mac": mac}


def action_lookup_pi_address(cfg: configparser.ConfigParser) -> dict:
    mac = _pi_primary_mac()
    if not mac:
        return {"success": False, "verified": False, "output": "Could not determine this Pi's own MAC address."}

    base = _ssh_base_argv(cfg)
    if base is None:
        return {"success": False, "verified": False, "output": "Router access not configured/reachable."}

    q = shlex.quote
    cmd = f"grep -i {q(mac)} /tmp/dhcp.leases 2>/dev/null"
    try:
        r = subprocess.run(base + [cmd], capture_output=True, text=True, timeout=10)
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        return {"success": False, "verified": False, "output": f"ssh failed: {e}"}

    line = r.stdout.strip()
    if not line:
        return {"success": True, "verified": False, "output": f"No DHCP lease found yet for {mac} — the Pi may not have renewed since the subnet change."}

    parts = line.split()
    pi_ip = parts[2] if len(parts) >= 3 else None
    if pi_ip:
        cfg["tunnels"]["tunnel.router.pi_44_address"] = pi_ip
        cfg["tunnels"]["tunnel.router.pi_mac"] = mac
        save_config(cfg)
    return {"success": True, "verified": bool(pi_ip), "output": f"Pi's current 44Net address: {pi_ip or '(unparsed)'}"}


def action_add_static_binding(cfg: configparser.ConfigParser) -> dict:
    mac = cfg.get("tunnels", "tunnel.router.pi_mac", fallback="") or _pi_primary_mac()
    pi_ip = cfg.get("tunnels", "tunnel.router.pi_44_address", fallback="")
    if not mac or not pi_ip:
        return {"success": False, "verified": False, "output": "Need a known Pi MAC and 44Net address first — run the lookup above."}

    base = _ssh_base_argv(cfg)
    if base is None:
        return {"success": False, "verified": False, "output": "Router access not configured/reachable."}

    q = shlex.quote
    cmd = (
        f"uci add dhcp host >/dev/null && "
        f"uci set dhcp.@host[-1].mac={q(mac)} && "
        f"uci set dhcp.@host[-1].ip={q(pi_ip)} && "
        f"uci set dhcp.@host[-1].name='pi-44helper' && "
        f"uci commit dhcp && "
        f"/etc/init.d/dnsmasq reload"
    )
    try:
        r = subprocess.run(base + [cmd], capture_output=True, text=True, timeout=15)
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        return {"success": False, "verified": False, "output": f"ssh failed: {e}"}
    ok = r.returncode == 0
    return {"success": ok, "verified": ok, "output": (r.stdout + r.stderr).strip() or ("OK" if ok else "uci command failed")}



def status_firewall_zone(cfg: configparser.ConfigParser) -> dict:
    done = cfg.get("tunnels", "tunnel.router.zone_fixed", fallback="") == "true"
    return {"done": done}


def action_fix_wireguard_zone(cfg: configparser.ConfigParser) -> dict:
    base = _ssh_base_argv(cfg)
    if base is None:
        return {"success": False, "verified": False, "output": "Router access not configured/reachable."}

    apply_cmd = (
        "uci set firewall.wgzone.forward='ACCEPT' && "
        "uci set firewall.wgzone.masq='0' && "
        "uci commit firewall && "
        "/etc/init.d/firewall reload"
    )
    try:
        r2 = subprocess.run(base + [apply_cmd], capture_output=True, text=True, timeout=15)
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        return {"success": False, "verified": False, "output": f"ssh failed: {e}"}
    ok = r2.returncode == 0
    if ok:
        cfg["tunnels"]["tunnel.router.zone_fixed"] = "true"
        save_config(cfg)
    return {"success": ok, "verified": ok, "output": (r2.stdout + r2.stderr).strip() or ("OK" if ok else "uci command failed — is firewall.wgzone present? (requires step 5 applied first)")}



def check_ping_traceroute_44() -> dict:
    target = "44.1.1.17"
    try:
        ping = subprocess.run(["ping", "-c", "2", "-W", "2", target],
                               capture_output=True, text=True, timeout=10)
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        return {"success": False, "output": f"ping failed: {e}"}

    ping_ok = ping.returncode == 0
    trace_out = ""
    other_44_hop = False
    if shutil.which("traceroute"):
        try:
            tr = subprocess.run(["traceroute", "-n", "-m", "8", target],
                                 capture_output=True, text=True, timeout=15)
            trace_out = tr.stdout
            for line in trace_out.splitlines()[1:]:
                if "44." in line and target not in line:
                    other_44_hop = True
                    break
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

    return {
        "success": ping_ok,
        "other_44_hop": other_44_hop,
        "output": f"ping {'OK' if ping_ok else 'FAILED'} to {target}." +
                  (f" Traceroute shows another 44.x.x.x hop before the destination." if other_44_hop else " No intermediate 44.x.x.x hop seen — tunnel may not be in the path.") +
                  ("\n" + trace_out if trace_out else ""),
    }


KNOWN_GOOD_ROUTER_DIR = "/etc/44helper/known_good_routers"


def save_known_good_router_note(cfg: configparser.ConfigParser, probe: dict) -> dict:
    try:
        os.makedirs(KNOWN_GOOD_ROUTER_DIR, mode=0o700, exist_ok=True)
    except OSError as e:
        return {"success": False, "output": f"Could not create notes dir: {e}"}

    model = probe.get("matched_model") or "unknown-model"
    mode = cfg.get("tunnels", "tunnel.router.mode", fallback="")
    model_label = {
        "router_subnet": "Model C (routed subnet, design plan §1b/§2)",
        "router_single": "Model B (single address + port-forward, design plan §2)",
    }.get(mode, "(allocation type not recorded)")

    fname = f"{model.replace(' ', '_')}_{time.time():.3f}-{random.randint(1000,9999)}".replace(".", "-") + ".md"
    path = os.path.join(KNOWN_GOOD_ROUTER_DIR, fname)

    if mode == "router_subnet":
        commands_section = (
            "- WireGuard interface + zone: `uci set network.wgclient=interface` ... "
            "`uci set firewall.wgzone=zone` ... (see `_build_uci_wg_apply_cmd` in source)\n"
            "- LAN IP: `uci set network.lan.proto='static'` + ipaddr/netmask from the allocated subnet\n"
            "- Firewall zone: `uci set firewall.wgzone.forward='ACCEPT'`, `masq='0'`"
        )
        extra_fields = f"- LAN subnet: {cfg.get('tunnels', 'tunnel.router.lan_subnet', fallback='(not recorded)')}\n"
    else:
        commands_section = (
            "- WireGuard interface + zone: `uci set network.wgclient=interface` ... "
            "`uci set firewall.wgzone=zone` (default masq='1', kept) — same as Model C's step 5\n"
            "- Port forward: `uci add firewall redirect` then `uci set firewall.<id>.src='wireguard'`, "
            "`dest='lan'`, `dest_ip=<Pi LAN IP>`, `dest_port=<port>`, `proto=<udp|tcp>`, `target='DNAT'`"
        )
        extra_fields = f"- Recorded forwards: {cfg.get('tunnels', 'tunnel.router.forwards', fallback='(none recorded)')}\n"

    content = f"""# Known-good router config — {model}

Generated by {APP_TITLE} v{APP_VERSION} on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
submitted: no

- Firmware: {'OpenWrt' if probe.get('is_openwrt') else 'unknown'}
- GL.iNet detected: {probe.get('is_glinet')}
- Matched model (design plan §1b.7 list): {model}
- LuCI present: {probe.get('luci_present')}
- Access method: SSH (key-based)
- Allocation type: {model_label}
{extra_fields}- WireGuard interface address: {cfg.get('tunnels', 'tunnel.router.wg_address', fallback='(not recorded)')}

## Commands used (uci, via SSH)

{commands_section}

No private keys or credentials are included in this file.
This is a draft suitable for submission to the ARDC wiki's Supported
Platforms page, which explicitly invites community contributions:
https://wiki.ampr.org/wiki/44Net_Connect/Supported_Platforms
"""
    try:
        with open(path, "w") as f:
            f.write(content)
        os.chmod(path, 0o600)
    except OSError as e:
        return {"success": False, "output": f"Could not write note: {e}"}

    log(f"Saved known-good router note: {path}")
    return {"success": True, "output": f"Saved to {path}", "filename": fname}


_NOTE_FILENAME_RE = re.compile(r"^[A-Za-z0-9_.\-]+\.md$")


def list_known_good_router_notes() -> list[str]:
    try:
        if not os.path.isdir(KNOWN_GOOD_ROUTER_DIR):
            return []
        return sorted(f for f in os.listdir(KNOWN_GOOD_ROUTER_DIR) if _NOTE_FILENAME_RE.match(f))
    except OSError:
        return []


def read_known_good_router_note(filename: str) -> str | None:
    if not _NOTE_FILENAME_RE.match(filename):
        return None
    path = os.path.join(KNOWN_GOOD_ROUTER_DIR, filename)
    real_dir = os.path.realpath(KNOWN_GOOD_ROUTER_DIR)
    real_path = os.path.realpath(path)
    if not real_path.startswith(real_dir + os.sep):
        return None
    try:
        with open(real_path) as f:
            return f.read()
    except OSError:
        return None



MODEL_B_FORWARD_SERVICES = {
    "iax2": {"label": "AllStarLink IAX2", "port": "4569", "proto": "udp", "default_on": True},
}


def status_port_forwards(cfg: configparser.ConfigParser) -> dict:
    raw = cfg.get("tunnels", "tunnel.router.forwards", fallback="")
    forwards = [f for f in raw.split(",") if f]
    return {"done": bool(forwards), "forwards": forwards}


def _valid_port(port: str) -> bool:
    return port.isdigit() and 1 <= int(port) <= 65535


def action_add_port_forward(cfg: configparser.ConfigParser, name: str, port: str, proto: str) -> dict:
    if proto not in ("udp", "tcp"):
        return {"success": False, "verified": False, "output": f"Invalid protocol '{proto}' — expected udp or tcp"}
    if not _valid_port(port):
        return {"success": False, "verified": False, "output": f"Invalid port '{port}'"}
    if not name or any(c in name for c in " '\"$();&|"):
        return {"success": False, "verified": False, "output": "Invalid forward name"}

    pi_ip = cfg.get("tunnels", "tunnel.router.pi_44_address", fallback="")
    if not pi_ip:
        return {"success": False, "verified": False, "output": "Pi's address is not known yet — run step 8's lookup first."}

    base = _ssh_base_argv(cfg)
    if base is None:
        return {"success": False, "verified": False, "output": "Router access not configured/reachable."}

    try:
        r_add = subprocess.run(base + ["uci add firewall redirect"], capture_output=True, text=True, timeout=10)
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        return {"success": False, "verified": False, "output": f"ssh failed: {e}"}
    new_id = r_add.stdout.strip()
    if r_add.returncode != 0 or not new_id:
        return {"success": False, "verified": False, "output": f"uci add failed: {(r_add.stdout + r_add.stderr).strip()}"}

    q = shlex.quote
    cfg_id = f"firewall.{new_id}"
    set_cmd = (
        f"uci set {cfg_id}.name={q(name)} && "
        f"uci set {cfg_id}.src='wireguard' && "
        f"uci set {cfg_id}.src_dport={q(port)} && "
        f"uci set {cfg_id}.dest='lan' && "
        f"uci set {cfg_id}.dest_ip={q(pi_ip)} && "
        f"uci set {cfg_id}.dest_port={q(port)} && "
        f"uci set {cfg_id}.proto={q(proto)} && "
        f"uci set {cfg_id}.target='DNAT' && "
        f"uci commit firewall && "
        f"/etc/init.d/firewall reload"
    )
    try:
        r_set = subprocess.run(base + [set_cmd], capture_output=True, text=True, timeout=15)
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        return {"success": False, "verified": False, "output": f"ssh failed: {e}"}

    ok = r_set.returncode == 0
    if ok:
        existing = cfg.get("tunnels", "tunnel.router.forwards", fallback="")
        entries = [e for e in existing.split(",") if e]
        entries.append(f"{name}:{port}/{proto}")
        cfg["tunnels"]["tunnel.router.forwards"] = ",".join(entries)
        save_config(cfg)
        log(f"Added router port-forward: {name} {port}/{proto} -> {pi_ip}")

    return {"success": ok, "verified": ok,
            "output": (r_set.stdout + r_set.stderr).strip() or ("OK" if ok else "uci command failed")}


def check_model_b_verify(cfg: configparser.ConfigParser) -> dict:
    myip = check_myip()
    forwards = status_port_forwards(cfg)
    note = (" Note: this confirms outbound traffic uses the router's 44.x.x.x "
            "address and that a forward rule is recorded — it does NOT confirm "
            "inbound reachability from outside the NAT, which 44helper has no "
            "vantage point to test from here.")
    return {
        "success": myip.get("success", False) and forwards["done"],
        "output": myip.get("output", "") + note,
        "forwards": forwards["forwards"],
    }


def status_verify(cfg: configparser.ConfigParser) -> dict:
    done = cfg.get("tunnels", "tunnel.router.verified", fallback="") == "true"
    return {"done": done}


def build_router_install_status(cfg: configparser.ConfigParser) -> dict:
    steps = {
        "allocation_type": status_allocation_type(cfg),
        "capture_config": status_capture_config(cfg),
        "apply_wg_config": status_apply_wg_config(cfg),
        "set_lan_ip": status_set_lan_ip(cfg),
        "bring_up_tunnel": status_bring_up_tunnel(cfg),
        "pi_address": status_pi_address(cfg),
        "firewall_zone": status_firewall_zone(cfg),
        "port_forwards": status_port_forwards(cfg),
        "verify": status_verify(cfg),
    }
    return {"steps": steps, "checked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}



def _local_port_listening(port: int, proto: str = "tcp") -> bool:
    path = f"/proc/net/{proto}"
    port_hex = format(port, "04X")
    try:
        with open(path) as f:
            next(f, None)
            for line in f:
                fields = line.split()
                if len(fields) < 2:
                    continue
                local = fields[1]
                if ":" not in local:
                    continue
                _, p = local.rsplit(":", 1)
                if p.upper() == port_hex:
                    return True
    except (OSError, IndexError, ValueError):
        return False
    return False


def _systemctl_is_active(unit: str) -> bool:
    try:
        r = subprocess.run(["systemctl", "is-active", unit], capture_output=True, text=True, timeout=5)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    return r.stdout.strip() == "active"


_SERVICE_UNIT_DEFS: list[tuple[str, str, str, bool]] = [
    ("firewalld", "firewalld.service", "System", False),
    ("systemd-resolved", "systemd-resolved.service", "System", False),
    ("WireGuard tunnel (wg-quick@wg0)", "wg-quick@wg0.service", "44Net Tunnel", False),
    ("WireGuard tunnel (ARDC fallback unit)", "44net-tunnel.service", "44Net Tunnel", False),
    ("Asterisk (AllStarLink)", "asterisk.service", "AllStarLink / DVSwitch", False),
    ("USRP2M17", "usrp2m17.service", "AllStarLink / DVSwitch", False),
    ("asl_dvs_dashboard", "asl_dvs_dashboard.service", "Dashboards (should stay private)", True),
    ("dvs_dashboard", "dvs_dashboard.service", "Dashboards (should stay private)", True),
]

_SERVICE_PORT_DEFS: list[tuple[str, int, str, str, bool]] = [
    ("sysmon dashboard", 9999, "tcp", "Dashboards (should stay private)", True),
    ("Zello bridge RX leg", 34012, "udp", "AllStarLink / DVSwitch", False),
    ("Zello bridge TX leg", 32012, "udp", "AllStarLink / DVSwitch", False),
]


def build_services_status(cfg: configparser.ConfigParser) -> dict:
    groups: dict[str, list[dict]] = {}
    for label, unit, group, flag in _SERVICE_UNIT_DEFS:
        active = _systemctl_is_active(unit)
        groups.setdefault(group, []).append({
            "label": label, "source": unit, "active": active, "flag_public": flag,
        })
    for label, port, proto, group, flag in _SERVICE_PORT_DEFS:
        listening = _local_port_listening(port, proto)
        groups.setdefault(group, []).append({
            "label": label, "source": f"port {port}/{proto}", "active": listening, "flag_public": flag,
        })
    my_port = cfg.getint("server", "port", fallback=9997)
    groups.setdefault("Dashboards (should stay private)", []).append({
        "label": "44helper (this dashboard)", "source": f"port {my_port}/tcp", "active": True, "flag_public": True,
    })
    return {"groups": groups, "checked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}


_PORTS_REFERENCE: list[tuple[str, str, str, str, bool]] = [
    ("IAX2", "4569", "udp", "AllStarLink IAX2 — primary 44Net Connect use case", False),
    ("EchoLink", "5198-5199", "udp", "EchoLink", False),
    ("VOTER/RTCM", "1667", "udp", "VOTER/RTCM", False),
    ("Asterisk AMI", "5038", "tcp", "Asterisk Manager Interface — especially risky if public", True),
    ("USRP2M17", "34008", "udp", "M17 gateway USRP leg", False),
    ("Zello RX", "34012", "udp", "Zello bridge USRP leg", False),
    ("Zello TX", "32012", "udp", "Zello bridge USRP leg", False),
    ("sysmon", "9999", "tcp", "sysmon dashboard", True),
    ("asl_dvs_dashboard", "8989", "tcp", "asl_dvs_dashboard", True),
    ("Cockpit", "9090", "tcp", "System management UI", True),
]


def _pi_exposed_port_set(zone: dict | None) -> set[str]:
    if zone is None:
        return set()
    return set(zone.get("ports", [])) | set(zone.get("services", []))


def build_ports_status(cfg: configparser.ConfigParser) -> dict:
    pi_mode = cfg.get("tunnels", "tunnel.pi.mode", fallback="")
    router_mode = cfg.get("tunnels", "tunnel.router.mode", fallback="")

    my_port = cfg.getint("server", "port", fallback=9997)
    reference = list(_PORTS_REFERENCE) + [("44helper", str(my_port), "tcp", "This dashboard", True)]

    services_status = build_services_status(cfg)
    running_labels = {
        item["label"] for group in services_status["groups"].values() for item in group if item["active"]
    }

    rows = []
    exposure_source = "none (no tunnel configured yet)"

    if pi_mode == "pi":
        zone = _firewalld_zone_info()
        exposure_source = f"{FIREWALLD_ZONE} firewalld zone (Pi-hosted)"
        exposed_set = _pi_exposed_port_set(zone)
        for label, port, proto, purpose, flag_public in reference:
            port_proto = f"{port}/{proto}"
            exposed = port_proto in exposed_set or label.lower() in exposed_set
            rows.append(_ports_row(label, port, proto, purpose, flag_public, exposed, label in running_labels))
    elif router_mode in ("router_single", "router_subnet"):
        raw_forwards = cfg.get("tunnels", "tunnel.router.forwards", fallback="")
        forwarded_ports = {e.split(":", 1)[1] for e in raw_forwards.split(",") if ":" in e}
        zone_open = router_mode == "router_subnet" and cfg.get("tunnels", "tunnel.router.zone_fixed", fallback="") == "true"
        exposure_source = (
            "Router forward table (Model B)" if router_mode == "router_single"
            else "Router wireguard zone — Masquerade off (Model C: whole subnet reachable, not just forwarded ports)"
        )
        for label, port, proto, purpose, flag_public in reference:
            port_proto = f"{port}/{proto}"
            exposed = zone_open or port_proto in forwarded_ports
            rows.append(_ports_row(label, port, proto, purpose, flag_public, exposed, label in running_labels))
    else:
        for label, port, proto, purpose, flag_public in reference:
            rows.append(_ports_row(label, port, proto, purpose, flag_public, False, label in running_labels))

    return {"rows": rows, "exposure_source": exposure_source, "checked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}


def _ports_row(label, port, proto, purpose, flag_public, exposed, running) -> dict:
    mismatch = exposed and flag_public
    return {
        "label": label, "port": port, "proto": proto, "purpose": purpose,
        "should_stay_private": flag_public, "exposed": exposed, "running": running,
        "mismatch": mismatch,
    }



def check_allstarlink_zone_guardrail() -> dict:
    try:
        r = subprocess.run(["firewall-cmd", "--zone=allstarlink", "--list-interfaces"],
                            capture_output=True, text=True, timeout=5)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return {"applicable": False, "wg0_attached": False}
    if r.returncode != 0:
        return {"applicable": False, "wg0_attached": False}
    interfaces = r.stdout.split()
    return {"applicable": True, "wg0_attached": "wg0" in interfaces}


def action_remove_zone_service(cfg: configparser.ConfigParser, service: str) -> dict:
    err = _require_root()
    if err:
        return err
    argv_pair = [
        ["firewall-cmd", "--permanent", f"--zone={FIREWALLD_ZONE}", f"--remove-service={service}"],
        ["firewall-cmd", "--reload"],
    ]
    results = [_run_argv(a) for a in argv_pair]
    ok = all(r["success"] for r in results)
    zone = _firewalld_zone_info()
    verified = zone is not None and service not in zone.get("services", [])
    return {"success": ok, "verified": verified, "output": "\n".join(r["output"] for r in results)}


def action_remove_zone_port(cfg: configparser.ConfigParser, port_proto: str) -> dict:
    err = _require_root()
    if err:
        return err
    if not _valid_port_proto(port_proto):
        return {"success": False, "verified": False, "output": f"Invalid port/proto '{port_proto}'"}
    argv_pair = [
        ["firewall-cmd", "--permanent", f"--zone={FIREWALLD_ZONE}", f"--remove-port={port_proto}"],
        ["firewall-cmd", "--reload"],
    ]
    results = [_run_argv(a) for a in argv_pair]
    ok = all(r["success"] for r in results)
    zone = _firewalld_zone_info()
    verified = zone is not None and port_proto not in zone.get("ports", [])
    return {"success": ok, "verified": verified, "output": "\n".join(r["output"] for r in results)}



def list_router_port_forwards(cfg: configparser.ConfigParser) -> list[dict] | None:
    base = _ssh_base_argv(cfg)
    if base is None:
        return None
    cmd = (
        "for r in $(uci show firewall 2>/dev/null | grep \"=redirect'\" | cut -d. -f2 | cut -d= -f1); do "
        "echo \"$r|$(uci -q get firewall.$r.name)|$(uci -q get firewall.$r.src_dport)|"
        "$(uci -q get firewall.$r.proto)|$(uci -q get firewall.$r.dest_ip)\"; done"
    )
    try:
        r = subprocess.run(base + [cmd], capture_output=True, text=True, timeout=15)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0:
        return None
    out = []
    for line in r.stdout.splitlines():
        parts = line.split("|")
        if len(parts) == 5:
            out.append({"id": parts[0], "name": parts[1], "port": parts[2], "proto": parts[3], "dest_ip": parts[4]})
    return out


_UCI_ID_RE = re.compile(r"^[A-Za-z0-9_]+$")


def action_remove_port_forward(cfg: configparser.ConfigParser, redirect_id: str) -> dict:
    if not _UCI_ID_RE.match(redirect_id):
        return {"success": False, "verified": False, "output": "Invalid redirect id."}
    base = _ssh_base_argv(cfg)
    if base is None:
        return {"success": False, "verified": False, "output": "Router access not configured/reachable."}
    cmd = f"uci delete firewall.{redirect_id} && uci commit firewall && /etc/init.d/firewall reload"
    try:
        r = subprocess.run(base + [cmd], capture_output=True, text=True, timeout=15)
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        return {"success": False, "verified": False, "output": f"ssh failed: {e}"}
    ok = r.returncode == 0
    return {"success": ok, "verified": ok, "output": (r.stdout + r.stderr).strip() or ("OK" if ok else "uci command failed")}


def build_firewall_status(cfg: configparser.ConfigParser) -> dict:
    pi_zone = _firewalld_zone_info()
    guardrail = check_allstarlink_zone_guardrail()
    router_forwards = list_router_port_forwards(cfg)
    return {
        "pi_zone": pi_zone,
        "allstarlink_guardrail": guardrail,
        "router_forwards": router_forwards,
        "router_configured": _ssh_base_argv(cfg) is not None,
        "checked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }




_CSS_BASE = """
/* ── :root variables — copied verbatim from asl_dvs_dashboard, design plan §10 ── */
:root {
  --bg: #0d1117;
  --surface: #161e2e;
  --surface2: #1e2a3f;
  --border: #2e4060;
  --border2: #3a5278;
  --amber: #ffd040;
  --amber-dim: #6b4800;
  --green: #00ffb0;
  --green-dim: #005538;
  --red: #ff3d5a;
  --red-dim: #6b0e20;
  --blue: #22d4ff;
  --blue-dim: #083a58;
  --purple: #d466ff;
  --purple-dim: #52087a;
  --teal: #00ffe5;
  --teal-dim: #004840;
  --orange: #ffaa22;
  --orange-dim: #703800;
  --text: #d0dff0;
  --text-bright: #f0f8ff;
  --muted: #4a6080;
  --mono: 'Courier New', Courier, monospace;
  --sans: Arial, Helvetica, sans-serif;
}

* { box-sizing: border-box; margin: 0; padding: 0; }

body {
  background: var(--bg);
  color: var(--text);
  font-family: var(--sans);
  min-height: 100vh;
  padding-bottom: 3rem;
}
"""

_CSS_LAYOUT = """
/* ── Header — same structure as ASL-DVS Node Control (§10) ── */
header {
  background: linear-gradient(90deg, #0f1a2e, #161e2e 50%, #0f1a2e);
  border-bottom: 2px solid var(--amber);
  padding: .45rem 1rem;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: .5rem;
  position: sticky;
  top: 0;
  z-index: 100;
  box-shadow: 0 2px 0 rgba(255,208,64,.25), 0 6px 30px rgba(0,0,0,.7);
}
.hdr-left { display: flex; flex-direction: column; min-width: 0; flex-shrink: 1; }
.hdr-right { display: flex; flex-direction: column; align-items: flex-end; flex-shrink: 0; white-space: nowrap; line-height: 1.4; }
.logo {
  font-family: var(--mono);
  font-size: 1.21rem;
  color: var(--amber);
  letter-spacing: .1em;
  text-shadow: 0 0 10px rgba(255,208,64,.9), 0 0 30px rgba(255,208,64,.5), 0 0 60px rgba(255,208,64,.2);
}
.logo-sub {
  font-size: .715rem;
  letter-spacing: .22em;
  text-transform: uppercase;
  color: var(--amber);
  margin-top: .1rem;
}
#hdr-uptime {
  font-family: var(--mono);
  font-size: .792rem;
  color: var(--amber);
  letter-spacing: .08em;
  text-shadow: 0 0 8px rgba(255,208,64,.5);
  white-space: nowrap;
}

/* ── Layout ── */
.wrap {
  max-width: 860px;
  margin: 0 auto;
  padding: 1rem;
  display: flex;
  flex-direction: column;
  gap: .55rem;
}
.wrap > div { min-width: 0; }

/* ── Tabs — same mechanism as source dashboard's mode tabs (§10) ── */
.tabs {
  display: flex;
  flex-wrap: wrap;
  overflow-x: auto;
  gap: .3rem .3rem;
  padding-bottom: 1px;
}
.tabs::-webkit-scrollbar { display: none; }
.tab-break { flex-basis: 100%; height: 0; }
.tab {
  font-family: var(--mono);
  font-size: .992rem;
  font-weight: bold;
  letter-spacing: .08em;
  text-transform: uppercase;
  padding: .52rem 1.1rem;
  border-radius: 5px 5px 0 0;
  border: 1px solid var(--border2);
  border-bottom: none;
  background: var(--surface2);
  color: #ffffff;
  cursor: pointer;
  transition: all .15s;
  user-select: none;
  flex-shrink: 0;
}
.tab:hover { color: var(--text-bright); border-color: #5a7898; background: #253550; }

/* Active-tab color assignment — design plan §10 table.
   Same --mc/--mc-rgb custom-property trick the source dashboard uses for
   its mode tabs (t-asl, t-echo, etc.), just mapped onto 44helper's own
   7 tabs instead of DV modes. */
.tab.active{color:var(--mc);border-color:var(--mc);background:rgba(var(--mc-rgb),.18);box-shadow:0 -2px 18px rgba(var(--mc-rgb),.35);text-shadow:0 0 14px rgba(var(--mc-rgb),1)}
.tab.t-overview{--mc:var(--amber);--mc-rgb:255,208,64}
.tab.t-router-install{--mc:var(--teal);--mc-rgb:0,255,229}
.tab.t-pi-install{--mc:var(--blue);--mc-rgb:34,212,255}
.tab.t-asl3{--mc:var(--amber);--mc-rgb:255,208,64}
.tab.t-services{--mc:var(--green);--mc-rgb:0,255,176}
.tab.t-ports{--mc:var(--purple);--mc-rgb:212,102,255}
.tab.t-firewall{--mc:var(--red);--mc-rgb:255,61,90}
.tab.t-actions-log{--mc:var(--orange);--mc-rgb:255,170,34}

.tab-panel {
  border: 1px solid var(--border2);
  border-radius: 0 5px 5px 5px;
  background: var(--surface);
  overflow-y: auto;
  box-shadow: 0 4px 20px rgba(0,0,0,.4);
  padding: 1.2rem;
  min-height: 240px;
}
.tab-panel.hidden { display: none; }
"""

_CSS_COMPONENTS = """
/* ── Stage-1 placeholder card ── */
.stub-card {
  border: 1px dashed var(--border2);
  border-radius: 6px;
  background: var(--surface2);
  padding: 1rem 1.2rem;
  font-family: var(--mono);
  font-size: .858rem;
  color: var(--muted);
  line-height: 1.6;
}
.stub-card .stub-title {
  color: var(--text-bright);
  font-size: 1rem;
  margin-bottom: .4rem;
  display: block;
}
.stub-card .stub-stage {
  color: var(--amber);
}

/* ── Footer / version tag ── */
.ver-tag {
  text-align: center;
  font-family: var(--mono);
  font-size: .715rem;
  color: var(--muted);
  padding-top: .8rem;
}

/* ── Overview tab (Stage 2) ── */
.ov-banner {
  border-radius: 6px;
  padding: .7rem 1rem;
  font-family: var(--mono);
  font-size: .858rem;
  margin-bottom: .9rem;
  border: 1px solid var(--border2);
}
.ov-banner.lvl-ok     { background: rgba(0,255,176,.10);  border-color: var(--green);  color: var(--green); }
.ov-banner.lvl-info   { background: var(--surface2);      border-color: var(--border2); color: var(--muted); }
.ov-banner.lvl-warn   { background: rgba(255,208,64,.12); border-color: var(--amber);  color: var(--amber); }
.ov-banner.lvl-danger { background: rgba(255,61,90,.14);  border-color: var(--red);    color: var(--red); }
.ov-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: .7rem;
  margin-bottom: .9rem;
}
@media (max-width: 640px) { .ov-grid { grid-template-columns: 1fr; } }
.ov-card {
  border: 1px solid var(--border2);
  border-radius: 6px;
  background: var(--surface2);
  padding: .8rem .95rem;
}
.ov-card .ov-card-title {
  font-family: var(--mono);
  font-size: .66rem;
  letter-spacing: .18em;
  text-transform: uppercase;
  color: #5a7898;
  margin-bottom: .4rem;
  display: block;
}
.ov-card .ov-card-body {
  font-family: var(--mono);
  font-size: .858rem;
  color: var(--text-bright);
  line-height: 1.6;
}
.ov-dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: .4rem; }
.ov-dot.ok     { background: var(--green); box-shadow: 0 0 6px var(--green); }
.ov-dot.warn   { background: var(--amber); box-shadow: 0 0 6px var(--amber); }
.ov-dot.danger { background: var(--red);   box-shadow: 0 0 6px var(--red); }
.ov-dot.info   { background: var(--muted); }
.ov-finding { padding: .2rem 0; }
.btn-recheck {
  font-family: var(--mono);
  font-size: .77rem;
  padding: .3rem .7rem;
  border-radius: 4px;
  border: 1px solid var(--teal);
  color: var(--teal);
  background: transparent;
  cursor: pointer;
}
.btn-recheck:hover { background: rgba(0,255,229,.12); }

/* ── Install-tab step cards (Stage 3+) ── */
.step-card {
  border: 1px solid var(--border2);
  border-radius: 6px;
  background: var(--surface2);
  padding: .8rem .95rem;
  margin-bottom: .6rem;
}
.step-head { display: flex; align-items: center; justify-content: space-between; gap: .6rem; flex-wrap: wrap; }
.step-title { font-family: var(--mono); font-size: .924rem; color: var(--text-bright); }
.step-num { color: var(--blue); margin-right: .4rem; }
.step-pill {
  font-family: var(--mono);
  font-size: .66rem;
  letter-spacing: .1em;
  text-transform: uppercase;
  padding: .18rem .55rem;
  border-radius: 999px;
  border: 1px solid var(--border2);
}
.step-pill.not_started { color: var(--muted); border-color: var(--border2); }
.step-pill.attempted_unconfirmed { color: var(--amber); border-color: var(--amber); background: rgba(255,208,64,.10); }
.step-pill.done { color: var(--green); border-color: var(--green); background: rgba(0,255,176,.10); }
.step-pill.danger { color: var(--red); border-color: var(--red); background: rgba(255,61,90,.10); }
.step-body { font-family: var(--mono); font-size: .8rem; color: var(--muted); margin-top: .5rem; line-height: 1.6; }
.step-actions { margin-top: .55rem; display: flex; gap: .5rem; flex-wrap: wrap; align-items: center; }
.btn-run {
  font-family: var(--mono);
  font-size: .77rem;
  padding: .32rem .8rem;
  border-radius: 4px;
  border: 1px solid var(--blue);
  color: var(--blue);
  background: transparent;
  cursor: pointer;
}
.btn-run:hover { background: rgba(34,212,255,.12); }
.btn-run:disabled { opacity: .4; cursor: not-allowed; }
.cmd-preview {
  font-family: var(--mono);
  font-size: .715rem;
  color: var(--amber);
  background: #0a1020;
  border: 1px solid var(--border2);
  border-radius: 4px;
  padding: .4rem .6rem;
  margin-top: .4rem;
  white-space: pre-wrap;
  word-break: break-all;
}
.step-warn {
  border: 1px solid var(--amber);
  background: rgba(255,208,64,.10);
  color: var(--amber);
  border-radius: 4px;
  padding: .5rem .7rem;
  font-family: var(--mono);
  font-size: .77rem;
  margin-top: .5rem;
}
.checklist label { display: block; font-family: var(--mono); font-size: .84rem; margin: .25rem 0; color: var(--text); }
textarea.wg-paste {
  width: 100%;
  min-height: 140px;
  background: #0a1020;
  border: 1px solid var(--border2);
  border-radius: 4px;
  color: var(--text-bright);
  font-family: var(--mono);
  font-size: .77rem;
  padding: .5rem;
  margin-top: .4rem;
}
"""

_CSS_NODES = """
/* ── Nodes tab (Stage 7) — collapsible per-card editor, same pattern as
   sysmon's stfu/m17/zello editors: max-height transition, one shared
   textarea, Save/Copy/Close bar. ── */
.nd-card-row { display: flex; align-items: center; justify-content: space-between; gap: .5rem; flex-wrap: wrap; margin: .5rem 0 .25rem; }
.nd-editor-wrap { overflow: hidden; max-height: 0; transition: max-height .3s ease; }
.nd-editor-wrap.open { max-height: 220px; margin-bottom: .6rem; }
.nd-editor-wrap textarea {
  width: 100%; box-sizing: border-box; min-height: 54px; resize: vertical;
  background: #0a1020; color: var(--text-bright); border: 1px solid var(--border2);
  border-radius: 4px; font-family: var(--mono); font-size: .8rem; padding: .4rem;
}
.nd-editor-bar { display: flex; align-items: center; gap: .4rem; margin-top: .4rem; flex-wrap: wrap; }
.nd-editor-status { font-family: var(--mono); font-size: .66rem; color: var(--muted); margin-left: auto; }
.nd-link-btn {
  font-family: var(--mono); font-size: .72rem; padding: .22rem .6rem; border-radius: 4px;
  border: 1px solid var(--teal); color: var(--teal); background: transparent; cursor: pointer;
}
.nd-link-btn:hover { background: rgba(0,255,229,.12); }
.nd-link-btn.nd-link-btn-dim { opacity: .45; border-color: var(--muted); color: var(--muted); }
.nd-link-btn.nd-link-btn-dim:hover { background: transparent; }
"""

_CSS_FIREWALL = """
/* ── Services / Ports / Firewall tabs (Stage 7) ── */
.svc-group-title {
  font-family: var(--mono);
  font-size: .77rem;
  letter-spacing: .12em;
  text-transform: uppercase;
  color: #5a7898;
  margin: .8rem 0 .3rem;
}
.svc-row { display: flex; align-items: center; gap: .5rem; padding: .2rem 0; font-family: var(--mono); font-size: .84rem; }
.svc-row.flagged { color: var(--amber); }
#ports-table th, #ports-table td { text-align: left; padding: .3rem .5rem; border-bottom: 1px solid var(--border2); }
#ports-table th { color: #5a7898; font-size: .66rem; letter-spacing: .1em; text-transform: uppercase; }
#ports-table tr.mismatch { background: rgba(255,61,90,.12); }
#ports-table tr.mismatch td:first-child { border-left: 3px solid var(--red); }
"""

_CSS_LOG = """
/* ── Actions Log tab (Stage 8) ── */
.log-line { padding: 1px 0; }
.log-line.run { color: var(--blue); }
.log-line.ok { color: var(--green); }
.log-line.fail { color: var(--red); }
.log-line.warn { color: var(--amber); }
.log-line.plain { color: var(--muted); }
.note-item { padding: .2rem 0; font-family: var(--mono); font-size: .84rem; }
.note-item a { color: var(--teal); cursor: pointer; text-decoration: underline; }
"""

_CSS_ASL3 = """
/* ── ASL3 tab (Stage 1) — distro dropdown, editable-command step
   cards, Purge toggle, Custom-mode transcript. Reuses .step-card /
   .step-pill / .btn-run / .step-actions / .step-warn as-is; only new
   rules are the editable command input and the terminal-style output
   pane. ── */
.asl3-topbar { display: flex; align-items: center; gap: .7rem; flex-wrap: wrap; margin-bottom: .8rem; }
.asl3-topbar select {
  font-family: var(--mono); font-size: .84rem; background: #0a1020; color: var(--text-bright);
  border: 1px solid var(--border2); border-radius: 4px; padding: .3rem .5rem;
}
.btn-purge {
  font-family: var(--mono); font-size: .77rem; padding: .32rem .8rem; border-radius: 4px;
  border: 1px solid var(--red); color: var(--red); background: transparent; cursor: pointer;
}
.btn-purge:hover { background: rgba(255,61,90,.12); }
.asl3-cmd-input {
  width: 100%; box-sizing: border-box; font-family: var(--mono); font-size: .77rem;
  background: #0a1020; color: var(--amber); border: 1px solid var(--border2);
  border-radius: 4px; padding: .4rem .6rem; margin-top: .4rem;
}
.asl3-console {
  font-family: var(--mono); font-size: .74rem; color: #b8e6c8; background: #05080f;
  border: 1px solid var(--border2); border-radius: 4px; padding: .5rem .6rem;
  margin-top: .4rem; white-space: pre-wrap; word-break: break-all;
  max-height: 220px; overflow-y: auto; display: none;
}
.asl3-console.shown { display: block; }
.asl3-console.fail { color: #ffb0b8; }
#asl3-custom-transcript {
  font-family: var(--mono); font-size: .74rem; color: #b8e6c8; background: #05080f;
  border: 1px solid var(--border2); border-radius: 4px; padding: .6rem .7rem;
  margin-top: .6rem; white-space: pre-wrap; word-break: break-all;
  max-height: 320px; overflow-y: auto;
}
"""

_CSS = (
    _CSS_BASE
    + _CSS_LAYOUT
    + _CSS_COMPONENTS
    + _CSS_NODES
    + _CSS_FIREWALL
    + _CSS_LOG
    + _CSS_ASL3
)

TABS: list[tuple[str, str, str, str]] = [
    ("overview", "Overview", "t-overview", "Stage 2"),
    ("router_install", "Router Install", "t-router-install", "Steps 1-2a: Stage 4 — Steps 3-11 (Model C): Stage 5 (done) — Model B: Stage 6"),
    ("pi_install", "Pi Install", "t-pi-install", "Stage 3"),
    ("nodes", "Nodes", "t-nodes", "Phase 1 complete (Stages 1-8) — Phase 2 (link-button reachability probe) pending"),
    ("asl3", "ASL3", "t-asl3", "Stage 1 (engine + real Bookworm/Trixie install steps) — purge lists are placeholders, DVswitch/SVXlink to follow"),
    ("services", "Services", "t-services", "Stage 7 (done)"),
    ("ports", "Ports", "t-ports", "Stage 7 (done)"),
    ("firewall", "Firewall", "t-firewall", "Stage 7 (done)"),
    ("actions_log", "Actions Log", "t-actions-log", "Stage 8 (done)"),
]

RPT_CONF_RESERVED_STANZAS: frozenset[str] = frozenset({
    "general",
    "nodes",
    "extnodes",
    "topdir",
    "functions",
    "telemetry",
    "morse",
    "os_1",
    "macro",
    "assignidx",
})


def _parse_asterisk_conf_stanzas(text: str) -> dict:
    stanzas: dict = {}
    current = ""
    stanzas[current] = {"line_no": 0, "entries": []}

    for i, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith(";"):
            continue
        if line.startswith("[") and "]" in line:
            name = line[1:line.index("]")].strip()
            stanzas[name] = {"line_no": i, "entries": []}
            current = name
            continue
        if "=" in line:
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip()
            if ";" in val:
                val = val.split(";", 1)[0].strip()
            stanzas[current]["entries"].append({
                "line_no": i, "raw": raw_line, "key": key, "val": val,
            })

    return stanzas


def _read_conf_stanzas(path: str) -> dict | None:
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r") as f:
            text = f.read()
    except OSError:
        return {"_unreadable": True}
    return _parse_asterisk_conf_stanzas(text)


def parse_iax_conf(cfg: configparser.ConfigParser) -> dict:
    path = cfg.get("nodes", "iax_conf_path", fallback="/etc/asterisk/iax.conf")
    stanzas = _read_conf_stanzas(path)

    result = {
        "path": path,
        "exists": stanzas is not None,
        "unreadable": bool(stanzas and stanzas.get("_unreadable")),
        "bindport": "4569",
        "bindport_explicit": False,
        "bindport_line_no": None,
        "bindport_raw_line": None,
    }

    if not stanzas or result["unreadable"]:
        return result

    for entry in stanzas.get("general", {}).get("entries", []):
        if entry["key"].lower() == "bindport":
            result["bindport"] = entry["val"]
            result["bindport_explicit"] = True
            result["bindport_line_no"] = entry["line_no"]
            result["bindport_raw_line"] = entry["raw"]

    return result


def parse_rpt_conf(cfg: configparser.ConfigParser) -> dict:
    path = cfg.get("nodes", "rpt_conf_path", fallback="/etc/asterisk/rpt.conf")
    stanzas = _read_conf_stanzas(path)

    result = {
        "path": path,
        "exists": stanzas is not None,
        "unreadable": bool(stanzas and stanzas.get("_unreadable")),
        "stanzas": {},
        "nodes_map": {},
    }

    if not stanzas or result["unreadable"]:
        return result

    result["stanzas"] = {k: v for k, v in stanzas.items() if k != ""}

    for entry in stanzas.get("nodes", {}).get("entries", []):
        result["nodes_map"][entry["key"]] = {
            "line_no": entry["line_no"],
            "raw": entry["raw"],
            "target": entry["val"],
        }

    return result


def parse_extensions_conf(cfg: configparser.ConfigParser) -> dict:
    path = cfg.get("nodes", "extensions_conf_path", fallback="/etc/asterisk/extensions.conf")

    result = {
        "path": path,
        "exists": os.path.exists(path),
        "unreadable": False,
        "node": None,
        "node_line_no": None,
        "node_raw_line": None,
    }

    if not result["exists"]:
        return result

    try:
        with open(path, "r") as f:
            text = f.read()
    except OSError:
        result["unreadable"] = True
        return result

    for i, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith(";") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        if key.strip().upper() == "NODE":
            result["node"] = val.split(";", 1)[0].strip()
            result["node_line_no"] = i
            result["node_raw_line"] = raw_line
            break

    return result


def parse_allmon3_ini(cfg: configparser.ConfigParser) -> dict:
    path = cfg.get("nodes", "allmon3_ini_path", fallback="/etc/allmon3/allmon3.ini")

    result = {
        "path": path,
        "exists": os.path.exists(path),
        "unreadable": False,
        "nodes": {},
    }

    if not result["exists"]:
        return result

    parser = configparser.ConfigParser()
    try:
        read_ok = parser.read(path)
    except (OSError, configparser.Error):
        result["unreadable"] = True
        return result

    if not read_ok:
        result["unreadable"] = True
        return result

    for section in parser.sections():
        result["nodes"][section] = dict(parser.items(section))

    return result


def build_nodes_parse_snapshot(cfg: configparser.ConfigParser) -> dict:
    return {
        "iax_conf": parse_iax_conf(cfg),
        "rpt_conf": parse_rpt_conf(cfg),
        "extensions_conf": parse_extensions_conf(cfg),
        "allmon3_ini": parse_allmon3_ini(cfg),
    }



_RPT_NODE_TARGET_RE = re.compile(
    r"^radio@(?P<host>[^:/]+)(?::(?P<port>\d+))?/(?P<node>\d+)\s*,?\s*(?P<flags>.*)$"
)


def _parse_rpt_node_target(target: str) -> dict:
    m = _RPT_NODE_TARGET_RE.match(target.strip())
    if not m:
        return {"host": None, "port": None, "flags": ""}
    return {
        "host": m.group("host"),
        "port": m.group("port"),
        "flags": m.group("flags").strip(),
    }


def parse_stored_peers(cfg: configparser.ConfigParser) -> dict:
    raw = cfg.get("nodes", "peers", fallback="")
    out: dict = {}
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 2 or not parts[0].isdigit():
            continue
        node = parts[0]
        out[node] = {
            "ip": parts[1] if len(parts) >= 2 else "",
            "port": parts[2] if len(parts) >= 3 and parts[2] else None,
            "label": parts[3] if len(parts) >= 4 else "",
        }
    return out


def parse_peer_links(cfg: configparser.ConfigParser) -> dict:
    raw = cfg.get("nodes", "peer_links", fallback="")
    out: dict = {}
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split("|", 1)]
        if len(parts) != 2 or not parts[0].isdigit() or not parts[1]:
            continue
        out[parts[0]] = parts[1]
    return out


def _local_node_numbers(rpt_conf: dict) -> list[str]:
    names = rpt_conf.get("stanzas", {}).keys()
    return sorted(
        (n for n in names if n.isdigit() and n not in RPT_CONF_RESERVED_STANZAS),
        key=int,
    )


def build_local_node_cards(snapshot: dict) -> list[dict]:
    rpt_conf = snapshot["rpt_conf"]
    ext_conf = snapshot["extensions_conf"]
    local_nodes = _local_node_numbers(rpt_conf)

    cards = []
    for node in local_nodes:
        stanza = rpt_conf["stanzas"].get(node, {})
        rxchannel = None
        for entry in stanza.get("entries", []):
            if entry["key"].lower() == "rxchannel":
                rxchannel = entry["val"]
                break

        own_line = rpt_conf["nodes_map"].get(node)
        own_target = _parse_rpt_node_target(own_line["target"]) if own_line else None

        cards.append({
            "node": node,
            "stanza_line_no": stanza.get("line_no"),
            "rxchannel": rxchannel,
            "own_nodes_line": own_line,
            "own_target_parsed": own_target,
            "extensions_node": ext_conf.get("node"),
            "extensions_match": (ext_conf.get("node") == node) if ext_conf.get("node") else None,
        })
    return cards


def build_peer_node_cards(cfg: configparser.ConfigParser, snapshot: dict) -> list[dict]:
    rpt_conf = snapshot["rpt_conf"]
    local_nodes = set(_local_node_numbers(rpt_conf))
    stored_peers = parse_stored_peers(cfg)
    peer_links = parse_peer_links(cfg)

    auto_peer_nodes = {
        node: entry for node, entry in rpt_conf["nodes_map"].items()
        if node not in local_nodes
    }

    all_peer_nodes = sorted(
        set(auto_peer_nodes) | set(stored_peers) | set(peer_links), key=int
    )

    cards = []
    for node in all_peer_nodes:
        auto = auto_peer_nodes.get(node)
        auto_target = _parse_rpt_node_target(auto["target"]) if auto else None
        stored = stored_peers.get(node)

        cards.append({
            "node": node,
            "wired": auto is not None,
            "source": ("auto+stored" if auto and stored
                       else "auto" if auto else "stored"),
            "ip": (auto_target["host"] if auto_target and auto_target["host"]
                  else stored["ip"] if stored else None),
            "port": (auto_target["port"] if auto_target and auto_target["port"]
                     else stored["port"] if stored else None),
            "label": stored["label"] if stored else "",
            "auto_nodes_line": auto,
            "helper_url": peer_links.get(node, ""),
        })
    return cards



def probe_peer_helper(url: str, timeout: float = 1.5) -> dict:
    probe_url = url.strip().rstrip("/") + "/api/version"
    if not (probe_url.startswith("http://") or probe_url.startswith("https://")):
        probe_url = "http://" + probe_url

    try:
        req = urllib.request.Request(probe_url, headers={"User-Agent": "44helper-nodes-probe"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
        return {"reachable": True, "error": None, "remote_version": data.get("version")}
    except (urllib.error.URLError, OSError, TimeoutError, json.JSONDecodeError, ValueError) as e:
        return {"reachable": False, "error": str(e)[:120], "remote_version": None}


def fetch_peer_node_status(url: str, timeout: float = 2.5) -> dict | None:
    status_url = url.strip().rstrip("/") + "/api/nodes/status"
    if not (status_url.startswith("http://") or status_url.startswith("https://")):
        status_url = "http://" + status_url

    try:
        req = urllib.request.Request(status_url, headers={"User-Agent": "44helper-nodes-probe"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", errors="replace"))
    except (urllib.error.URLError, OSError, TimeoutError, json.JSONDecodeError, ValueError):
        return None


def probe_all_peer_helpers(peer_cards: list[dict], timeout: float = 1.5, fetch_remote_status: bool = True) -> None:
    for card in peer_cards:
        if not card["helper_url"]:
            card["helper_probe"] = None
            card["helper_remote_status"] = None
            continue
        probe = probe_peer_helper(card["helper_url"], timeout)
        card["helper_probe"] = probe
        if fetch_remote_status and probe["reachable"]:
            card["helper_remote_status"] = fetch_peer_node_status(card["helper_url"])
        else:
            card["helper_remote_status"] = None


def build_nodes_guardrails(box: dict, local_cards: list[dict], peer_cards: list[dict]) -> list[dict]:
    findings: list[dict] = []
    restart_note = "Restart Asterisk for the change to take effect (sudo systemctl restart asterisk)."

    bindport = box["bindport"]
    bindport_num = int(bindport) if bindport.isdigit() else None
    in_range = (bindport_num is not None
                and box["bindport_range_min"] <= bindport_num <= box["bindport_range_max"])
    rmin, rmax = box["bindport_range_min"], box["bindport_range_max"]

    if bindport_num is None:
        findings.append({
            "level": "warn", "scope": "box",
            "msg": f"iax.conf bindport ('{bindport}') isn't a plain number — couldn't range-check it.",
            "fix": (
                f"1. Open the This Box card's Edit bindport editor above.\n"
                f"2. Replace the line with a plain numeric value, e.g.: bindport = {rmin}\n"
                f"3. Save (a backup of iax.conf is made automatically).\n"
                f"4. {restart_note}"
            ),
        })
    elif box["bindport_explicit"] and not in_range:
        findings.append({
            "level": "warn", "scope": "box",
            "msg": (
                f"bindport {bindport_num} is outside the ASL3-recommended "
                f"{rmin}-{rmax} range for a secondary node sharing a NAT."
            ),
            "fix": (
                f"1. Pick an unused port between {rmin} and {rmax} (check your other boxes/peers first "
                f"so you don't pick one already in use).\n"
                f"2. Open the This Box card's Edit bindport editor above and change the value, e.g.: bindport = {rmin}\n"
                f"3. Save.\n"
                f"4. Update this box's port-forward on your router to point the new port at this box's LAN IP.\n"
                f"5. If this node is registered on the AllStarLink Portal, update its Server settings to match.\n"
                f"6. {restart_note}"
            ),
        })
    elif not box["bindport_explicit"] and peer_cards:
        findings.append({
            "level": "warn", "scope": "box",
            "msg": (
                f"iax.conf has no explicit bindport (using the default {bindport}) "
                "while peer nodes are configured — if this box shares a public IP "
                f"with any of them, give it a distinct port in the {rmin}-{rmax} range."
            ),
            "fix": (
                f"1. Confirm whether this box shares a router/public IP with any configured peer "
                f"(if you're not sure, check with whoever set up the peer box).\n"
                f"2. If it does, pick an unused port between {rmin} and {rmax}.\n"
                f"3. Open the This Box card's Edit bindport editor above and set it explicitly, e.g.: bindport = {rmin}\n"
                f"4. Save.\n"
                f"5. Update this box's port-forward on your router to point the new port at this box's LAN IP.\n"
                f"6. {restart_note}"
            ),
        })
    else:
        findings.append({"level": "ok", "scope": "box", "msg": f"bindport {bindport_num} OK."})

    for card in local_cards:
        node = card["node"]
        if card["own_nodes_line"] is None:
            findings.append({
                "level": "danger", "scope": f"local:{node}",
                "msg": f"Node {node} has a channel stanza but no matching [nodes] entry — it won't be dialable.",
                "fix": (
                    f"1. Open the Local Nodes card and click Edit next to node {node}.\n"
                    f"2. The editor will pre-fill a suggested line: {node} = radio@127.0.0.1/{node},NONE\n"
                    f"3. Save (a backup of rpt.conf is made automatically).\n"
                    f"4. {restart_note}"
                ),
            })
        elif card["own_target_parsed"] is None:
            findings.append({
                "level": "danger", "scope": f"local:{node}",
                "msg": f"Node {node}'s [nodes] line doesn't match the expected radio@host/node format.",
                "fix": (
                    f"1. Open the Local Nodes card and click Edit next to node {node}.\n"
                    f"2. Replace the line with: {node} = radio@127.0.0.1/{node},NONE (adjust the trailing "
                    f"flags after the comma if your setup needs something other than NONE).\n"
                    f"3. Save.\n"
                    f"4. {restart_note}"
                ),
            })
        elif card["own_target_parsed"]["host"] != "127.0.0.1":
            findings.append({
                "level": "danger", "scope": f"local:{node}",
                "msg": (
                    f"Node {node} is hosted on this box but its [nodes] entry points at "
                    f"{card['own_target_parsed']['host']} instead of 127.0.0.1."
                ),
                "fix": (
                    f"1. This is usually a copy/paste mistake from a peer's line. Open the Local Nodes "
                    f"card and click Edit next to node {node}.\n"
                    f"2. Change the host portion to 127.0.0.1, e.g.: {node} = radio@127.0.0.1/{node},NONE\n"
                    f"3. Save.\n"
                    f"4. {restart_note}"
                ),
            })
        else:
            findings.append({"level": "ok", "scope": f"local:{node}", "msg": f"Node {node} wired correctly."})

        if card["extensions_match"] is False and len(local_cards) == 1:
            findings.append({
                "level": "danger", "scope": f"local:{node}",
                "msg": f"extensions.conf NODE={card['extensions_node']} doesn't match this box's only local node ({node}).",
                "fix": (
                    f"1. This tab doesn't edit extensions.conf yet — open /etc/asterisk/extensions.conf "
                    f"directly (SSH in, or use another editor).\n"
                    f"2. Find the line 'NODE = {card['extensions_node']}' and change it to: NODE = {node}\n"
                    f"3. Save the file.\n"
                    f"4. {restart_note}"
                ),
            })

    if not local_cards:
        findings.append({"level": "info", "scope": "box", "msg": "No locally-hosted nodes detected in rpt.conf."})
    elif len(local_cards) > 1 and any(c["extensions_node"] for c in local_cards):
        findings.append({
            "level": "info", "scope": "box",
            "msg": (
                f"extensions.conf NODE={local_cards[0]['extensions_node']} — multiple local nodes are "
                "hosted here; verify this is the intended primary node."
            ),
        })
    elif local_cards and local_cards[0]["extensions_node"] is None:
        findings.append({
            "level": "warn", "scope": "box",
            "msg": "extensions.conf has no NODE= declaration — dialplan may not resolve correctly.",
            "fix": (
                f"1. This tab doesn't edit extensions.conf yet — open /etc/asterisk/extensions.conf "
                f"directly (SSH in, or use another editor).\n"
                f"2. Add a line near the top: NODE = {local_cards[0]['node']} "
                f"(use your primary node's number).\n"
                f"3. Save the file.\n"
                f"4. {restart_note}"
            ),
        })

    for card in peer_cards:
        node = card["node"]
        if not card["wired"]:
            suggested_ip = card["ip"] or "<peer's LAN IP>"
            suggested_port = f":{card['port']}" if card["port"] else ""
            findings.append({
                "level": "warn", "scope": f"peer:{node}",
                "msg": f"Peer {node} is configured but has no [nodes] entry yet — not wired in.",
                "fix": (
                    f"1. Open the Peer Nodes card and click Edit next to peer {node}.\n"
                    f"2. The editor will pre-fill a suggested line: "
                    f"{node} = radio@{suggested_ip}{suggested_port}/{node},NONE — adjust the IP/port if needed.\n"
                    f"3. Save (a backup of rpt.conf is made automatically).\n"
                    f"4. Confirm the peer box itself has a matching [nodes] line pointing back at this box "
                    f"(if it's also running 44helper, check its own Nodes tab).\n"
                    f"5. Make sure any needed router port-forwards are in place on both sides.\n"
                    f"6. {restart_note}"
                ),
            })
        elif card["auto_nodes_line"] and _parse_rpt_node_target(card["auto_nodes_line"]["target"])["host"] is None:
            findings.append({
                "level": "danger", "scope": f"peer:{node}",
                "msg": f"Peer {node}'s [nodes] line doesn't match the expected radio@host[:port]/node format.",
                "fix": (
                    f"1. Open the Peer Nodes card and click Edit next to peer {node}.\n"
                    f"2. Replace the line with: {node} = radio@<peer-ip>[:<peer-port>]/{node},NONE "
                    f"(fill in the peer's real LAN IP and port).\n"
                    f"3. Save.\n"
                    f"4. {restart_note}"
                ),
            })
        else:
            findings.append({"level": "ok", "scope": f"peer:{node}", "msg": f"Peer {node} wired."})

        if card["wired"] and card["port"] is None:
            findings.append({
                "level": "warn", "scope": f"peer:{node}",
                "msg": (
                    f"Peer {node}'s neighbor line has no explicit :port — this only works if "
                    "the peer's own bindport is the IAX default (4569)."
                ),
                "fix": (
                    f"1. Confirm peer {node}'s actual iax.conf bindport (check its own 44helper Nodes tab "
                    f"if it has one, or ask whoever administers it).\n"
                    f"2. If it isn't 4569, open the Peer Nodes card and click Edit next to peer {node}.\n"
                    f"3. Add the port explicitly, e.g.: {node} = radio@<peer-ip>:<peer-port>/{node},NONE\n"
                    f"4. Save.\n"
                    f"5. {restart_note}"
                ),
            })

        remote = card.get("helper_remote_status")
        remote_bindport = None
        if remote:
            rb = remote.get("box", {}).get("bindport", "")
            if rb.isdigit():
                remote_bindport = int(rb)

        if remote_bindport is not None and bindport_num is not None and remote_bindport == bindport_num:
            findings.append({
                "level": "danger", "scope": f"peer:{node}",
                "msg": (
                    f"CONFIRMED: peer {node} reports its own bindport as {remote_bindport}, "
                    f"matching this box's bindport ({bindport_num}) — live collision, not just "
                    "a stored assumption."
                ),
                "fix": (
                    f"1. Only one of the two boxes can keep bindport {bindport_num} — pick which one changes.\n"
                    f"2. On whichever box changes: open its This Box card's Edit bindport editor and set a "
                    f"distinct value between {rmin} and {rmax} (this box's Edit bindport button is above, "
                    f"in the This Box card, if this box is the one changing).\n"
                    f"3. Save.\n"
                    f"4. Update that box's router port-forward to match the new port.\n"
                    f"5. If either node is registered on the AllStarLink Portal, update its Server settings.\n"
                    f"6. {restart_note} (on whichever box you changed)\n"
                    f"7. Click Re-check here to confirm the collision is gone."
                ),
            })
        elif remote_bindport is not None:
            pass
        elif card["port"] and bindport_num is not None and str(card["port"]) == str(bindport_num):
            findings.append({
                "level": "danger", "scope": f"peer:{node}",
                "msg": f"This box's bindport ({bindport_num}) matches peer {node}'s stored port — collision on a shared NAT.",
                "fix": (
                    f"1. This is based on the port you typed in for peer {node}, not a confirmed live check.\n"
                    f"2. If this peer has its own 44helper reachable, add its URL in the Peer Nodes form "
                    f"and click Re-check for a confirmed answer instead of relying on the typed value.\n"
                    f"3. If accurate: pick which box changes, then open its This Box card's Edit bindport "
                    f"editor and set a distinct value between {rmin} and {rmax}.\n"
                    f"4. Save.\n"
                    f"5. Update that box's router port-forward to match.\n"
                    f"6. {restart_note} (on whichever box you changed)"
                ),
            })

        if remote is not None:
            findings.append({
                "level": "info", "scope": f"peer:{node}",
                "msg": f"Peer {node} reports its own status as '{remote.get('guardrail_level', 'unknown')}'.",
            })

    seen_ports: dict[str, str] = {}
    for card in peer_cards:
        if not card["port"]:
            continue
        prior = seen_ports.get(str(card["port"]))
        if prior:
            findings.append({
                "level": "danger", "scope": "peers",
                "msg": f"Peers {prior} and {card['node']} are both configured with port {card['port']} — pick distinct ports.",
                "fix": (
                    f"1. Your router can only forward this port to one LAN device — one of these two peers "
                    f"needs a different port.\n"
                    f"2. Pick which peer changes (peer {prior} or peer {card['node']}), then edit that "
                    f"peer's stored port in the Peer Nodes form here (Add/Update Peer with the same node "
                    f"number and a new port).\n"
                    f"3. Make sure that peer's own iax.conf bindport actually matches the new port — this "
                    f"only fixes the record here, not the peer box itself.\n"
                    f"4. Update that peer box's router port-forward to match.\n"
                    f"5. Restart Asterisk on that peer box for its own bindport change to take effect.\n"
                    f"6. If the peer's own [nodes] line also needs the new port, click Edit next to it "
                    f"here and update the :port suffix, then Save."
                ),
            })
        else:
            seen_ports[str(card["port"])] = card["node"]

    return findings


def build_nodes_tab_data(cfg: configparser.ConfigParser, probe_peers: bool = False) -> dict:
    snapshot = build_nodes_parse_snapshot(cfg)
    iax_conf = snapshot["iax_conf"]

    box = {
        "bindport": iax_conf["bindport"],
        "bindport_explicit": iax_conf["bindport_explicit"],
        "bindport_range_min": cfg.getint("nodes", "bindport_range_min", fallback=4560),
        "bindport_range_max": cfg.getint("nodes", "bindport_range_max", fallback=4580),
    }
    local_cards = build_local_node_cards(snapshot)
    peer_cards = build_peer_node_cards(cfg, snapshot)
    if probe_peers:
        probe_all_peer_helpers(peer_cards)
    else:
        for card in peer_cards:
            card["helper_probe"] = None
            card["helper_remote_status"] = None
    guardrails = build_nodes_guardrails(box, local_cards, peer_cards)

    return {
        "box": box,
        "local_nodes": local_cards,
        "peer_nodes": peer_cards,
        "guardrails": guardrails,
        "guardrail_level": _self_check_worst_level(guardrails),
        "snapshot": snapshot,
    }



def _serialize_stored_peers(peers: dict) -> str:
    lines = []
    for node in sorted(peers, key=int):
        p = peers[node]
        lines.append(f"{node}|{p.get('ip', '')}|{p.get('port') or ''}|{p.get('label', '')}")
    return "\n".join(lines)


def _serialize_peer_links(links: dict) -> str:
    return "\n".join(f"{node}|{url}" for node, url in sorted(links.items(), key=lambda kv: int(kv[0])))


def action_upsert_peer(cfg: configparser.ConfigParser, node: str, ip: str, port: str, label: str, helper_url: str = "") -> dict:
    if not node.isdigit():
        return {"success": False, "output": f"Node number must be numeric (got '{node}')"}
    if not ip or any(c in ip for c in " '\"$();&|"):
        return {"success": False, "output": f"Invalid IP/host '{ip}'"}
    if port and not _valid_port(port):
        return {"success": False, "output": f"Invalid port '{port}'"}
    if "|" in label:
        return {"success": False, "output": "Label can't contain '|'"}
    if "|" in helper_url:
        return {"success": False, "output": "Helper URL can't contain '|'"}

    peers = parse_stored_peers(cfg)
    peers[node] = {"ip": ip, "port": port or None, "label": label}
    if "nodes" not in cfg:
        cfg["nodes"] = {}
    cfg["nodes"]["peers"] = _serialize_stored_peers(peers)

    links = parse_peer_links(cfg)
    if helper_url:
        links[node] = helper_url
    elif node in links:
        del links[node]
    cfg["nodes"]["peer_links"] = _serialize_peer_links(links)

    save_config(cfg)
    log(f"Nodes tab: peer {node} ({ip}{':' + port if port else ''}) saved")
    return {"success": True, "output": f"Peer {node} saved."}


def action_remove_peer(cfg: configparser.ConfigParser, node: str) -> dict:
    peers = parse_stored_peers(cfg)
    if node not in peers:
        return {"success": False, "output": f"Peer {node} not found in stored peers."}
    del peers[node]
    if "nodes" not in cfg:
        cfg["nodes"] = {}
    cfg["nodes"]["peers"] = _serialize_stored_peers(peers)

    links = parse_peer_links(cfg)
    if node in links:
        del links[node]
        cfg["nodes"]["peer_links"] = _serialize_peer_links(links)

    save_config(cfg)
    log(f"Nodes tab: peer {node} removed")
    return {"success": True, "output": f"Peer {node} removed."}


def build_node_snippet(cfg: configparser.ConfigParser, scope: str) -> dict:
    data = build_nodes_tab_data(cfg)
    rpt_path = data["snapshot"]["rpt_conf"]["path"]

    if scope == "box":
        iax = data["snapshot"]["iax_conf"]
        if iax["bindport_explicit"]:
            text = iax["bindport_raw_line"]
        else:
            text = f"bindport = {iax['bindport']}  ; explicit port recommended once peers are configured"
        return {"scope": "box", "path": iax["path"], "line_no": iax["bindport_line_no"], "text": text}

    if scope.startswith("local:"):
        node = scope.split(":", 1)[1]
        card = next((c for c in data["local_nodes"] if c["node"] == node), None)
        if card is None:
            return {"error": f"Local node {node} not found."}
        if card["own_nodes_line"]:
            return {"scope": scope, "path": rpt_path,
                     "line_no": card["own_nodes_line"]["line_no"],
                     "text": card["own_nodes_line"]["raw"]}
        return {"scope": scope, "path": rpt_path, "line_no": None,
                 "text": f"{node} = radio@127.0.0.1/{node},NONE"}

    if scope.startswith("peer:"):
        node = scope.split(":", 1)[1]
        card = next((c for c in data["peer_nodes"] if c["node"] == node), None)
        if card is None:
            return {"error": f"Peer {node} not found."}
        if card["auto_nodes_line"]:
            return {"scope": scope, "path": rpt_path,
                     "line_no": card["auto_nodes_line"]["line_no"],
                     "text": card["auto_nodes_line"]["raw"]}
        ip = card["ip"] or "192.168.0.X"
        port_part = f":{card['port']}" if card["port"] else ""
        return {"scope": scope, "path": rpt_path, "line_no": None,
                 "text": f"{node} = radio@{ip}{port_part}/{node},NONE"}

    return {"error": f"Unknown scope '{scope}'."}


def _apply_targeted_conf_edit(path: str, line_no: int | None, new_text: str, stanza_name: str) -> dict:
    if not os.path.exists(path):
        return {"success": False, "output": f"{path} does not exist."}

    try:
        with open(path, "r") as f:
            original_text = f.read()
    except OSError as e:
        return {"success": False, "output": f"Could not read {path}: {e}"}

    old_lines = original_text.splitlines(keepends=True)
    nt = new_text if new_text.endswith("\n") else new_text + "\n"

    if line_no is not None:
        idx = line_no - 1
        if idx < 0 or idx >= len(old_lines):
            return {"success": False, "output": f"Line {line_no} is out of range for {path} — file may have changed; re-open the editor and try again."}
        new_lines = list(old_lines)
        new_lines[idx] = nt
    else:
        stanzas = _read_conf_stanzas(path)
        if stanzas is None or stanzas.get("_unreadable"):
            return {"success": False, "output": f"Could not parse {path} to find [{stanza_name}]."}
        target = stanzas.get(stanza_name)
        if target is None:
            return {"success": False, "output": f"[{stanza_name}] stanza not found in {path}."}
        insert_after_line = target["entries"][-1]["line_no"] if target["entries"] else target["line_no"]
        new_lines = list(old_lines)
        new_lines.insert(insert_after_line, nt)

    new_full_text = "".join(new_lines)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = f"{path}.bak.{ts}"
    try:
        shutil.copy2(path, backup_path)
    except OSError as e:
        return {"success": False, "output": f"Backup failed — aborting write (nothing changed): {e}"}

    diff = "".join(difflib.unified_diff(
        old_lines, new_lines, fromfile=f"{path} (before)", tofile=f"{path} (after)", lineterm="\n",
    ))

    try:
        with open(path, "w") as f:
            f.write(new_full_text)
    except OSError as e:
        return {"success": False, "output": f"Write failed after backup was made ({backup_path}): {e}", "backup_path": backup_path}

    return {
        "success": True,
        "output": f"Saved {path}.",
        "backup_path": backup_path,
        "diff": diff,
    }


def action_save_node_snippet(cfg: configparser.ConfigParser, scope: str, text: str) -> dict:
    text = text.strip()
    if not text:
        return {"success": False, "output": "Snippet text is empty."}
    if "\n" in text:
        return {"success": False, "output": "Snippet must be a single line."}

    info = build_node_snippet(cfg, scope)
    if "error" in info:
        return {"success": False, "output": info["error"]}

    path, line_no = info["path"], info["line_no"]

    if scope == "box":
        if not re.match(r"^bindport\s*=\s*\d+\b", text, re.IGNORECASE):
            return {"success": False, "output": "Expected a 'bindport = <number>' line."}
        stanza_name = "general"
    elif scope.startswith("local:") or scope.startswith("peer:"):
        node = scope.split(":", 1)[1]
        if not re.match(rf"^{re.escape(node)}\s*=\s*radio@", text):
            return {"success": False, "output": f"Expected a '{node} = radio@...' line for node {node}."}
        stanza_name = "nodes"
    else:
        return {"success": False, "output": f"Unknown scope '{scope}'."}

    result = _apply_targeted_conf_edit(path, line_no, text, stanza_name)
    if result["success"]:
        log(f"Nodes tab: wrote {scope} -> {path} (backup: {result.get('backup_path')})")
    return {**result, "scope": scope}




_JS_TABS = """
function clickTab(id) {
  document.querySelectorAll('.tab').forEach(function(el) {
    el.classList.toggle('active', el.id === 'tab-' + id);
  });
  document.querySelectorAll('.tab-panel').forEach(function(el) {
    el.classList.toggle('hidden', el.id !== 'panel-' + id);
  });
}
"""

_JS_OVERVIEW = """
// ── Overview tab (Stage 2) — fetch/populate logic ──
var _ovTimer = null;

function _ovLevelLabel(level) {
  return {ok: 'All clear', info: 'Info', warn: 'Attention', danger: 'Exposure risk'}[level] || level;
}

function _ovDot(level) {
  return '<span class="ov-dot ' + level + '"></span>';
}

function renderOverview(data) {
  // Banner — single worst-level finding drives color/text.
  var levels = {ok: 0, info: 1, warn: 2, danger: 3};
  var worst = 'ok';
  (data.self_check || []).forEach(function(f) {
    if ((levels[f.level] || 0) > levels[worst]) worst = f.level;
  });
  var banner = document.getElementById('ov-banner');
  banner.className = 'ov-banner lvl-' + worst;
  banner.textContent = worst === 'danger'
    ? 'Self-check found a possible public exposure — see findings below.'
    : (worst === 'warn' ? 'Self-check found something worth a look.' : 'Self-check clear.');

  // wg0 / tunnel card
  var wg0html = _ovDot(data.wg0_present ? 'ok' : 'info') +
    (data.wg0_present ? 'wg0 interface present' : 'wg0 interface not present');
  if (data.wg0_conf) {
    if (data.wg0_conf._unreadable) {
      wg0html += '<br>' + _ovDot('warn') + 'wg0.conf exists but is not readable by this process';
    } else if (data.wg0_conf.interface && data.wg0_conf.interface.Address) {
      wg0html += '<br>Address: ' + data.wg0_conf.interface.Address;
    }
  } else {
    wg0html += '<br>' + _ovDot('info') + 'No wg0.conf found yet (expected before Pi Install)';
  }
  if (data.wg_status) {
    if (data.wg_status.latest_handshake) wg0html += '<br>Handshake: ' + data.wg_status.latest_handshake;
    if (data.wg_status.transfer) wg0html += '<br>Transfer: ' + data.wg_status.transfer;
  }
  document.getElementById('ov-wg0').innerHTML = wg0html;

  // Configured tunnels card
  var tNames = data.tunnel_names || [];
  document.getElementById('ov-tunnels').innerHTML = tNames.length
    ? tNames.map(function(n){ return _ovDot('ok') + n; }).join('<br>')
    : _ovDot('info') + 'No tunnels configured yet (Pi/Router Install not run)';

  // Firewall zone card
  var fw = data.firewalld_zone;
  document.getElementById('ov-firewall').innerHTML = fw
    ? ('Services: ' + (fw.services.join(', ') || '(none)') +
       '<br>Ports: ' + (fw.ports.join(', ') || '(none)') +
       '<br>Interfaces: ' + (fw.interfaces.join(', ') || '(none)'))
    : (_ovDot('info') + '44NetConnect zone not found yet');

  // Findings card
  var findings = data.self_check || [];
  document.getElementById('ov-findings').innerHTML = findings.length
    ? findings.map(function(f) {
        return '<div class="ov-finding">' + _ovDot(f.level) + f.msg + '</div>';
      }).join('')
    : 'No findings.';

  document.getElementById('ov-checked-at').textContent = 'Last checked: ' + (data.checked_at || '');
}

function refreshOverview() {
  fetch('/api/overview').then(function(r) { return r.json(); }).then(renderOverview);
}
"""

_JS_PI_INSTALL = """
// ── Pi Install tab (Stage 3) ──
// Model B port-forward presets (mirrors MODEL_B_FORWARD_SERVICES server-side, sec 6.2 step 9)
var MODEL_B_SERVICES = {
  iax2: {label: 'AllStarLink IAX2', port: '4569', proto: 'udp'}
};

var PI_STEP_META = [
  {id: 'firewalld_prereq', num: 1, title: 'Firewall prereq (firewalld)',
   cmd: 'apt-get install -y firewalld && systemctl enable --now firewalld'},
  {id: 'resolved_prereq', num: '1a', title: 'systemd-resolved prereq (ARDC guide, sec 1a.1)',
   cmd: 'apt-get install -y wireguard systemd-resolved && systemctl enable --now systemd-resolved'},
  {id: 'create_zone', num: 2, title: 'Create 44NetConnect firewall zone',
   cmd: 'firewall-cmd --permanent --new-zone=44NetConnect && firewall-cmd --reload'},
  {id: 'service_ports', num: 3, title: 'Add inbound services/ports', checklist: true},
  {id: 'paste_config', num: 4, title: 'Paste WireGuard config', paste: true},
  {id: 'attach_interface', num: 5, title: 'Attach wg0 to the zone',
   cmd: 'firewall-cmd --permanent --zone=44NetConnect --add-interface=wg0 && firewall-cmd --reload'},
  {id: 'enable_tunnel', num: 6, title: 'Enable + start the tunnel',
   cmd: 'systemctl enable --now wg-quick@wg0  (falls back to a custom unit if that template is unavailable, sec 1a.3)',
   verify: true}
];

function pillState(step) {
  if (step && step.done) return 'done';
  return window._piAttempted && window._piAttempted[step.__id] ? 'attempted_unconfirmed' : 'not_started';
}
function pillLabel(state) {
  return {not_started: 'Not started', attempted_unconfirmed: 'Attempted \u2014 unconfirmed', done: 'Done'}[state];
}

function renderPiInstall(data) {
  window._piCatalog = data.services_catalog;
  var html = '';
  PI_STEP_META.forEach(function(meta) {
    var step = data.steps[meta.id] || {};
    step.__id = meta.id;
    var state = pillState(step);
    html += '<div class="step-card" id="pi-card-' + meta.id + '">';
    html += '  <div class="step-head"><div class="step-title"><span class="step-num">' + meta.num + '.</span>' + meta.title + '</div>';
    html += '  <span class="step-pill ' + state + '">' + pillLabel(state) + '</span></div>';

    if (meta.id === 'firewalld_prereq') {
      html += '<div class="step-body">Installed: ' + step.installed + ' &middot; Active: ' + step.active + '</div>';
    } else if (meta.id === 'resolved_prereq') {
      html += '<div class="step-body">Per sec 1a.1 (ARDC guide, not the ASL manual) \u2014 required or wg-quick up can fail with a resolve1 timeout. Reboot recommended after install, before step 6.</div>';
    } else if (meta.id === 'create_zone') {
      html += '<div class="step-body">Zones present: ' + ((step.zones||[]).join(', ') || '(none)') + '</div>';
    } else if (meta.id === 'service_ports') {
      html += '<div class="checklist">';
      Object.keys(window._piCatalog || {}).forEach(function(svc) {
        var meta2 = window._piCatalog[svc];
        var on = (step.services||[]).indexOf(svc) !== -1;
        html += '<label><input type="checkbox" ' + (on?'checked disabled':'') + ' onchange="piAddService(\\'' + svc + '\\')"> ' + meta2.label + (on?' (already added)':'') + '</label>';
      });
      html += '<label>Custom port (e.g. 14569/udp): <input type="text" id="pi-custom-port" style="font-family:var(--mono);background:#0a1020;color:var(--text-bright);border:1px solid var(--border2);border-radius:4px;padding:.2rem .4rem"> <button class="btn-run" onclick="piAddPort()">Add</button></label>';
      html += '</div><div class="step-body">Current ports in zone: ' + ((step.ports||[]).join(', ') || '(none)') + '</div>';
    } else if (meta.id === 'paste_config') {
      if (step.done) {
        html += '<div class="step-body">wg0.conf present, permissions 600. (Not re-displayed \u2014 private key never sent back to the browser.)</div>';
      } else {
        html += '<textarea class="wg-paste" id="pi-wg-paste" placeholder="Paste the WireGuard config block from the 44Net Connect portal here..."></textarea>';
        html += '<div class="step-actions"><button class="btn-run" onclick="piPasteConfig()">Write wg0.conf (chmod 600)</button></div>';
      }
    } else if (meta.id === 'attach_interface') {
      html += '<div class="step-body">Interfaces in zone: ' + ((step.interfaces||[]).join(', ') || '(none)') + '</div>';
    } else if (meta.id === 'enable_tunnel') {
      html += '<div class="step-warn">Starting the tunnel can change this Pi\\'s return network path. If you are connected over SSH/Cockpit from outside the LAN, that session may drop \u2014 use local/console access or tmux if possible (per the 44Net Connect manual).</div>';
      if (step.wg_status && step.wg_status.latest_handshake) {
        html += '<div class="step-body">Handshake: ' + step.wg_status.latest_handshake + '</div>';
      }
      html += '<div class="step-actions"><button class="btn-run" onclick="piVerify()">Verify (connect.44net.cloud/myip + rpt show registrations)</button><span id="pi-verify-out" class="step-body"></span></div>';
    }

    if (meta.cmd) {
      html += '<div class="step-actions">';
      html += '<button class="btn-run" onclick="piRunStep(\\'' + meta.id + '\\')">Run</button>';
      html += '</div><div class="cmd-preview">$ ' + meta.cmd + '</div>';
    }
    html += '<div class="step-body" id="pi-out-' + meta.id + '"></div>';
    html += '</div>';
  });
  document.getElementById('pi-steps').innerHTML = html;
  document.getElementById('pi-checked-at').textContent = 'Last checked: ' + (data.checked_at || '');
}

function refreshPiInstall() {
  fetch('/api/pi_install/status').then(function(r) { return r.json(); }).then(renderPiInstall);
}

function _piConfirmAndPost(stepId, cmdPreview, body) {
  if (!confirm('Run this on the Pi?\\n\\n' + cmdPreview)) return;
  window._piAttempted = window._piAttempted || {};
  window._piAttempted[stepId] = true;
  fetch('/api/pi_install/action', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(Object.assign({step: stepId}, body || {}))
  }).then(function(r) { return r.json(); }).then(function(result) {
    var out = document.getElementById('pi-out-' + stepId);
    if (out) out.textContent = result.output || '';
    refreshPiInstall();
  });
}

function piRunStep(stepId) {
  var meta = PI_STEP_META.filter(function(m){ return m.id === stepId; })[0];
  _piConfirmAndPost(stepId, meta.cmd, {});
}
function piAddService(svc) {
  _piConfirmAndPost('service_ports', 'firewall-cmd --permanent --zone=44NetConnect --add-service=' + svc + ' && firewall-cmd --reload', {action: 'add_service', service: svc});
}
function piAddPort() {
  var val = document.getElementById('pi-custom-port').value.trim();
  if (!val) return;
  _piConfirmAndPost('service_ports', 'firewall-cmd --permanent --zone=44NetConnect --add-port=' + val + ' && firewall-cmd --reload', {action: 'add_port', port: val});
}
function piPasteConfig() {
  var text = document.getElementById('pi-wg-paste').value;
  if (!confirm('Write this to /etc/wireguard/wg0.conf (mode 600)? The private key is never sent back to this browser once saved.')) return;
  window._piAttempted = window._piAttempted || {};
  window._piAttempted['paste_config'] = true;
  fetch('/api/pi_install/action', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({step: 'paste_config', config_text: text})
  }).then(function(r){ return r.json(); }).then(function(result){
    var out = document.getElementById('pi-out-paste_config');
    if (out) out.textContent = result.output || '';
    refreshPiInstall();
  });
}
function piVerify() {
  document.getElementById('pi-verify-out').textContent = 'Checking...';
  fetch('/api/pi_install/verify').then(function(r){ return r.json(); }).then(function(result){
    document.getElementById('pi-verify-out').textContent =
      'myip: ' + (result.myip.output || '') + '  |  rpt: ' + (result.rpt.output ? 'ok' : 'unavailable');
  });
}
"""

_JS_NODES = """
// ── Nodes tab (Stages 1-7, Scenario B) ──
// Not auto-polled like Overview (5s interval would blow away any open
// inline editor mid-edit) — refreshed on load, after the Re-check
// button, and after any peer/save action completes.

function ndLevelLabel(level) {
  return {ok: 'All clear', info: 'Info', warn: 'Attention', danger: 'Problem'}[level] || level;
}

function ndFindingsFor(scope, findings) {
  return (findings || []).filter(function(f) { return f.scope === scope; });
}

function ndRenderFindings(scope, findings) {
  var rows = ndFindingsFor(scope, findings);
  if (!rows.length) return '';
  return rows.map(function(f) {
    var fixHtml = (f.fix && (f.level === 'warn' || f.level === 'danger'))
      ? '<div style="margin-top:.35rem;padding-top:.35rem;border-top:1px solid rgba(255,255,255,.12);white-space:pre-line"><b>What to do:</b><br>' + f.fix + '</div>'
      : '';
    return '<div class="ov-banner lvl-' + f.level + '" style="padding:.4rem .5rem;margin:.35rem 0;font-size:.74rem;line-height:1.45">' + f.msg + fixHtml + '</div>';
  }).join('');
}

function ndPillFor(scope, findings) {
  var rows = ndFindingsFor(scope, findings);
  var order = {danger: 3, warn: 2, info: 1, ok: 0};
  var worst = 'ok';
  rows.forEach(function(f) { if ((order[f.level] || 0) > (order[worst] || 0)) worst = f.level; });
  var cls = {ok: 'done', warn: 'attempted_unconfirmed', danger: 'danger', info: 'not_started'}[worst] || 'not_started';
  return '<span class="step-pill ' + cls + '">' + ndLevelLabel(worst) + '</span>';
}

function ndEditorHtml(scope) {
  var safe = scope.replace(':', '-');
  return '<div class="nd-editor-wrap" id="nd-editor-wrap-' + safe + '">' +
    '<textarea id="nd-ta-' + safe + '" spellcheck="false"></textarea>' +
    '<div class="nd-editor-bar">' +
      '<button class="btn-run" onclick="ndSave(\\'' + scope + '\\')">\U0001F4BE Save</button>' +
      '<button class="btn-run" style="color:var(--muted);border-color:var(--border2)" onclick="ndCopy(\\'' + scope + '\\')">\u2398 Copy</button>' +
      '<button class="btn-run" style="color:var(--muted);border-color:var(--border2)" onclick="ndClose(\\'' + scope + '\\')">\u2715 Close</button>' +
      '<span class="nd-editor-status" id="nd-status-' + safe + '"></span>' +
    '</div></div>';
}

function renderNodes(data) {
  window._ndData = data;

  var banner = document.getElementById('nd-banner');
  if (banner) {
    banner.className = 'ov-banner lvl-' + data.guardrail_level;
    var wide = ndFindingsFor('box', data.guardrails).concat(ndFindingsFor('peers', data.guardrails));
    banner.textContent = wide.length ? wide.map(function(f) { return f.msg; }).join('  |  ') : 'No box/peer-wide issues found.';
  }

  var box = data.box;
  var boxBody = document.getElementById('nd-box-body');
  if (boxBody) {
    boxBody.innerHTML =
      'bindport: <b>' + box.bindport + '</b>' + (box.bindport_explicit ? '' : ' (implicit default)') +
      ' &middot; recommended range: ' + box.bindport_range_min + '-' + box.bindport_range_max + ' ' +
      ndPillFor('box', data.guardrails) +
      '<div style="margin-top:.4rem"><button class="btn-run" onclick="ndToggleEditor(\\'box\\')">Edit bindport</button></div>' +
      ndRenderFindings('box', data.guardrails) +
      ndEditorHtml('box');
  }

  var localHtml = '';
  (data.local_nodes || []).forEach(function(c) {
    var scope = 'local:' + c.node;
    localHtml +=
      '<div class="nd-card-row"><div><b>' + c.node + '</b> &middot; ' + (c.rxchannel || '(no rxchannel)') + ' ' +
      ndPillFor(scope, data.guardrails) + '</div>' +
      '<button class="btn-run" onclick="ndToggleEditor(\\'' + scope + '\\')">Edit</button></div>' +
      ndRenderFindings(scope, data.guardrails) + ndEditorHtml(scope);
  });
  var localEl = document.getElementById('nd-local-cards');
  if (localEl) localEl.innerHTML = localHtml || 'No locally-hosted nodes detected.';

  var peerHtml = '';
  (data.peer_nodes || []).forEach(function(c) {
    var scope = 'peer:' + c.node;
    var linkBtn = '';
    if (c.helper_url) {
      var probed = c.helper_probe;
      var reachable = probed && probed.reachable;
      var cls = 'nd-link-btn' + (reachable ? '' : ' nd-link-btn-dim');
      var title = probed
        ? (reachable ? ' title="44helper reachable' + (probed.remote_version ? ' (v' + probed.remote_version + ')' : '') + '"'
                     : ' title="44helper unreachable: ' + (probed.error || 'no response') + '"')
        : ' title="Reachability not checked"';
      linkBtn = '<button class="' + cls + '"' + title + ' onclick="ndOpenHelper(\\'' + c.helper_url.replace(/'/g, "\\'") + '\\')">\U0001F517 44helper</button> ';
    }
    peerHtml +=
      '<div class="nd-card-row"><div><b>' + c.node + '</b> &middot; ' + (c.ip || '?') + (c.port ? (':' + c.port) : '') +
      (c.label ? (' \u2014 ' + c.label) : '') + ' ' +
      (c.wired ? '<span class="step-pill done">Wired</span>' : '<span class="step-pill not_started">Not wired</span>') + ' ' +
      ndPillFor(scope, data.guardrails) + '</div>' +
      '<div>' + linkBtn +
      '<button class="btn-run" onclick="ndToggleEditor(\\'' + scope + '\\')">Edit</button> ' +
      '<button class="btn-run" style="color:var(--red);border-color:var(--red)" onclick="ndPeerRemove(\\'' + c.node + '\\')">Remove</button></div></div>' +
      (c.helper_remote_status
        ? '<div class="step-body" style="margin:.2rem 0 0;font-size:.72rem">Peer reports: bindport ' +
          c.helper_remote_status.box.bindport + ', status ' + c.helper_remote_status.guardrail_level + '</div>'
        : '') +
      ndRenderFindings(scope, data.guardrails) + ndEditorHtml(scope);
  });
  var peerEl = document.getElementById('nd-peer-cards');
  if (peerEl) peerEl.innerHTML = peerHtml || 'No peers configured yet.';

  var checkedEl = document.getElementById('nd-checked-at');
  if (checkedEl) checkedEl.textContent = 'Refreshed just now';
}

function ndToggleEditor(scope) {
  var safe = scope.replace(':', '-');
  var wrap = document.getElementById('nd-editor-wrap-' + safe);
  if (!wrap) return;
  var opening = !wrap.classList.contains('open');
  wrap.classList.toggle('open', opening);
  if (opening) {
    fetch('/api/nodes/edit_snippet?scope=' + encodeURIComponent(scope))
      .then(function(r) { return r.json(); })
      .then(function(d) {
        var ta = document.getElementById('nd-ta-' + safe);
        if (ta) ta.value = d.text || d.error || '';
      });
  }
}

function ndClose(scope) {
  var wrap = document.getElementById('nd-editor-wrap-' + scope.replace(':', '-'));
  if (wrap) wrap.classList.remove('open');
}

function ndSave(scope) {
  var safe = scope.replace(':', '-');
  var ta = document.getElementById('nd-ta-' + safe);
  if (!ta) return;
  var text = ta.value;
  if (!confirm('Save this line?\\n\\n' + text + '\\n\\nA backup of the file is made automatically before writing.')) return;
  fetch('/api/nodes/save_snippet', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({scope: scope, text: text})
  }).then(function(r) { return r.json(); }).then(function(result) {
    alert(result.success ? ('Saved.\\n\\n' + (result.diff || '')) : ('Save failed: ' + result.output));
    refreshNodes();
  });
}

function ndCopy(scope) {
  var safe = scope.replace(':', '-');
  var ta = document.getElementById('nd-ta-' + safe);
  if (!ta || !ta.value) return;
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(ta.value);
  } else {
    ta.select();
    document.execCommand('copy');
  }
  var st = document.getElementById('nd-status-' + safe);
  if (st) { st.textContent = 'Copied'; setTimeout(function() { st.textContent = ''; }, 1500); }
}

function ndOpenHelper(url) {
  var u = url.indexOf('http') === 0 ? url : ('http://' + url);
  window.open(u, 'asl_dvs_44h');
}

function ndPeerSave() {
  var node = document.getElementById('nd-peer-node').value.trim();
  var ip = document.getElementById('nd-peer-ip').value.trim();
  var port = document.getElementById('nd-peer-port').value.trim();
  var label = document.getElementById('nd-peer-label').value.trim();
  var url = document.getElementById('nd-peer-url').value.trim();
  if (!node || !ip) { alert('Node number and IP are required.'); return; }
  fetch('/api/nodes/peer_add', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({node: node, ip: ip, port: port, label: label, helper_url: url})
  }).then(function(r) { return r.json(); }).then(function(result) {
    if (!result.success) { alert('Could not save peer: ' + result.output); return; }
    ['nd-peer-node', 'nd-peer-ip', 'nd-peer-port', 'nd-peer-label', 'nd-peer-url'].forEach(function(id) {
      var el = document.getElementById(id); if (el) el.value = '';
    });
    refreshNodes();
  });
}

function ndPeerRemove(node) {
  if (!confirm('Remove peer ' + node + ' from stored bookkeeping?\\n\\nThis does not remove any [nodes] line already wired into rpt.conf.')) return;
  fetch('/api/nodes/peer_remove', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({node: node})
  }).then(function(r) { return r.json(); }).then(function() { refreshNodes(); });
}

function refreshNodes() {
  fetch('/api/nodes/status').then(function(r) { return r.json(); }).then(renderNodes);
}
"""

_JS_INIT = """
// Default to the Overview tab on load, then start polling.
document.addEventListener('DOMContentLoaded', function() {
  clickTab('overview');
  refreshOverview();
  refreshPiInstall();
  refreshRouterInstall();
  refreshNodes();
  refreshServices();
  refreshPorts();
  refreshFirewall();
  refreshActionsLog();
  refreshAsl3();
  _ovTimer = setInterval(refreshOverview, 5000);
});
"""

_JS_ROUTER_INSTALL = """
// ── Router Install tab (Stage 4: steps 1, 2, 2a only) ──
function renderRouterInstall(data) {
  var cfg = data.config;
  var probe = data.probe;
  var html = '';

  // Step 1: router access config
  html += '<div class="step-card"><div class="step-head"><div class="step-title"><span class="step-num">1.</span>Router access</div>';
  html += '<span class="step-pill ' + (probe.reachable ? 'done' : (probe.configured ? 'attempted_unconfirmed' : 'not_started')) + '">' +
          (probe.reachable ? 'Reachable' : (probe.configured ? 'Configured, not reachable' : 'Not configured')) + '</span></div>';
  html += '<div class="step-body">';
  html += 'Access method: <select id="rt-access-method">';
  ['none','ssh','api'].forEach(function(m) {
    html += '<option value="' + m + '"' + (cfg.access_method === m ? ' selected' : '') + '>' + m + '</option>';
  });
  html += '</select><br>';
  html += 'Host: <input type="text" id="rt-host" value="' + (cfg.host||'') + '" placeholder="192.168.8.1" style="font-family:var(--mono);background:#0a1020;color:var(--text-bright);border:1px solid var(--border2);border-radius:4px;padding:.2rem .4rem"><br>';
  html += 'User: <input type="text" id="rt-user" value="' + (cfg.user||'') + '" placeholder="root" style="font-family:var(--mono);background:#0a1020;color:var(--text-bright);border:1px solid var(--border2);border-radius:4px;padding:.2rem .4rem"><br>';
  html += 'SSH key path: <input type="text" id="rt-key" value="' + (cfg.key_path||'') + '" placeholder="/etc/44helper/router_id_ed25519" style="font-family:var(--mono);background:#0a1020;color:var(--text-bright);border:1px solid var(--border2);border-radius:4px;padding:.2rem .4rem;width:280px"><br>';
  html += 'Poll interval (sec): <input type="text" id="rt-poll" value="' + (cfg.poll_interval_sec||'60') + '" style="font-family:var(--mono);background:#0a1020;color:var(--text-bright);border:1px solid var(--border2);border-radius:4px;padding:.2rem .4rem;width:60px">';
  html += '</div><div class="step-actions"><button class="btn-run" onclick="routerSaveConfig()">Save</button>';
  html += '<button class="btn-run" onclick="routerReprobe()">Test connection / Re-probe</button></div>';
  html += '<div class="step-body" id="rt-save-out"></div>';
  html += '</div>';

  // Step 2: firmware/model probe (read-only display of last probe result)
  html += '<div class="step-card"><div class="step-head"><div class="step-title"><span class="step-num">2.</span>Router firmware/model detection</div>';
  html += '<span class="step-pill ' + (probe.reachable ? 'done' : 'not_started') + '">' + (probe.reachable ? 'Probed' : 'Not probed') + '</span></div>';
  if (probe.reachable) {
    html += '<div class="step-body">';
    html += 'OpenWrt: ' + probe.is_openwrt + ' &middot; uci available: ' + probe.uci_available + '<br>';
    html += 'GL.iNet detected: ' + probe.is_glinet + (probe.matched_model ? (' &middot; matched known model: ' + probe.matched_model) : '') + '<br>';
    if (probe.raw_openwrt_release) html += '<span style="color:var(--muted)">' + probe.raw_openwrt_release.replace(/\\n/g,'<br>') + '</span>';
    html += '</div>';
  } else {
    html += '<div class="step-body">Configure and test router access above first.</div>';
  }
  html += '</div>';

  // Step 2a: LuCI status + install (mutating action, real as of Stage 5)
  html += '<div class="step-card"><div class="step-head"><div class="step-title"><span class="step-num">2a.</span>LuCI status (GL.iNet/OpenWrt)</div>';
  var luciState = probe.luci_present === true ? 'done' : (probe.luci_present === false ? 'attempted_unconfirmed' : 'not_started');
  html += '<span class="step-pill ' + luciState + '">' + (probe.luci_present === true ? 'Installed' : (probe.luci_present === false ? 'Not installed' : 'Unknown')) + '</span></div>';
  if (probe.luci_present === false) {
    html += '<div class="step-actions"><button class="btn-run" onclick="routerRunAction(\\'install_luci\\', {}, \\'opkg update && opkg install luci\\')">Install LuCI</button></div>';
  } else {
    html += '<div class="step-body">' + (probe.luci_present === true ? 'Already installed.' : 'Probe the router first (step 1) to check.') + '</div>';
  }
  html += '<div class="step-body" id="rt-out-install_luci"></div></div>';

  var rs = data.router_steps || {};

  // Step 3: allocation type
  var atDone = rs.allocation_type && rs.allocation_type.done;
  html += '<div class="step-card"><div class="step-head"><div class="step-title"><span class="step-num">3.</span>Allocation type</div>';
  html += '<span class="step-pill ' + (atDone ? 'done' : 'not_started') + '">' + (atDone ? rs.allocation_type.mode : 'Not set') + '</span></div>';
  html += '<div class="step-body">Do you have a single 44Net Connect address (portal, Model B) or a routed subnet from a local coordinator/sysop (Model C)? This changes everything below (design plan sec 1b).</div>';
  html += '<div class="step-actions"><button class="btn-run" onclick="routerRunAction(\\'allocation_type\\', {mode:\\'router_subnet\\'}, \\'Set allocation type = router_subnet (Model C)\\')">Routed subnet (Model C)</button>';
  html += '<button class="btn-run" onclick="routerRunAction(\\'allocation_type\\', {mode:\\'router_single\\'}, \\'Set allocation type = router_single (Model B)\\')">Single address (Model B)</button></div>';
  html += '<div class="step-body" id="rt-out-allocation_type"></div></div>';

  // Step 4: capture config + LAN subnet
  var ccDone = rs.capture_config && rs.capture_config.done;
  html += '<div class="step-card"><div class="step-head"><div class="step-title"><span class="step-num">4.</span>Capture WireGuard config + LAN subnet</div>';
  html += '<span class="step-pill ' + (ccDone ? 'done' : 'not_started') + '">' + (ccDone ? 'Captured' : 'Not captured') + '</span></div>';
  if (ccDone) {
    html += '<div class="step-body">Interface address: ' + rs.capture_config.wg_address + '<br>LAN subnet: ' + rs.capture_config.lan_subnet + '</div>';
  } else {
    html += '<textarea class="wg-paste" id="rt-wg-paste" placeholder="Paste the WireGuard config block from your coordinator/sysop..."></textarea>';
    html += '<label>LAN subnet CIDR (e.g. 44.56.66.1/28): <input type="text" id="rt-lan-subnet" style="font-family:var(--mono);background:#0a1020;color:var(--text-bright);border:1px solid var(--border2);border-radius:4px;padding:.2rem .4rem"></label>';
    html += '<div class="step-actions"><button class="btn-run" onclick="routerCaptureConfig()">Capture</button></div>';
  }
  html += '<div class="step-body" id="rt-out-capture_config"></div></div>';

  // Step 5: apply WG config
  var awDone = rs.apply_wg_config && rs.apply_wg_config.done;
  html += '<div class="step-card"><div class="step-head"><div class="step-title"><span class="step-num">5.</span>Apply WireGuard config to router (uci)</div>';
  html += '<span class="step-pill ' + (awDone ? 'done' : 'not_started') + '">' + (awDone ? 'Applied' : 'Not applied') + '</span></div>';
  html += '<div class="step-body">Pushes the captured config via uci over SSH. The private key was staged server-side at capture time and is never re-sent from this browser.</div>';
  html += '<div class="step-actions"><button class="btn-run" ' + (ccDone ? '' : 'disabled') + ' onclick="routerRunAction(\\'apply_wg_config\\', {}, \\'Apply captured WireGuard config to the router via uci (private key already staged server-side)\\')">Apply</button></div>';
  html += '<div class="step-body" id="rt-out-apply_wg_config"></div></div>';

  var isModelB = rs.allocation_type && rs.allocation_type.mode === 'router_single';

  // Step 6: LAN IP change -- Model C only
  if (!isModelB) {
    var liDone = rs.set_lan_ip && rs.set_lan_ip.done;
    html += '<div class="step-card"><div class="step-head"><div class="step-title"><span class="step-num">6.</span>Set router LAN IP to the subnet</div>';
    html += '<span class="step-pill ' + (liDone ? 'attempted_unconfirmed' : 'not_started') + '">' + (liDone ? 'Attempted \u2014 unconfirmed' : 'Not started') + '</span></div>';
    html += '<div class="step-warn">This changes the router\\'s own LAN address. The admin session AND this Pi\\'s network connection may drop (design plan sec 1b.5 / this file\\'s header note). After running: renew this Pi\\'s DHCP lease (or reboot it), update the Host field in step 1 to the new LAN IP, then Re-probe.</div>';
    html += '<div class="step-actions"><button class="btn-run" ' + (ccDone ? '' : 'disabled') + ' onclick="routerRunAction(\\'set_lan_ip\\', {}, \\'uci set network.lan.proto=static + ipaddr/netmask from the captured subnet, then network reload\\')">Set LAN IP</button></div>';
    html += '<div class="step-body" id="rt-out-set_lan_ip"></div></div>';
  }

  // Step 7: bring up tunnel
  var buDone = rs.bring_up_tunnel && rs.bring_up_tunnel.done;
  html += '<div class="step-card"><div class="step-head"><div class="step-title"><span class="step-num">7.</span>Bring up the tunnel</div>';
  html += '<span class="step-pill ' + (buDone ? 'done' : 'not_started') + '">' + (buDone ? 'Up' : 'Not started') + '</span></div>';
  html += '<div class="step-actions"><button class="btn-run" onclick="routerRunAction(\\'bring_up_tunnel\\', {}, \\'ifup wgclient; check ifstatus\\')">Bring up tunnel</button></div>';
  html += '<div class="step-body" id="rt-out-bring_up_tunnel"></div></div>';

  // Step 8: Pi's address (44Net address for Model C, ordinary LAN IP for Model B)
  html += '<div class="step-card"><div class="step-head"><div class="step-title"><span class="step-num">8.</span>Pi\\'s ' + (isModelB ? 'LAN IP' : '44Net address') + '</div>';
  html += '<span class="step-pill ' + (rs.pi_address && rs.pi_address.pi_mac ? 'attempted_unconfirmed' : 'not_started') + '">' + (rs.pi_address && rs.pi_address.pi_mac ? ('MAC: ' + rs.pi_address.pi_mac) : 'Unknown MAC') + '</span></div>';
  html += '<div class="step-actions"><button class="btn-run" onclick="routerRunAction(\\'pi_address_lookup\\', {}, \\'grep this Pi\\'s MAC in /tmp/dhcp.leases on the router\\')">Look up address</button>';
  if (!isModelB) {
    html += '<button class="btn-run" onclick="routerRunAction(\\'pi_address_bind\\', {}, \\'uci add dhcp host - static MAC to IP binding for this Pi\\')">Add static binding</button>';
  }
  html += '</div><div class="step-body" id="rt-out-pi_address_lookup"></div></div>';

  // Step 9: Model C = fix firewall zone. Model B = port-forward checklist.
  if (isModelB) {
    var pf = rs.port_forwards || {forwards: []};
    html += '<div class="step-card"><div class="step-head"><div class="step-title"><span class="step-num">9.</span>Port forwards</div>';
    html += '<span class="step-pill ' + (pf.forwards.length ? 'done' : 'not_started') + '">' + (pf.forwards.length ? (pf.forwards.length + ' configured') : 'None yet') + '</span></div>';
    html += '<div class="step-body">Forwards the router\\'s 44.x.x.x address:port to the Pi\\'s LAN IP (step 8 must be run first).<br>Configured: ' + (pf.forwards.join(', ') || '(none)') + '</div>';
    html += '<div class="checklist">';
    Object.keys(MODEL_B_SERVICES).forEach(function(svc) {
      var m = MODEL_B_SERVICES[svc];
      html += '<label><input type="checkbox" onchange="routerAddForward(\\'' + svc + '\\', \\'' + m.port + '\\', \\'' + m.proto + '\\')"> ' + m.label + ' (' + m.port + '/' + m.proto + ')</label>';
    });
    html += '<label>Custom: port <input type="text" id="rt-fwd-port" style="width:70px;font-family:var(--mono);background:#0a1020;color:var(--text-bright);border:1px solid var(--border2);border-radius:4px;padding:.2rem .4rem"> proto ';
    html += '<select id="rt-fwd-proto"><option value="udp">udp</option><option value="tcp">tcp</option></select> ';
    html += '<button class="btn-run" onclick="routerAddCustomForward()">Add</button></label>';
    html += '</div><div class="step-body" id="rt-out-add_port_forward"></div></div>';
  } else {
    var fzDone = rs.firewall_zone && rs.firewall_zone.done;
    html += '<div class="step-card"><div class="step-head"><div class="step-title"><span class="step-num">9.</span>Fix wireguard firewall zone</div>';
    html += '<span class="step-pill ' + (fzDone ? 'done' : 'not_started') + '">' + (fzDone ? 'Fixed' : 'Not fixed') + '</span></div>';
    html += '<div class="step-body">Sets Forward=ACCEPT and turns off Masquerade on the wireguard zone, so LAN devices\\' real 44.x.x.x addresses are used instead of NAT\\'d (design plan sec 1b.4).</div>';
    html += '<div class="step-actions"><button class="btn-run" onclick="routerRunAction(\\'firewall_zone\\', {}, \\'uci set firewall.wgzone.forward=ACCEPT, masq=0\\')">Fix zone</button></div>';
    html += '<div class="step-body" id="rt-out-firewall_zone"></div></div>';
  }

  // Step 10: verify + known-good note
  var vDone = rs.verify && rs.verify.done;
  html += '<div class="step-card"><div class="step-head"><div class="step-title"><span class="step-num">10.</span>Verify</div>';
  html += '<span class="step-pill ' + (vDone ? 'done' : 'not_started') + '">' + (vDone ? 'Verified' : 'Not verified') + '</span></div>';
  if (isModelB) {
    html += '<div class="step-body">Checks outbound traffic uses the router\\'s 44.x.x.x address and that a forward rule is recorded. Does NOT confirm inbound reachability from outside the NAT \u2014 44helper has no vantage point to test that from here.</div>';
  } else {
    html += '<div class="step-body">Pings/traceroutes 44.1.1.17 (portal.ampr.org) from this Pi, checking for another 44.x.x.x hop in the path (design plan sec 1b.6).</div>';
  }
  html += '<div class="step-actions"><button class="btn-run" onclick="routerVerify()">Verify</button>';
  html += '<button class="btn-run" onclick="routerRunAction(\\'save_note\\', {}, \\'Save a known-good router note (model/firmware/access method, no secrets)\\')">Save known-good note</button></div>';
  html += '<div class="step-body" id="rt-out-verify"></div></div>';

  // Step 11: done
  html += '<div class="stub-card"><span class="stub-title">11. Done</span>Once verify (step 10) passes, this Pi has ' +
    (isModelB ? 'a working forwarded path through the router\\'s single 44Net Connect address' : 'its own working 44.x.x.x address via the router\\'s routed subnet') +
    '. Check Overview/Ports/Firewall tabs (Stage 7) for ongoing monitoring.</div>';

  document.getElementById('router-steps').innerHTML = html;
  document.getElementById('router-checked-at').textContent =
    'Last checked: ' + (data.checked_at || '') + (probe._cache_age_sec ? ' (cached, ' + probe._cache_age_sec + 's old)' : ' (fresh)');
}

function refreshRouterInstall(force) {
  Promise.all([
    fetch('/api/router/status' + (force ? '?force=1' : '')).then(function(r){ return r.json(); }),
    fetch('/api/router_install/status').then(function(r){ return r.json(); })
  ]).then(function(results) {
    var overallData = results[0];
    overallData.router_steps = results[1].steps;
    renderRouterInstall(overallData);
  });
}
function routerSaveConfig() {
  var body = {
    access_method: document.getElementById('rt-access-method').value,
    host: document.getElementById('rt-host').value,
    user: document.getElementById('rt-user').value,
    key_path: document.getElementById('rt-key').value,
    poll_interval_sec: document.getElementById('rt-poll').value
  };
  fetch('/api/router/config', {
    method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)
  }).then(function(r){ return r.json(); }).then(function(result) {
    document.getElementById('rt-save-out').textContent = result.output || '';
    refreshRouterInstall(true);
  });
}
function routerReprobe() {
  refreshRouterInstall(true);
}
function routerRunAction(step, extra, description) {
  if (!confirm('Run on the router?\\n\\n' + description)) return;
  fetch('/api/router_install/action', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(Object.assign({step: step}, extra))
  }).then(function(r){ return r.json(); }).then(function(result) {
    var out = document.getElementById('rt-out-' + step);
    if (out) out.textContent = result.output || '';
    refreshRouterInstall(true);
  });
}
function routerCaptureConfig() {
  var text = document.getElementById('rt-wg-paste').value;
  var subnet = document.getElementById('rt-lan-subnet').value;
  var redacted = text.replace(/PrivateKey\\s*=.*/i, 'PrivateKey = (hidden)');
  if (!confirm('Capture this config?\\n\\n' + redacted + '\\n\\nLAN subnet: ' + subnet)) return;
  fetch('/api/router_install/action', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({step: 'capture_config', config_text: text, lan_subnet: subnet})
  }).then(function(r){ return r.json(); }).then(function(result) {
    var out = document.getElementById('rt-out-capture_config');
    if (out) out.textContent = result.output || '';
    refreshRouterInstall(true);
  });
}
function routerVerify() {
  document.getElementById('rt-out-verify').textContent = 'Checking...';
  fetch('/api/router_install/action', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({step: 'verify'})
  }).then(function(r){ return r.json(); }).then(function(result) {
    document.getElementById('rt-out-verify').textContent = result.output || '';
    refreshRouterInstall(true);
  });
}
function routerAddForward(name, port, proto) {
  if (!confirm('Add port forward?\\n\\nRouter 44.x.x.x:' + port + '/' + proto + ' -> this Pi\\'s address:' + port)) return;
  fetch('/api/router_install/action', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({step: 'add_port_forward', name: name, port: port, proto: proto})
  }).then(function(r){ return r.json(); }).then(function(result) {
    document.getElementById('rt-out-add_port_forward').textContent = result.output || '';
    refreshRouterInstall(true);
  });
}
function routerAddCustomForward() {
  var port = document.getElementById('rt-fwd-port').value.trim();
  var proto = document.getElementById('rt-fwd-proto').value;
  if (!port) return;
  routerAddForward('custom-' + port, port, proto);
}
"""

_JS_SERVICES_PORTS = """
// ── Services tab (Stage 7) ──
function refreshServices() {
  fetch('/api/services/status').then(function(r){ return r.json(); }).then(function(data) {
    var html = '';
    Object.keys(data.groups).forEach(function(group) {
      html += '<div class="svc-group-title">' + group + '</div>';
      data.groups[group].forEach(function(item) {
        var cls = 'svc-row' + (item.flag_public ? ' flagged' : '');
        html += '<div class="' + cls + '">' + _ovDot(item.active ? 'ok' : 'info') + item.label +
                ' <span style="color:var(--muted)">(' + item.source + ')</span>' +
                (item.flag_public ? ' <span style="color:var(--amber)">[should stay private]</span>' : '') + '</div>';
      });
    });
    document.getElementById('svc-groups').innerHTML = html;
    document.getElementById('svc-checked-at').textContent = 'Last checked: ' + (data.checked_at || '');
  });
}

// ── Ports tab (Stage 7) ──
function refreshPorts() {
  fetch('/api/ports/status').then(function(r){ return r.json(); }).then(function(data) {
    document.getElementById('ports-source').textContent = 'Exposure source: ' + data.exposure_source;
    var html = '<tr><th>Port</th><th>Proto</th><th>Purpose</th><th>Exposed</th><th>Running</th><th>Status</th></tr>';
    data.rows.forEach(function(row) {
      html += '<tr class="' + (row.mismatch ? 'mismatch' : '') + '">';
      html += '<td>' + row.label + ' (' + row.port + ')</td><td>' + row.proto + '</td><td>' + row.purpose + '</td>';
      html += '<td>' + _ovDot(row.exposed ? 'danger' : 'ok') + (row.exposed ? 'yes' : 'no') + '</td>';
      html += '<td>' + _ovDot(row.running ? 'ok' : 'info') + (row.running ? 'yes' : 'no') + '</td>';
      html += '<td>' + (row.mismatch ? '<span style="color:var(--red)">MISMATCH</span>' : 'ok') + '</td>';
      html += '</tr>';
    });
    document.getElementById('ports-table').innerHTML = html;
    document.getElementById('ports-checked-at').textContent = 'Last checked: ' + (data.checked_at || '');
  });
}
"""

_JS_FIREWALL = """
// ── Firewall tab (Stage 7) ──
function refreshFirewall() {
  fetch('/api/firewall/status').then(function(r){ return r.json(); }).then(function(data) {
    var g = data.allstarlink_guardrail;
    var guardHtml = '';
    if (g.applicable && g.wg0_attached) {
      guardHtml = '<div class="ov-banner lvl-danger">Warning: the default \\'allstarlink\\' firewall zone has wg0 attached \u2014 its whole service set may be reachable on the public 44Net address. No shortcut button is offered here; review manually (design plan sec 6.6).</div>';
    } else if (g.applicable) {
      guardHtml = '<div class="ov-banner lvl-ok">allstarlink zone does not have wg0 attached.</div>';
    }
    document.getElementById('fw-guardrail').innerHTML = guardHtml;

    var zone = data.pi_zone;
    document.getElementById('fw-pi-zone').innerHTML = zone
      ? ('Services: ' + (zone.services.join(', ') || '(none)') + '<br>Ports: ' + (zone.ports.join(', ') || '(none)') + '<br>Interfaces: ' + (zone.interfaces.join(', ') || '(none)'))
      : '44NetConnect zone not found (Pi Install not run yet, or not Pi-hosted).';

    var fw = data.router_forwards;
    var fwHtml;
    if (!data.router_configured) {
      fwHtml = 'Router access not configured (see Router Install step 1).';
    } else if (fw === null) {
      fwHtml = 'Could not query the router (unreachable or ssh unavailable).';
    } else if (fw.length === 0) {
      fwHtml = 'No forward rules found on the router.';
    } else {
      fwHtml = fw.map(function(f) {
        return f.name + ': ' + f.port + '/' + f.proto + ' -> ' + f.dest_ip +
               ' <button class="btn-run" onclick="fwRemoveForward(\\'' + f.id + '\\')">Remove</button>';
      }).join('<br>');
    }
    document.getElementById('fw-router-forwards').innerHTML = fwHtml;
    document.getElementById('fw-checked-at').textContent = 'Last checked: ' + (data.checked_at || '');
  });
}
function fwAddService() {
  var svc = document.getElementById('fw-add-service').value;
  if (!confirm('Run?\\n\\nfirewall-cmd --permanent --zone=44NetConnect --add-service=' + svc)) return;
  fetch('/api/firewall/action', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({action:'add_service', service: svc})})
    .then(function(r){return r.json();}).then(function(result){ document.getElementById('fw-out-pi').textContent = result.output || ''; refreshFirewall(); refreshPorts(); });
}
function fwRemoveService() {
  var svc = document.getElementById('fw-rm-service').value.trim();
  if (!svc || !confirm('Run?\\n\\nfirewall-cmd --permanent --zone=44NetConnect --remove-service=' + svc)) return;
  fetch('/api/firewall/action', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({action:'remove_service', service: svc})})
    .then(function(r){return r.json();}).then(function(result){ document.getElementById('fw-out-pi').textContent = result.output || ''; refreshFirewall(); refreshPorts(); });
}
function fwAddPort() {
  var p = document.getElementById('fw-add-port').value.trim();
  if (!p || !confirm('Run?\\n\\nfirewall-cmd --permanent --zone=44NetConnect --add-port=' + p)) return;
  fetch('/api/firewall/action', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({action:'add_port', port: p})})
    .then(function(r){return r.json();}).then(function(result){ document.getElementById('fw-out-pi').textContent = result.output || ''; refreshFirewall(); refreshPorts(); });
}
function fwRemovePort() {
  var p = document.getElementById('fw-rm-port').value.trim();
  if (!p || !confirm('Run?\\n\\nfirewall-cmd --permanent --zone=44NetConnect --remove-port=' + p)) return;
  fetch('/api/firewall/action', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({action:'remove_port', port: p})})
    .then(function(r){return r.json();}).then(function(result){ document.getElementById('fw-out-pi').textContent = result.output || ''; refreshFirewall(); refreshPorts(); });
}
function fwRemoveForward(id) {
  if (!confirm('Remove this router forward rule?')) return;
  fetch('/api/firewall/action', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({action:'remove_forward', redirect_id: id})})
    .then(function(r){return r.json();}).then(function(result){ refreshFirewall(); refreshPorts(); });
}
"""

_JS_ACTIONS_LOG = """
// ── Actions Log tab (Stage 8) ──
function _logLineClass(line) {
  if (line.indexOf('] RUN:') !== -1) return 'run';
  if (line.indexOf('] OK ') !== -1 || line.indexOf('] OK:') !== -1) return 'ok';
  if (line.indexOf('] FAIL') !== -1) return 'fail';
  if (line.indexOf('WARNING') !== -1) return 'warn';
  return 'plain';
}
function refreshActionsLog() {
  fetch('/api/log').then(function(r){ return r.json(); }).then(function(lines) {
    var html = lines.slice().reverse().map(function(line) {
      return '<div class="log-line ' + _logLineClass(line) + '">' + line.replace(/</g,'&lt;') + '</div>';
    }).join('');
    document.getElementById('log-lines').innerHTML = html || '(empty)';
  });
  fetch('/api/actions_log/notes').then(function(r){ return r.json(); }).then(function(notes) {
    var html = notes.length
      ? notes.map(function(n) { return '<div class="note-item"><a onclick="viewNote(\\'' + n + '\\')">' + n + '</a></div>'; }).join('')
      : '(none saved yet — Router Install\\'s Verify step offers to save one on success)';
    document.getElementById('notes-list').innerHTML = html;
  });
}
function viewNote(filename) {
  fetch('/api/actions_log/notes/' + encodeURIComponent(filename)).then(function(r){ return r.text(); }).then(function(text) {
    var el = document.getElementById('note-view');
    el.style.display = 'block';
    el.textContent = text;
  });
}
"""

_JS_ASL3 = """
// ── ASL3 tab (Stage 1) — distro dropdown, editable-command step cards,
// Purge toggle (double-confirm), Custom-mode transcript. Session-only
// state (window._asl3State) — nothing persisted, resets on reload.
function asl3CurrentDistro() {
  var el = document.getElementById('asl3-distro');
  return el ? el.value : 'bookworm';
}

function asl3EscapeAttr(s) {
  return String(s).replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function asl3RenderStepList(mode, distro) {
  var steps = ((window._asl3Scripts || {})[mode] || {})[distro] || [];
  var html = '';
  steps.forEach(function(step) {
    var stateKey = mode + '_' + distro + '_' + step.id;
    var st = (window._asl3State || {})[stateKey] || {};
    var pillClass = st.status === 'ok' ? 'done' : (st.status === 'fail' ? 'danger' : (st.status === 'attempted' ? 'attempted_unconfirmed' : 'not_started'));
    var pillLabel = st.status === 'ok' ? 'OK' : (st.status === 'fail' ? 'Failed' : (st.status === 'attempted' ? 'Running\u2026' : 'Not run'));
    html += '<div class="step-card">';
    html += '<div class="step-head"><div class="step-title"><span class="step-num">' + step.num + '.</span>' + step.title + '</div>';
    html += '<span class="step-pill ' + pillClass + '" id="asl3-pill-' + stateKey + '">' + pillLabel + '</span></div>';
    if (step.note) html += '<div class="step-warn">' + asl3EscapeAttr(step.note) + '</div>';
    html += '<input type="text" class="asl3-cmd-input" id="asl3-cmd-' + stateKey + '" value="' + asl3EscapeAttr(step.cmd) + '">';
    html += '<div class="step-actions"><button class="btn-run" id="asl3-btn-' + stateKey + '" onclick="asl3RunStep(this,\\'' + mode + '\\',\\'' + distro + '\\',\\'' + step.id + '\\')">Run</button></div>';
    html += '<div class="asl3-console' + (st.output ? ' shown' : '') + (st.status === 'fail' ? ' fail' : '') + '" id="asl3-out-' + stateKey + '">' + (st.output ? asl3EscapeAttr(st.output) : '') + '</div>';
    html += '</div>';
  });
  return html || '<div class="step-body">(no steps defined)</div>';
}

function asl3Render() {
  var distro = asl3CurrentDistro();
  var stepsEl = document.getElementById('asl3-steps');
  var customEl = document.getElementById('asl3-custom');
  var purgeBtn = document.getElementById('asl3-purge-btn');
  if (distro === 'custom') {
    stepsEl.style.display = 'none';
    purgeBtn.style.display = 'none';
    document.getElementById('asl3-purge-steps').innerHTML = '';
    window._asl3PurgeShown = false;
    customEl.style.display = 'block';
  } else {
    customEl.style.display = 'none';
    purgeBtn.style.display = 'inline-block';
    stepsEl.style.display = 'block';
    stepsEl.innerHTML = asl3RenderStepList('install', distro);
  }
}

function asl3OnDistroChange() {
  document.getElementById('asl3-purge-steps').innerHTML = '';
  window._asl3PurgeShown = false;
  asl3Render();
}

function refreshAsl3() {
  fetch('/api/asl3/script').then(function(r) { return r.json(); }).then(function(data) {
    window._asl3Scripts = data;
    window._asl3State = window._asl3State || {};
    asl3Render();
  });
}

function asl3RunStep(btn, mode, distro, stepId) {
  var stateKey = mode + '_' + distro + '_' + stepId;
  var inputEl = document.getElementById('asl3-cmd-' + stateKey);
  var cmd = inputEl ? inputEl.value : '';
  if (!cmd.trim()) return;
  if (!confirm('Run this on the node?\\n\\n' + cmd)) return;
  window._asl3State = window._asl3State || {};
  window._asl3State[stateKey] = {status: 'attempted', output: ''};
  var pill = document.getElementById('asl3-pill-' + stateKey);
  if (pill) { pill.className = 'step-pill attempted_unconfirmed'; pill.textContent = 'Running\u2026'; }
  if (btn) btn.disabled = true;
  fetch('/api/asl3/action', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({mode: mode, distro: distro, step_id: stepId, command_text: cmd})
  }).then(function(r) { return r.json(); }).then(function(result) {
    window._asl3State[stateKey] = {status: result.success ? 'ok' : 'fail', output: result.output || ''};
    if (pill) { pill.className = 'step-pill ' + (result.success ? 'done' : 'danger'); pill.textContent = result.success ? 'OK' : 'Failed'; }
    var out = document.getElementById('asl3-out-' + stateKey);
    if (out) {
      out.className = 'asl3-console shown' + (result.success ? '' : ' fail');
      out.textContent = result.output || '';
    }
    if (btn) btn.disabled = false;
  }).catch(function(e) {
    if (pill) { pill.className = 'step-pill danger'; pill.textContent = 'Failed'; }
    var out = document.getElementById('asl3-out-' + stateKey);
    if (out) { out.className = 'asl3-console shown fail'; out.textContent = 'Request failed: ' + e; }
    if (btn) btn.disabled = false;
  });
}

function asl3TogglePurge() {
  if (window._asl3PurgeShown) {
    document.getElementById('asl3-purge-steps').innerHTML = '';
    window._asl3PurgeShown = false;
    return;
  }
  var distro = asl3CurrentDistro();
  if (distro === 'custom') { alert('Select Bookworm or Trixie first \u2014 Purge is not defined for Custom mode.'); return; }
  if (!confirm('This will show the purge steps for removing a previous ASL3 install (' + distro + '). Continue?')) return;
  if (!confirm('Are you sure? Purge steps are destructive and cannot be undone automatically. Confirm again to show them.')) return;
  document.getElementById('asl3-purge-steps').innerHTML = asl3RenderStepList('purge', distro);
  window._asl3PurgeShown = true;
}

function asl3CustomRun() {
  var inputEl = document.getElementById('asl3-custom-input');
  var cmd = inputEl.value.trim();
  if (!cmd) return;
  if (!confirm('Run this on the node?\\n\\n' + cmd)) return;
  var transcript = document.getElementById('asl3-custom-transcript');
  transcript.textContent += '$ ' + cmd + '\\n(running...)\\n';
  transcript.scrollTop = transcript.scrollHeight;
  fetch('/api/asl3/action', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({mode: 'custom', command_text: cmd})
  }).then(function(r) { return r.json(); }).then(function(result) {
    transcript.textContent = transcript.textContent.replace('(running...)\\n', (result.output || '(no output)') + '\\n');
    transcript.scrollTop = transcript.scrollHeight;
  }).catch(function(e) {
    transcript.textContent = transcript.textContent.replace('(running...)\\n', 'Request failed: ' + e + '\\n');
    transcript.scrollTop = transcript.scrollHeight;
  });
  inputEl.value = '';
}
"""

_JS = (
    _JS_TABS
    + _JS_OVERVIEW
    + _JS_PI_INSTALL
    + _JS_NODES
    + _JS_INIT
    + _JS_ROUTER_INSTALL
    + _JS_SERVICES_PORTS
    + _JS_FIREWALL
    + _JS_ACTIONS_LOG
    + _JS_ASL3
)


def _render_tab_bar() -> str:
    buttons = []
    for tab_id, label, css_class, _stage in TABS:
        buttons.append(
            f'<div class="tab {css_class}" id="tab-{tab_id}" '
            f'onclick="clickTab(\'{tab_id}\')">{label}</div>'
        )
        if tab_id == "nodes":
            buttons.append('<div class="tab-break"></div>')
    return '<div class="tabs">' + "".join(buttons) + "</div>"


def _render_services_panel() -> str:
    return """
<div class="tab-panel hidden" id="panel-services">
  <div id="svc-groups"></div>
  <button class="btn-recheck" onclick="refreshServices()">Re-check</button>
  <span style="font-family:var(--mono);font-size:.7rem;color:var(--muted);margin-left:.6rem" id="svc-checked-at"></span>
</div>
"""


def _render_ports_panel() -> str:
    return """
<div class="tab-panel hidden" id="panel-ports">
  <div class="step-body" id="ports-source" style="margin-bottom:.6rem"></div>
  <table id="ports-table" style="width:100%;border-collapse:collapse;font-family:var(--mono);font-size:.8rem"></table>
  <button class="btn-recheck" onclick="refreshPorts()">Re-check</button>
  <span style="font-family:var(--mono);font-size:.7rem;color:var(--muted);margin-left:.6rem" id="ports-checked-at"></span>
</div>
"""


def _render_firewall_panel() -> str:
    return """
<div class="tab-panel hidden" id="panel-firewall">
  <div id="fw-guardrail"></div>
  <div class="step-card"><div class="step-head"><div class="step-title">Pi: 44NetConnect zone</div></div>
    <div class="step-body" id="fw-pi-zone">...</div>
    <div class="checklist">
      <label>Add service: <select id="fw-add-service"><option value="iax2">iax2</option><option value="echolink">echolink</option><option value="rtcm">rtcm</option></select>
      <button class="btn-run" onclick="fwAddService()">Add</button></label>
      <label>Remove service: <input type="text" id="fw-rm-service" placeholder="iax2" style="font-family:var(--mono);background:#0a1020;color:var(--text-bright);border:1px solid var(--border2);border-radius:4px;padding:.2rem .4rem">
      <button class="btn-run" onclick="fwRemoveService()">Remove</button></label><br>
      <label>Add port (e.g. 14569/udp): <input type="text" id="fw-add-port" style="font-family:var(--mono);background:#0a1020;color:var(--text-bright);border:1px solid var(--border2);border-radius:4px;padding:.2rem .4rem">
      <button class="btn-run" onclick="fwAddPort()">Add</button></label>
      <label>Remove port: <input type="text" id="fw-rm-port" style="font-family:var(--mono);background:#0a1020;color:var(--text-bright);border:1px solid var(--border2);border-radius:4px;padding:.2rem .4rem">
      <button class="btn-run" onclick="fwRemovePort()">Remove</button></label>
    </div>
    <div class="step-body" id="fw-out-pi"></div>
  </div>
  <div class="step-card"><div class="step-head"><div class="step-title">Router: live port-forward table</div></div>
    <div class="step-body" id="fw-router-forwards">...</div>
  </div>
  <button class="btn-recheck" onclick="refreshFirewall()">Re-check</button>
  <span style="font-family:var(--mono);font-size:.7rem;color:var(--muted);margin-left:.6rem" id="fw-checked-at"></span>
</div>
"""


def _render_actions_log_panel() -> str:
    return """
<div class="tab-panel hidden" id="panel-actions_log">
  <div class="step-card"><div class="step-head"><div class="step-title">Session log</div></div>
    <div id="log-lines" style="font-family:var(--mono);font-size:.77rem;max-height:360px;overflow-y:auto;line-height:1.6"></div>
    <button class="btn-recheck" onclick="refreshActionsLog()">Refresh</button>
  </div>
  <div class="step-card"><div class="step-head"><div class="step-title">Known-good router notes</div></div>
    <div id="notes-list" class="step-body">...</div>
    <div id="note-view" class="cmd-preview" style="display:none;white-space:pre-wrap;max-height:300px;overflow-y:auto"></div>
  </div>
</div>
"""


def _render_asl3_panel() -> str:
    return """
<div class="tab-panel hidden" id="panel-asl3">
  <div class="step-warn">Stage 1: engine + real Bookworm/Trixie install steps. Purge lists are placeholders
  only. Two install steps (Allmon3 admin password, asl-menu) are interactive prompts this engine cannot
  drive — they will very likely hang until timeout as written; confirm during your live test pass.</div>
  <div class="asl3-topbar">
    <label style="font-family:var(--mono);font-size:.8rem;color:var(--muted)">Script:
      <select id="asl3-distro" onchange="asl3OnDistroChange()">
        <option value="bookworm">Bookworm (Debian 12)</option>
        <option value="trixie">Trixie (Debian 13)</option>
        <option value="custom">Custom</option>
      </select>
    </label>
    <button class="btn-purge" id="asl3-purge-btn" onclick="asl3TogglePurge()">Purge previous install</button>
  </div>
  <div id="asl3-purge-steps"></div>
  <div id="asl3-steps"></div>
  <div id="asl3-custom" style="display:none">
    <div class="step-card">
      <div class="step-head"><div class="step-title">Custom command</div></div>
      <input type="text" class="asl3-cmd-input" id="asl3-custom-input" placeholder="Type or paste a command line...">
      <div class="step-actions"><button class="btn-run" onclick="asl3CustomRun()">Run</button></div>
    </div>
    <div id="asl3-custom-transcript"></div>
  </div>
</div>
"""


def _render_panel(tab_id: str, label: str, stage: str) -> str:
    return f"""
<div class="tab-panel hidden" id="panel-{tab_id}">
  <div class="stub-card">
    <span class="stub-title">{label} — not yet implemented</span>
    Lands in <span class="stub-stage">{stage}</span> of the staged build
    (see design plan §11). This is a Stage 2 skeleton build — no
    firewall/router mutating logic wired up yet outside the self-installer.
  </div>
</div>
"""


def _render_router_install_panel() -> str:
    return """
<div class="tab-panel hidden" id="panel-router_install">
  <div class="step-warn">
    Per design plan §1a.5/§1b: ARDC documents no router path officially.
    A detailed community guide exists for the GL.iNet family specifically
    and is used as a verified starting template for those models;
    anything else is best-effort. SSH access only in this stage — no
    mutating actions against the router happen until Stage 5/6.
  </div>
  <div id="router-steps"></div>
  <span style="font-family:var(--mono);font-size:.7rem;color:var(--muted)" id="router-checked-at"></span>
</div>
"""


def _render_pi_install_panel() -> str:
    return """
<div class="tab-panel hidden" id="panel-pi_install">
  <div class="step-warn">
    Base tunnel setup below follows ARDC's own generic 44Net Connect
    procedure (design plan §1a); the service/port checklist step is an
    ASL3-Appliance-specific hardening layer on top, not a universal 44Net
    Connect requirement.
  </div>
  <div id="pi-steps"></div>
  <span style="font-family:var(--mono);font-size:.7rem;color:var(--muted)" id="pi-checked-at"></span>
</div>
"""


def _render_overview_panel() -> str:
    return """
<div class="tab-panel" id="panel-overview">
  <div id="ov-banner" class="ov-banner lvl-info">Checking…</div>

  <div class="ov-grid">
    <div class="ov-card">
      <span class="ov-card-title">Tunnel / wg0</span>
      <div class="ov-card-body" id="ov-wg0">…</div>
    </div>
    <div class="ov-card">
      <span class="ov-card-title">Configured tunnels</span>
      <div class="ov-card-body" id="ov-tunnels">…</div>
    </div>
    <div class="ov-card">
      <span class="ov-card-title">44NetConnect firewall zone</span>
      <div class="ov-card-body" id="ov-firewall">…</div>
    </div>
    <div class="ov-card">
      <span class="ov-card-title">Self-check findings</span>
      <div class="ov-card-body" id="ov-findings">…</div>
    </div>
  </div>

  <button class="btn-recheck" onclick="refreshOverview()">Re-check</button>
  <span style="font-family:var(--mono);font-size:.7rem;color:var(--muted);margin-left:.6rem" id="ov-checked-at"></span>
</div>
"""


def _render_nodes_panel() -> str:
    return """
<div class="tab-panel hidden" id="panel-nodes">
  <div id="nd-banner" class="ov-banner lvl-info">Checking…</div>

  <div class="step-card">
    <div class="step-head"><div class="step-title">This Box</div></div>
    <div class="step-body" id="nd-box-body">…</div>
  </div>

  <div class="step-card">
    <div class="step-head"><div class="step-title">Local Nodes</div></div>
    <div id="nd-local-cards" class="step-body">…</div>
  </div>

  <div class="step-card">
    <div class="step-head"><div class="step-title">Peer Nodes</div></div>
    <div id="nd-peer-cards" class="step-body">…</div>
    <div class="checklist">
      <label>Node #: <input type="text" id="nd-peer-node" style="font-family:var(--mono);background:#0a1020;color:var(--text-bright);border:1px solid var(--border2);border-radius:4px;padding:.2rem .4rem;width:90px"></label>
      <label>IP: <input type="text" id="nd-peer-ip" placeholder="192.168.0.11" style="font-family:var(--mono);background:#0a1020;color:var(--text-bright);border:1px solid var(--border2);border-radius:4px;padding:.2rem .4rem;width:140px"></label>
      <label>Port: <input type="text" id="nd-peer-port" placeholder="4570" style="font-family:var(--mono);background:#0a1020;color:var(--text-bright);border:1px solid var(--border2);border-radius:4px;padding:.2rem .4rem;width:80px"></label>
      <label>Label: <input type="text" id="nd-peer-label" style="font-family:var(--mono);background:#0a1020;color:var(--text-bright);border:1px solid var(--border2);border-radius:4px;padding:.2rem .4rem;width:160px"></label>
      <label>44helper URL: <input type="text" id="nd-peer-url" placeholder="http://192.168.0.11:9998" style="font-family:var(--mono);background:#0a1020;color:var(--text-bright);border:1px solid var(--border2);border-radius:4px;padding:.2rem .4rem;width:220px"></label>
      <button class="btn-run" onclick="ndPeerSave()">Add / Update Peer</button>
    </div>
  </div>

  <button class="btn-recheck" onclick="refreshNodes()">Re-check</button>
  <span style="font-family:var(--mono);font-size:.7rem;color:var(--muted);margin-left:.6rem" id="nd-checked-at"></span>
</div>
"""


_PANEL_RENDERERS: dict[str, Callable[[], str]] = {
    "overview": _render_overview_panel,
    "pi_install": _render_pi_install_panel,
    "router_install": _render_router_install_panel,
    "nodes": _render_nodes_panel,
    "asl3": _render_asl3_panel,
    "services": _render_services_panel,
    "ports": _render_ports_panel,
    "firewall": _render_firewall_panel,
    "actions_log": _render_actions_log_panel,
}


def render_page(cfg: configparser.ConfigParser) -> str:
    callsign = cfg.get("identity", "callsign", fallback="").strip()
    node = cfg.get("identity", "node", fallback="").strip()
    identity_bits = []
    if callsign:
        identity_bits.append(callsign)
    if node:
        identity_bits.append(f"Node {node}")
    identity_line = " · ".join(identity_bits) if identity_bits else "Deployment model: not configured"

    panels = "".join(
        _PANEL_RENDERERS[t_id]()
        if t_id in _PANEL_RENDERERS
        else _render_panel(t_id, label, stage)
        for t_id, label, _cls, stage in TABS
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{APP_TITLE}</title>
<style>{_CSS}</style>
</head>
<body>
<header>
  <div class="hdr-left">
    <div class="logo">{APP_TITLE}</div>
    <div class="logo-sub">{identity_line}</div>
  </div>
  <div class="hdr-right">
    <span id="hdr-uptime">v{APP_VERSION} — {APP_STAGE}</span>
  </div>
</header>
<div class="wrap">
  {_render_tab_bar()}
  {panels}
  <div class="ver-tag">asl_dvs_m17_44helper_v{APP_VERSION}.py — stage {APP_STAGE.split(' ')[0]} of 8 — reference copy, not release-stripped</div>
</div>
<script>{_JS}</script>
</body>
</html>
"""






def _route_index(query: dict) -> tuple[int, str, bytes]:
    return 200, "text/html; charset=utf-8", render_page(_cfg).encode("utf-8")


def _route_version(query: dict) -> tuple[int, str, bytes]:
    payload = {"app": APP_TITLE, "version": APP_VERSION, "stage": APP_STAGE}
    return 200, "application/json", json.dumps(payload).encode("utf-8")


def _route_log(query: dict) -> tuple[int, str, bytes]:
    return 200, "application/json", json.dumps(get_log_lines()).encode("utf-8")


def _route_overview(query: dict) -> tuple[int, str, bytes]:
    return 200, "application/json", json.dumps(build_overview_data(_cfg)).encode("utf-8")


def _route_pi_install_status(query: dict) -> tuple[int, str, bytes]:
    return 200, "application/json", json.dumps(build_pi_install_status(_cfg)).encode("utf-8")


def _route_nodes_status(query: dict) -> tuple[int, str, bytes]:
    body = json.dumps(build_nodes_tab_data(_cfg, probe_peers=True)).encode("utf-8")
    return 200, "application/json", body


def _route_nodes_edit_snippet(query: dict) -> tuple[int, str, bytes]:
    scope = query.get("scope", [""])[0]
    return 200, "application/json", json.dumps(build_node_snippet(_cfg, scope)).encode("utf-8")


def _route_pi_install_verify(query: dict) -> tuple[int, str, bytes]:
    result = {"myip": check_myip(), "rpt": check_rpt_registrations()}
    return 200, "application/json", json.dumps(result).encode("utf-8")


def _route_router_status(query: dict) -> tuple[int, str, bytes]:
    force = query.get("force", ["0"])[0] == "1"
    probe = get_router_status(_cfg, force=force)
    cfg_view = {
        "access_method": _cfg.get("router", "access_method", fallback="none"),
        "host": _cfg.get("router", "host", fallback=""),
        "user": _cfg.get("router", "user", fallback=""),
        "key_path": _cfg.get("router", "key_path", fallback=""),
        "poll_interval_sec": _cfg.get("router", "poll_interval_sec", fallback="60"),
    }
    body = json.dumps({
        "config": cfg_view,
        "probe": probe,
        "checked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }).encode("utf-8")
    return 200, "application/json", body


def _route_router_install_status(query: dict) -> tuple[int, str, bytes]:
    return 200, "application/json", json.dumps(build_router_install_status(_cfg)).encode("utf-8")


def _route_services_status(query: dict) -> tuple[int, str, bytes]:
    return 200, "application/json", json.dumps(build_services_status(_cfg)).encode("utf-8")


def _route_ports_status(query: dict) -> tuple[int, str, bytes]:
    return 200, "application/json", json.dumps(build_ports_status(_cfg)).encode("utf-8")


def _route_firewall_status(query: dict) -> tuple[int, str, bytes]:
    return 200, "application/json", json.dumps(build_firewall_status(_cfg)).encode("utf-8")


def _route_actions_log_notes(query: dict) -> tuple[int, str, bytes]:
    body = json.dumps(list_known_good_router_notes()).encode("utf-8")
    return 200, "application/json", body


def _route_asl3_script(query: dict) -> tuple[int, str, bytes]:
    return 200, "application/json", json.dumps(_ASL3_SCRIPTS).encode("utf-8")


_GET_ROUTES: dict[str, Callable[[dict], tuple[int, str, bytes]]] = {
    "/": _route_index,
    "/index.html": _route_index,
    "/api/version": _route_version,
    "/api/log": _route_log,
    "/api/overview": _route_overview,
    "/api/pi_install/status": _route_pi_install_status,
    "/api/nodes/status": _route_nodes_status,
    "/api/nodes/edit_snippet": _route_nodes_edit_snippet,
    "/api/pi_install/verify": _route_pi_install_verify,
    "/api/router/status": _route_router_status,
    "/api/router_install/status": _route_router_install_status,
    "/api/services/status": _route_services_status,
    "/api/ports/status": _route_ports_status,
    "/api/firewall/status": _route_firewall_status,
    "/api/actions_log/notes": _route_actions_log_notes,
    "/api/asl3/script": _route_asl3_script,
}



_PI_INSTALL_SIMPLE_ACTIONS: dict[str, Callable[[dict], dict]] = {
    "firewalld_prereq": lambda p: action_install_firewalld(),
    "resolved_prereq": lambda p: action_install_resolved(),
    "create_zone": lambda p: action_create_zone(),
    "paste_config": lambda p: action_paste_config(p.get("config_text", "")),
    "attach_interface": lambda p: action_attach_interface(),
    "enable_tunnel": lambda p: action_enable_tunnel(),
}
_PI_INSTALL_SERVICE_PORTS_ACTIONS: dict[str, Callable[[dict], dict]] = {
    "add_service": lambda p: action_add_service(p.get("service", "")),
    "add_port": lambda p: action_add_port(p.get("port", "")),
}


def _dispatch_pi_install_action(payload: dict) -> dict:
    step = payload.get("step", "")
    action = payload.get("action", step)
    if step in _PI_INSTALL_SIMPLE_ACTIONS:
        return _PI_INSTALL_SIMPLE_ACTIONS[step](payload)
    if step == "service_ports" and action in _PI_INSTALL_SERVICE_PORTS_ACTIONS:
        return _PI_INSTALL_SERVICE_PORTS_ACTIONS[action](payload)
    return {"success": False, "verified": False, "output": f"Unknown step/action: {step}/{action}"}


def _router_action_verify(payload: dict) -> dict:
    mode = _cfg.get("tunnels", "tunnel.router.mode", fallback="")
    if mode == "router_single":
        result = check_model_b_verify(_cfg)
    else:
        result = check_ping_traceroute_44()
    if result.get("success"):
        if "tunnels" not in _cfg:
            _cfg["tunnels"] = {}
        _cfg["tunnels"]["tunnel.router.verified"] = "true"
        save_config(_cfg)
    return result


_ROUTER_INSTALL_ACTIONS: dict[str, Callable[[dict], dict]] = {
    "install_luci": lambda p: action_install_luci(_cfg),
    "allocation_type": lambda p: action_set_allocation_type(_cfg, p.get("mode", "")),
    "capture_config": lambda p: action_capture_router_config(
        _cfg, p.get("config_text", ""), p.get("lan_subnet", "")
    ),
    "apply_wg_config": lambda p: action_apply_router_wg_config(_cfg),
    "set_lan_ip": lambda p: action_set_router_lan_ip(_cfg),
    "bring_up_tunnel": lambda p: action_bring_up_router_tunnel(_cfg),
    "pi_address_lookup": lambda p: action_lookup_pi_address(_cfg),
    "pi_address_bind": lambda p: action_add_static_binding(_cfg),
    "firewall_zone": lambda p: action_fix_wireguard_zone(_cfg),
    "add_port_forward": lambda p: action_add_port_forward(
        _cfg, p.get("name", ""), p.get("port", ""), p.get("proto", "")
    ),
    "verify": _router_action_verify,
    "save_note": lambda p: save_known_good_router_note(_cfg, get_router_status(_cfg)),
}


def _dispatch_router_install_action(payload: dict) -> dict:
    step = payload.get("step", "")
    handler_fn = _ROUTER_INSTALL_ACTIONS.get(step)
    if handler_fn is not None:
        return handler_fn(payload)
    return {"success": False, "verified": False, "output": f"Unknown step: {step}"}


_FIREWALL_ACTIONS: dict[str, Callable[[dict], dict]] = {
    "add_service": lambda p: action_add_service(p.get("service", "")),
    "remove_service": lambda p: action_remove_zone_service(_cfg, p.get("service", "")),
    "add_port": lambda p: action_add_port(p.get("port", "")),
    "remove_port": lambda p: action_remove_zone_port(_cfg, p.get("port", "")),
    "remove_forward": lambda p: action_remove_port_forward(_cfg, p.get("redirect_id", "")),
}


def _dispatch_firewall_action(payload: dict) -> dict:
    action = payload.get("action", "")
    handler_fn = _FIREWALL_ACTIONS.get(action)
    if handler_fn is not None:
        return handler_fn(payload)
    return {"success": False, "verified": False, "output": f"Unknown action: {action}"}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:
        log(f"HTTP {self.address_string()} - {fmt % args}")

    def _send(self, status: int, content_type: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self) -> tuple[dict | None, bytes | None]:
        length = int(self.headers.get("Content-Length", 0))
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return None, b'{"success": false, "output": "bad JSON"}'
        return payload, None

    def do_GET(self) -> None:
        parsed = urllib.parse.urlsplit(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        if path.startswith("/api/actions_log/notes/"):
            filename = urllib.parse.unquote(path[len("/api/actions_log/notes/"):])
            content = read_known_good_router_note(filename)
            if content is None:
                self._send(404, "text/plain; charset=utf-8", b"not found")
                return
            self._send(200, "text/plain; charset=utf-8", content.encode("utf-8"))
            return

        route_fn = _GET_ROUTES.get(path)
        if route_fn is not None:
            status, content_type, body = route_fn(query)
            self._send(status, content_type, body)
            return

        self._send(404, "text/plain; charset=utf-8", b"not found")

    def do_POST(self) -> None:
        parsed = urllib.parse.urlsplit(self.path)
        path = parsed.path

        if path == "/api/router/config":
            payload, err = self._read_json_body()
            if err is not None:
                self._send(400, "application/json", err)
                return
            result = save_router_config(
                _cfg,
                payload.get("access_method", "none"),
                payload.get("host", ""),
                payload.get("user", ""),
                payload.get("key_path", ""),
                payload.get("poll_interval_sec", "60"),
            )
            self._send(200, "application/json", json.dumps(result).encode("utf-8"))
            return

        if path == "/api/pi_install/action":
            payload, err = self._read_json_body()
            if err is not None:
                self._send(400, "application/json", err)
                return
            result = _dispatch_pi_install_action(payload)
            self._send(200, "application/json", json.dumps(result).encode("utf-8"))
            return

        if path == "/api/router_install/action":
            payload, err = self._read_json_body()
            if err is not None:
                self._send(400, "application/json", err)
                return
            result = _dispatch_router_install_action(payload)
            self._send(200, "application/json", json.dumps(result).encode("utf-8"))
            return

        if path == "/api/firewall/action":
            payload, err = self._read_json_body()
            if err is not None:
                self._send(400, "application/json", err)
                return
            result = _dispatch_firewall_action(payload)
            self._send(200, "application/json", json.dumps(result).encode("utf-8"))
            return

        if path in ("/api/nodes/peer_add", "/api/nodes/peer_edit"):
            payload, err = self._read_json_body()
            if err is not None:
                self._send(400, "application/json", err)
                return
            result = action_upsert_peer(
                _cfg,
                str(payload.get("node", "")).strip(),
                str(payload.get("ip", "")).strip(),
                str(payload.get("port", "")).strip(),
                str(payload.get("label", "")).strip(),
                str(payload.get("helper_url", "")).strip(),
            )
            self._send(200, "application/json", json.dumps(result).encode("utf-8"))
            return

        if path == "/api/nodes/peer_remove":
            payload, err = self._read_json_body()
            if err is not None:
                self._send(400, "application/json", err)
                return
            result = action_remove_peer(_cfg, str(payload.get("node", "")).strip())
            self._send(200, "application/json", json.dumps(result).encode("utf-8"))
            return

        if path == "/api/nodes/save_snippet":
            payload, err = self._read_json_body()
            if err is not None:
                self._send(400, "application/json", err)
                return
            result = action_save_node_snippet(
                _cfg,
                str(payload.get("scope", "")).strip(),
                str(payload.get("text", "")),
            )
            self._send(200, "application/json", json.dumps(result).encode("utf-8"))
            return

        if path == "/api/asl3/action":
            payload, err = self._read_json_body()
            if err is not None:
                self._send(400, "application/json", err)
                return
            result = _dispatch_asl3_action(payload)
            self._send(200, "application/json", json.dumps(result).encode("utf-8"))
            return

        self._send(404, "text/plain; charset=utf-8", b"not found")


class _QuietThreadingHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True



_cfg: configparser.ConfigParser


def main() -> None:
    global _cfg
    _cfg = load_config()

    host = _cfg.get("server", "host", fallback="0.0.0.0")
    port = _cfg.getint("server", "port", fallback=9997)

    log(f"{APP_TITLE} v{APP_VERSION} ({APP_STAGE}) starting on {host}:{port}")

    server = _QuietThreadingHTTPServer((host, port), Handler)

    def _sigterm(signum, frame):
        log("SIGTERM received, shutting down")
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, _sigterm)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log("KeyboardInterrupt, shutting down")
        server.shutdown()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=f"{APP_TITLE} — 44Net Connect / firewall / router dashboard"
    )
    parser.add_argument("--install", action="store_true", help="Install as a systemd service & start")
    parser.add_argument("--uninstall", action="store_true", help="Stop & remove the systemd service")
    args = parser.parse_args()

    if args.install:
        install_service()
    elif args.uninstall:
        uninstall_service()
    else:
        main()
