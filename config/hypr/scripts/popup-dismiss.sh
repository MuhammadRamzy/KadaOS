#!/usr/bin/env bash
# Click outside a popup (Quick Settings panels, launcher, pickers) closes it.
# These popups are stay_focused (so hovering another window doesn't close them), and a click on empty
# desktop or the bar gives focus to nothing, so they would never lose focus on their own. Run on every left click (pass-through bindn).
# Clicks on the bar are ignored: its buttons toggle their own panel and must not close-then-reopen it.
win=$(hyprctl -j activewindow) || exit 0
case $(jq -r '.class // ""' <<<"$win") in org.myos.Panel|org.myos.Run|org.myos.Pick) ;; *) exit 0;; esac
read -r x y < <(hyprctl cursorpos | tr -d ,)
inside() { jq -e --argjson x "$x" --argjson y "$y" \
  '.at[0] <= $x and $x < .at[0]+.size[0] and .at[1] <= $y and $y < .at[1]+.size[1]' >/dev/null; }
inside <<<"$win" && exit 0
hyprctl -j layers | jq -e --argjson x "$x" --argjson y "$y" '[..|objects|select(.namespace? == "waybar")
  |select(.x <= $x and $x < .x+.w and .y <= $y and $y < .y+.h)] | length > 0' >/dev/null && exit 0
hyprctl -q dispatch closewindow "address:$(jq -r .address <<<"$win")"
