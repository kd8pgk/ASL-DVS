#!/usr/bin/env bash
# wifi-menu.sh - Simple WiFi status & switch menu using nmcli
# Run with: bash wifi-menu.sh   (or make executable: chmod +x wifi-menu.sh)
#
# v2 - Audit fixes:
#   - select_interface() no longer leaks its menu text into the returned
#     interface name (was corrupting every downstream nmcli call whenever
#     more than one WiFi device was present)
#   - connect_target() no longer deletes existing saved profiles before
#     confirming the new connection succeeds
#   - password read uses -r (no backslash mangling)
#   - confirmation prompts added before disconnect / delete actions
#   - network list is sorted by signal BEFORE de-duplicating by SSID
#   - fixed 2s post-rescan sleep replaced with a short poll
#   - single-choice-from-list logic consolidated into one helper with
#     consistent (non-silent-fallback) invalid-input handling
#   - hidden network connect now asks open vs. secured instead of assuming WPA2
#
# v3 - External review follow-ups:
#   - connect_target() profile cleanup uses exact-string SSID matching
#     (awk) instead of treating the SSID as a grep -E regex, so SSIDs with
#     characters like . * [ ] ? can no longer match/delete the wrong profile
#   - active WiFi connection detection no longer assumes interface names
#     contain "wl" - now derived from device TYPE=wifi/STATE=connected
#   - saved connection names containing a literal colon are no longer
#     truncated when listed/selected in list_saved_connections()
#   - SIGNAL field is validated as numeric before -gt/-le comparisons,
#     preventing a set -e crash on an empty/non-numeric scan result

set -euo pipefail

# Colors for nicer output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m' # No Color

# Restore terminal echo if a `read -s` is interrupted with Ctrl+C
trap 'stty echo 2>/dev/null || true' EXIT

# Function to detect WiFi devices
get_wifi_devices() {
    nmcli device 2>/dev/null | awk '$2 == "wifi" {print $1}' | sort || true
}

# Generic "pick one item from a numbered list" helper.
# Prints ONLY the chosen item to stdout; everything else (prompts, menu,
# errors) goes to stderr so callers can safely use $(choose_from_list ...).
# Returns 1 (nothing printed) on cancel or invalid input - callers must check.
#
# Usage: choose_from_list "Prompt text" "${array[@]}"
choose_from_list() {
    local prompt="$1"; shift
    local -a items=("$@")

    if [[ ${#items[@]} -eq 0 ]]; then
        return 1
    fi

    if [[ ${#items[@]} -eq 1 ]]; then
        echo "${items[0]}"
        return 0
    fi

    echo -e "${BLUE}${prompt}${NC}" >&2
    local i=1
    for item in "${items[@]}"; do
        echo "  $i) $item" >&2
        ((i++))
    done
    echo "  q) Cancel" >&2
    echo "" >&2

    local choice
    read -p "Choice: " -r choice >&2
    if [[ "$choice" =~ ^[qQ]$ ]]; then
        return 1
    fi

    if ! [[ "$choice" =~ ^[0-9]+$ ]] || (( choice < 1 || choice > ${#items[@]} )); then
        echo -e "${RED}✗ Invalid choice.${NC}" >&2
        return 1
    fi

    echo "${items[$((choice-1))]}"
    return 0
}

# Ask a yes/no question. Returns 0 for yes, 1 for no/anything else.
confirm() {
    local prompt="$1"
    local ans
    read -p "$(echo -e "${YELLOW}${prompt} [y/N]: ${NC}")" -r ans
    [[ "$ans" =~ ^[yY]$ ]]
}

# Function to show current status
show_status() {
    clear
    echo -e "${BOLD}${BLUE}+--------------------------------------------+${NC}"
    echo -e "${BOLD}${BLUE}|          WiFi Status & Manager             |${NC}"
    echo -e "${BOLD}${BLUE}+--------------------------------------------+${NC}\n"

    local radio_status
    radio_status=$(nmcli radio wifi 2>/dev/null || echo "unknown")

    if [[ "$radio_status" == "enabled" ]]; then
        echo -e "${GREEN}✓${NC} WiFi radio: ${BOLD}${GREEN}ENABLED${NC}"
    else
        echo -e "${RED}✗${NC} WiFi radio: ${BOLD}${RED}DISABLED${NC}"
    fi
    echo ""

    echo -e "${CYAN}Available WiFi interfaces:${NC}"
    local devices_output
    devices_output=$(nmcli -c no -f DEVICE,STATE,TYPE,CONNECTION device 2>/dev/null | grep wifi || true)

    if [[ -n "$devices_output" ]]; then
        echo "$devices_output" | awk '{printf "   %-12s %-15s %s\n", $1, $2, $4}'
    else
        echo -e "   ${YELLOW}(none found)${NC}"
    fi
    echo ""

    echo -e "${CYAN}Active WiFi connection:${NC}"
    # Identify the active WiFi connection by device TYPE and STATE rather
    # than assuming the interface name contains "wl" - not all systems
    # follow that naming convention (predictable names, USB adapters, etc).
    local active_con
    active_con=$(nmcli -t -f DEVICE,STATE,TYPE,CONNECTION device 2>/dev/null \
        | awk -F: '$2 == "connected" && $3 == "wifi" {print $4 ":" $1}')

    if [[ -n "$active_con" ]]; then
        local con_name device
        con_name=$(echo "$active_con" | cut -d: -f1)
        device=$(echo "$active_con" | cut -d: -f2)

        local signal
        signal=$(nmcli -t -f IN-USE,SIGNAL dev wifi 2>/dev/null | grep '^\*' | cut -d: -f2 || echo "?")

        echo -e "   ${GREEN}${con_name}${NC} on ${BOLD}${device}${NC} (Signal: ${signal}%)"
    else
        echo -e "   ${RED}None${NC}"
    fi
    echo ""
}

# Function to switch active WiFi device
switch_device() {
    local devices
    readarray -t devices < <(get_wifi_devices)

    if [[ ${#devices[@]} -eq 0 ]]; then
        echo -e "${RED}✗ No WiFi devices found.${NC}"
        read -p "Press Enter to continue..." -r
        return
    elif [[ ${#devices[@]} -eq 1 ]]; then
        echo -e "${YELLOW}Only one WiFi device: ${devices[0]}${NC}"
        read -p "Press Enter to continue..." -r
        return
    fi

    local selected_dev
    if ! selected_dev=$(choose_from_list "Select WiFi device to activate:" "${devices[@]}"); then
        return
    fi

    echo -e "\n${YELLOW}Bringing up ${selected_dev}...${NC}"

    if nmcli device connect "$selected_dev" 2>/dev/null; then
        echo -e "${GREEN}✓ Successfully connected ${selected_dev}${NC}"
    else
        echo -e "${RED}✗ Failed to connect ${selected_dev}${NC}"
    fi

    read -p "Press Enter to continue..." -r
}

# Function to disconnect active WiFi
disconnect_wifi() {
    local devices
    readarray -t devices < <(get_wifi_devices)

    if [[ ${#devices[@]} -eq 0 ]]; then
        echo -e "${RED}✗ No WiFi devices found.${NC}"
        read -p "Press Enter to continue..." -r
        return
    fi

    local iface
    if [[ ${#devices[@]} -eq 1 ]]; then
        iface="${devices[0]}"
    else
        if ! iface=$(choose_from_list "Select WiFi interface to disconnect:" "${devices[@]}"); then
            return
        fi
    fi

    if ! confirm "Disconnect interface ${iface}? This may drop an active SSH session."; then
        echo -e "${YELLOW}Cancelled.${NC}"
        read -p "Press Enter to continue..." -r
        return
    fi

    echo -e "${YELLOW}Disconnecting interface ${iface}...${NC}"

    if nmcli device disconnect "$iface" 2>/dev/null; then
        echo -e "${GREEN}✓ Successfully disconnected.${NC}"
    else
        echo -e "${RED}✗ Failed to disconnect or device already disconnected.${NC}"
    fi

    read -p "Press Enter to continue..." -r
}

# Helper function to prompt for interface if multiple exist.
# Prints ONLY the chosen interface name to stdout.
select_interface() {
    local devices
    readarray -t devices < <(get_wifi_devices)

    if [[ ${#devices[@]} -eq 0 ]]; then
        return 1
    fi

    choose_from_list "Select WiFi interface to use:" "${devices[@]}"
}

# Robust connection handler supporting open and secured connections safely.
# Does NOT touch existing saved profiles unless the new connection succeeds,
# so a failed attempt (bad password, busy radio) never leaves you with
# nothing usable.
connect_target() {
    local ssid="$1"
    local iface="$2"
    local sec="$3"

    local needs_password=true
    if [[ "$sec" == "--" || "$sec" == "none" || -z "$sec" ]]; then
        needs_password=false
    fi

    local connect_ok=false

    if [[ "$needs_password" == false ]]; then
        echo -e "${YELLOW}Connecting to open network: ${GREEN}${ssid}${NC}"
        if nmcli device wifi connect "$ssid" ifname "$iface" 2>/dev/null; then
            connect_ok=true
        fi
    else
        echo ""
        read -s -p "Enter password for '${ssid}': " -r password
        echo ""

        if [[ -z "$password" ]]; then
            echo -e "${RED}✗ Password cannot be empty for secured networks.${NC}"
            return 1
        fi

        if nmcli device wifi connect "$ssid" password "$password" ifname "$iface" 2>/dev/null; then
            connect_ok=true
        fi
        unset password
    fi

    if [[ "$connect_ok" == true ]]; then
        echo -e "${GREEN}✓ Connected and saved successfully!${NC}"

        # Now that we KNOW the new connection works, clean up any older
        # duplicate/stale profiles for the same SSID (nmcli sometimes
        # creates "ssid-1", "ssid-2" style profiles on repeat connects).
        # The just-created active profile for this device is left alone.
        local active_con
        active_con=$(nmcli -t -f NAME,DEVICE connection show --active 2>/dev/null \
            | awk -F: -v dev="$iface" '$2 == dev {print $1}')

        # Exact-string match on the NAME field via awk - the SSID is NOT
        # treated as a regex here, so SSIDs containing characters like
        # . * [ ] ? + ( ) can't cause unintended profile matches/deletes.
        while IFS= read -r con_id; do
            [[ -z "$con_id" ]] && continue
            [[ "$con_id" == "$active_con" ]] && continue
            nmcli connection delete "$con_id" 2>/dev/null || true
        done < <(nmcli -t -f NAME,TYPE connection show 2>/dev/null | awk -F: -v ssid="$ssid" '$1 == ssid {print $1}')

        return 0
    else
        echo -e "${RED}✗ Connection failed (wrong password, or interface busy). Existing saved profiles were left untouched.${NC}"
        return 1
    fi
}

# Function to connect to a network (saved or new scans)
connect_menu() {
    local iface
    if ! iface=$(select_interface); then
        echo -e "${RED}✗ No WiFi devices found.${NC}"
        read -p "Press Enter to continue..." -r
        return
    fi

    echo -e "\n${BLUE}Scanning networks on ${BOLD}${iface}${NC}${BLUE}...${NC}"
    nmcli device wifi rescan ifname "$iface" 2>/dev/null || true

    # Poll briefly instead of a blind fixed sleep - bail out early once
    # results show up, cap wait time for slow hardware (e.g. Pi Zero 2W).
    local waited=0
    while (( waited < 5 )); do
        if [[ -n "$(nmcli -t -f SSID device wifi list ifname "$iface" 2>/dev/null)" ]]; then
            break
        fi
        sleep 1
        ((waited++))
    done

    local networks
    # Sort by signal strength FIRST, then de-duplicate by SSID, so that
    # when multiple APs share an SSID we keep the strongest one instead
    # of whichever happened to be listed first.
    mapfile -t networks < <(nmcli -t -f SSID,SIGNAL,SECURITY device wifi list ifname "$iface" 2>/dev/null \
        | sed 's/\\:/\x00/g' \
        | sort -t: -k2 -nr \
        | awk -F: '!seen[$1]++')

    if [[ ${#networks[@]} -eq 0 ]]; then
        echo -e "${RED}✗ No networks found.${NC}"
        read -p "Press Enter to continue..." -r
        return
    fi

    echo -e "\n${CYAN}Available networks (strongest first):${NC}\n"
    printf "${BOLD}%4s  %-32s  %6s  %s${NC}\n" "#" "SSID" "Signal" "Security"
    echo "------------------------------------------------------------"

    local i=1
    for net in "${networks[@]}"; do
        IFS=':' read -r ssid signal sec <<< "$net"
        ssid="${ssid//$'\x00'/:}"
        [[ -z "$ssid" ]] && ssid="(hidden)"

        local sig_color="$RED"
        local sig_display="$signal"
        if [[ "$signal" =~ ^[0-9]+$ ]]; then
            [[ "$signal" -gt 70 ]] && sig_color="$GREEN"
            [[ "$signal" -gt 40 && "$signal" -le 70 ]] && sig_color="$YELLOW"
        else
            # nmcli returned something non-numeric (empty, mid-scan glitch,
            # etc). Under set -e, feeding that straight into -gt/-le would
            # throw an integer-expression error and kill the script.
            sig_display="?"
        fi

        printf "%4d  %-32s  ${sig_color}%5s%%${NC}  %s\n" "$i" "$ssid" "$sig_display" "${sec:-open}"
        ((i++))
    done

    echo ""
    echo "  h) Connect to a hidden network"
    echo "  q) Cancel"
    echo ""
    read -p "Enter number or option: " -r choice

    if [[ "$choice" =~ ^[qQ]$ ]]; then
        return
    elif [[ "$choice" =~ ^[hH]$ ]]; then
        echo ""
        read -p "Enter hidden SSID name: " -r hidden_ssid
        if [[ -z "$hidden_ssid" ]]; then
            echo -e "${RED}✗ SSID cannot be empty.${NC}"
            read -p "Press Enter to continue..." -r
            return
        fi

        local hidden_sec
        read -p "Is it secured (WPA/WPA2)? [Y/n]: " -r hidden_sec_ans
        if [[ "$hidden_sec_ans" =~ ^[nN]$ ]]; then
            hidden_sec="none"
        else
            hidden_sec="WPA2"
        fi

        connect_target "$hidden_ssid" "$iface" "$hidden_sec"
        read -p "Press Enter to continue..." -r
        return
    fi

    if ! [[ "$choice" =~ ^[0-9]+$ ]] || (( choice < 1 || choice > ${#networks[@]} )); then
        echo -e "${RED}✗ Invalid choice.${NC}"
        read -p "Press Enter to continue..." -r
        return
    fi

    local selected="${networks[$((choice-1))]}"
    IFS=':' read -r ssid _ sec <<< "$selected"
    ssid="${ssid//$'\x00'/:}"
    [[ -z "$ssid" ]] && ssid="(hidden)"

    connect_target "$ssid" "$iface" "$sec"
    read -p "Press Enter to continue..." -r
}

# Function to list and manage saved connections
list_saved_connections() {
    while true; do
        clear
        echo -e "${BOLD}${BLUE}+--------------------------------------------+${NC}"
        echo -e "${BOLD}${BLUE}|         Saved WiFi Connections             |${NC}"
        echo -e "${BOLD}${BLUE}+--------------------------------------------+${NC}\n"

        # nmcli -t escapes literal colons in field values as "\:" - swap
        # them out for a NUL placeholder before splitting on ":", then
        # restore them via bash parameter expansion (not a second sed
        # pass, since NUL bytes are unreliable to stream through sed
        # again), so a connection NAME containing a colon isn't
        # truncated at the wrong point.
        local saved_lines_raw saved_lines=()
        mapfile -t saved_lines_raw < <(nmcli -t -f NAME,TYPE connection show 2>/dev/null \
            | grep -E '(802-11-wireless|wifi)' \
            | sed 's/\\:/\x00/g' \
            | cut -d: -f1 \
            || true)
        for _raw in "${saved_lines_raw[@]}"; do
            saved_lines+=("${_raw//$'\x00'/:}")
        done

        if [[ ${#saved_lines[@]} -eq 0 ]]; then
            echo -e "${YELLOW}No saved connections found.${NC}\n"
            read -p "Press Enter to return..." -r
            return
        fi

        echo -e "${CYAN}Saved networks:${NC}\n"
        printf "${BOLD}%4s  %s${NC}\n" "#" "Connection Name"
        echo "--------------------------------------------"

        local i=1
        for con in "${saved_lines[@]}"; do
            printf "%4d  %s\n" "$i" "$con"
            ((i++))
        done

        echo ""
        echo "  f <#> ) Forget/Delete a specific saved connection (e.g., f 1)"
        echo "  q     ) Return to main menu"
        echo ""
        read -p "Choice: " -r choice

        if [[ "$choice" =~ ^[qQ]$ ]]; then
            return
        elif [[ "$choice" =~ ^[fF][[:space:]]*([0-9]+)$ ]]; then
            local index="${BASH_REMATCH[1]}"
            if (( index >= 1 && index <= ${#saved_lines[@]} )); then
                local target_con="${saved_lines[$((index-1))]}"
                if confirm "Delete saved profile '${target_con}'? This cannot be undone."; then
                    echo -e "${YELLOW}Deleting profile '${target_con}'...${NC}"
                    if nmcli connection delete "$target_con" 2>/dev/null; then
                        echo -e "${GREEN}✓ Successfully deleted profile.${NC}"
                    else
                        echo -e "${RED}✗ Failed to delete profile.${NC}"
                    fi
                else
                    echo -e "${YELLOW}Cancelled.${NC}"
                fi
            else
                echo -e "${RED}✗ Invalid selection index.${NC}"
            fi
            sleep 2
        elif [[ "$choice" =~ ^[fF]$ ]]; then
            echo -e "${RED}✗ Please specify a number after 'f' (e.g., f 1).${NC}"
            sleep 2
        else
            echo -e "${YELLOW}Returning to main menu...${NC}"
            sleep 1
            return
        fi
    done
}

# Main menu loop
main_menu() {
    while true; do
        show_status

        local devices
        readarray -t devices < <(get_wifi_devices)
        local default_iface="${devices[0]:-wlan0}"

        echo -e "${BOLD}${BLUE}+--------------------------------------------+${NC}"
        echo -e "${BOLD}${BLUE}|              WiFi Menu                     |${NC}"
        echo -e "${BOLD}${BLUE}+--------------------------------------------+${NC}\n"
        echo -e "  ${BOLD}1)${NC} Refresh status"
        echo -e "  ${BOLD}2)${NC} Turn WiFi radio ${GREEN}ON${NC}"
        echo -e "  ${BOLD}3)${NC} Turn WiFi radio ${RED}OFF${NC}"
        echo -e "  ${BOLD}4)${NC} Switch active WiFi device"
        echo -e "  ${BOLD}5)${NC} Disconnect active WiFi"
        echo -e "  ${BOLD}6)${NC} Connect to network (on ${CYAN}${default_iface}${NC})"
        echo -e "  ${BOLD}7)${NC} List & manage saved connections"
        echo -e "  ${BOLD}q)${NC} Quit"
        echo ""
        read -p "Choice: " -r choice

        case "$choice" in
            1)
                continue
                ;;
            2)
                if nmcli radio wifi on 2>/dev/null; then
                    echo -e "\n${GREEN}✓ WiFi radio enabled.${NC}"
                else
                    echo -e "\n${RED}✗ Failed to enable WiFi radio.${NC}"
                fi
                sleep 2
                ;;
            3)
                if nmcli radio wifi off 2>/dev/null; then
                    echo -e "\n${RED}✓ WiFi radio disabled.${NC}"
                else
                    echo -e "\n${RED}✗ Failed to disable WiFi radio.${NC}"
                fi
                sleep 2
                ;;
            4)
                switch_device
                ;;
            5)
                disconnect_wifi
                ;;
            6)
                connect_menu
                ;;
            7)
                list_saved_connections
                ;;
            q|Q)
                clear
                echo -e "${GREEN}Goodbye!${NC}"
                exit 0
                ;;
            *)
                echo -e "\n${YELLOW}✗ Invalid choice. Please try again.${NC}"
                sleep 1
                ;;
        esac
    done
}

# Check for dependencies
if ! command -v nmcli >/dev/null 2>&1; then
    echo -e "${RED}✗ Error: nmcli not found. Is NetworkManager installed?${NC}"
    exit 1
fi

# Start the menu
main_menu
