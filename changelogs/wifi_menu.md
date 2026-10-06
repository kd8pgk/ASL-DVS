# wifi_menu.sh changelog

Current file: `wifi_menu.sh`. Newest entries first.

## Unversioned (2026-10-06)

- No code change. Repo copy is comment-stripped. The change history that was in the file's comments now lives in this changelog.


## Earlier history

Carried over unchanged from the comments of the files below.

### wifi_menu.sh (header comments)

```text
wifi-menu.sh - Simple WiFi status & switch menu using nmcli
Run with: bash wifi-menu.sh   (or make executable: chmod +x wifi-menu.sh)

v2 - Audit fixes:
  - select_interface() no longer leaks its menu text into the returned
    interface name (was corrupting every downstream nmcli call whenever
    more than one WiFi device was present)
  - connect_target() no longer deletes existing saved profiles before
    confirming the new connection succeeds
  - password read uses -r (no backslash mangling)
  - confirmation prompts added before disconnect / delete actions
  - network list is sorted by signal BEFORE de-duplicating by SSID
  - fixed 2s post-rescan sleep replaced with a short poll
  - single-choice-from-list logic consolidated into one helper with
    consistent (non-silent-fallback) invalid-input handling
  - hidden network connect now asks open vs. secured instead of assuming WPA2

v3 - External review follow-ups:
  - connect_target() profile cleanup uses exact-string SSID matching
    (awk) instead of treating the SSID as a grep -E regex, so SSIDs with
    characters like . * [ ] ? can no longer match/delete the wrong profile
  - active WiFi connection detection no longer assumes interface names
    contain "wl" - now derived from device TYPE=wifi/STATE=connected
  - saved connection names containing a literal colon are no longer
    truncated when listed/selected in list_saved_connections()
  - SIGNAL field is validated as numeric before -gt/-le comparisons,
    preventing a set -e crash on an empty/non-numeric scan result
```
