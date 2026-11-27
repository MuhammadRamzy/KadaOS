#!/usr/bin/env bash
# Lock the screen so a numeric PIN always works on the number pad.
# Num Lock state can't be forced reliably from a script on Wayland (wtype has its own keyboard; hyprctl doesn't
# report the key's state), so while locked we add the xkb option "numpad:mac": the keypad ALWAYS types digits,
# whatever Num Lock says. Your normal keypad behaviour is restored right after unlocking.
pidof hyprlock >/dev/null && exit 0
orig=$(hyprctl getoption input:kb_options -j | jq -r .str); [ "$orig" = "[[EMPTY]]" ] && orig=""
case ",$orig," in *,numpad:mac,*) new="$orig";; *) new="${orig:+$orig,}numpad:mac";; esac
hyprctl keyword input:kb_options "$new" >/dev/null
restore(){ hyprctl keyword input:kb_options "$orig" >/dev/null; }
trap restore EXIT
locked_at=$(date +%s)
hyprlock "$@"
# back: one summary of what arrived, if you were away 10+ minutes (secretary decides; quiet otherwise)
setsid -f python3 ~/.local/share/local-ai/secretary.py away "$locked_at" >/dev/null 2>&1
