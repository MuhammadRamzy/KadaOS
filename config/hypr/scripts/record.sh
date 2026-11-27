#!/usr/bin/env bash
# record.sh [menu|area|window|full|stop|toggle|status|bar] [--mic] [--gif]
# Screen recording (Ctrl+Shift+Alt+R, also in the screenshot menu). Saves to ~/Videos/Recordings.
#   toggle   stop if recording, else the menu        status  JSON for the bar        bar  the bar item (loops)
# Encoder: NVIDIA (NVENC) when plugged in, CPU x264 on battery (waking the dGPU costs more power than it saves);
# falls back to x264 if NVENC can't start. --gif also makes a GIF (small, for chats and docs) when it stops.
RT="${XDG_RUNTIME_DIR:-/tmp}"; PID="$RT/myos-record.pid"; META="$RT/myos-record.meta"
d="$(xdg-user-dir VIDEOS 2>/dev/null || echo ~/Videos)/Recordings"
S="$HOME/.config/hypr/scripts"

recording() { [ -f "$PID" ] && kill -0 "$(cat "$PID" 2>/dev/null)" 2>/dev/null; }
bar_signal() { pkill -RTMIN+15 waybar 2>/dev/null; }
on_ac() { for p in /sys/class/power_supply/*; do [ "$(cat "$p/type" 2>/dev/null)" = Mains ] && [ "$(cat "$p/online" 2>/dev/null)" = 1 ] && return 0; done; return 1; }

start() {   # $1 = area|window|full ; $2.. = flags
  recording && { notify-send -a Recording "Already recording" "Ctrl+Shift+Alt+R stops it."; exit 0; }
  local mode=$1; shift; local mic="" gif=""
  for a in "$@"; do case $a in --mic) mic=1;; --gif) gif=1;; esac; done
  local geo=()
  case $mode in
    area)   g=$(slurp -d -b 1e1e2e66 -c f38ba8ff -w 2) || exit 0; geo=(-g "$g");;
    window) g=$(hyprctl activewindow -j | jq -r '"\(.at[0]),\(.at[1]) \(.size[0])x\(.size[1])"'); geo=(-g "$g");;
    *)      geo=(-o "$(hyprctl monitors -j | jq -r '.[] | select(.focused) | .name')");;
  esac
  mkdir -p "$d"; local f; f="$d/Recording from $(date '+%Y-%m-%d %H-%M-%S').mp4"
  local enc=(-c libx264 -p preset=veryfast -p crf=23 -x yuv420p)
  on_ac && enc=(-c h264_nvenc -p preset=p4 -p cq=25 -x yuv420p)
  local audio=(); [ -n "$mic" ] && audio=(--audio)
  # background jobs of a script start with SIGINT ignored; reset it so "stop" (SIGINT) always reaches the recorder
  env --default-signal=INT wf-recorder "${geo[@]}" "${enc[@]}" "${audio[@]}" -f "$f" >"$RT/myos-record.log" 2>&1 &
  local p=$!; sleep 0.8
  if ! kill -0 "$p" 2>/dev/null && [ "${enc[1]}" = h264_nvenc ]; then           # NVENC refused: CPU instead
    enc=(-c libx264 -p preset=veryfast -p crf=23 -x yuv420p)
    env --default-signal=INT wf-recorder "${geo[@]}" "${enc[@]}" "${audio[@]}" -f "$f" >"$RT/myos-record.log" 2>&1 & p=$!; sleep 0.8
  fi
  if ! kill -0 "$p" 2>/dev/null; then
    notify-send -a Recording -u critical "Couldn't start recording" "$(tail -n 2 "$RT/myos-record.log")"; exit 1
  fi
  echo "$p" > "$PID"; printf '%s\n%s\n%s\n%s\n' "$(date +%s)" "$f" "$gif" "${enc[1]}" > "$META"
  bar_signal
}

stop() {
  recording || { rm -f "$PID"; exit 0; }
  local p; p=$(cat "$PID"); kill -INT "$p"                    # SIGINT: wf-recorder finishes the file properly
  # wait until it has really exited: using the file earlier gives an unplayable MP4 (the index is written last), and a
  # long CPU-encoded recording can take a while to flush
  for i in $(seq 600); do kill -0 "$p" 2>/dev/null || break; [ "$i" = 30 ] && notify-send -a Recording -t 4000 "Finishing the video…"; sleep 0.1; done
  if kill -0 "$p" 2>/dev/null; then notify-send -a Recording -u critical "Recording still finishing" "Left it running: $(sed -n 2p "$META")"; exit 1; fi
  local f gif; f=$(sed -n 2p "$META"); gif=$(sed -n 3p "$META")
  rm -f "$PID" "$META"; bar_signal
  [ -s "$f" ] || { notify-send -a Recording -u critical "Recording failed" "$(tail -n 2 "$RT/myos-record.log")"; exit 1; }
  if [ -n "$gif" ]; then make_gif "$f" && f="${f%.mp4}.gif"; fi
  printf 'file://%s\n' "$f" | wl-copy --type text/uri-list
  act=$("$S/notify-action.py" -t 15 "Recording saved (copied)" "$(basename "$f")" open=Open folder="Show in folder" gif="Make a GIF")
  case $act in
    open) xdg-open "$f";; folder) nautilus --select "$f";;
    gif) make_gif "$f" && nautilus --select "${f%.mp4}.gif";;
  esac
}

make_gif() {   # small, sharp GIF: 12 fps, max 960 px wide, own palette
  local in=$1 out="${1%.mp4}.gif"
  ffmpeg -hide_banner -loglevel error -y -i "$in" -vf "fps=12,scale='min(960,iw)':-2:flags=lanczos,split[a][b];[a]palettegen=stats_mode=diff[p];[b][p]paletteuse=dither=sierra2_4a" "$out"
}

status() {   # JSON for the bar: empty when not recording
  if recording; then
    local t0; t0=$(head -1 "$META" 2>/dev/null || date +%s); local s=$(( $(date +%s) - t0 ))
    printf '{"text":"● %d:%02d","class":"rec","tooltip":"Recording · click to stop"}\n' $((s / 60)) $((s % 60))
  else printf '{"text":"","class":"idle"}\n'; fi
}

case ${1:-menu} in
  area|window|full) m=$1; shift; start "$m" "$@";;
  stop) stop;;
  toggle) if recording; then stop; else exec "$0" menu; fi;;
  status) status;;
  bar) while :; do status; sleep 1; done;;   # the bar item (waybar keeps it running); two tiny checks a second
  menu)
    recording && { stop; exit 0; }
    c=$(printf '%s\n' \
      "Area	media-record-symbolic	drag a region" \
      "Window	view-restore-symbolic	the active window" \
      "Full screen	video-display-symbolic	the whole display" \
      "Full screen + microphone	audio-input-microphone-symbolic	with your voice" \
      "Area as GIF	image-x-generic-symbolic	small, for chats and docs" \
      | "$S/menu.sh" "Record screen") || exit 0
    sleep 0.3
    case $c in
      *microphone*) start full --mic;; *GIF*) start area --gif;; Window*) start window;; Full*) start full;; *) start area;;
    esac;;
  *) echo "usage: record.sh menu|area|window|full|stop|toggle|status" >&2; exit 2;;
esac
