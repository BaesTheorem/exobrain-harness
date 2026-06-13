#!/bin/bash
# headless-chrome-reaper.sh
#
# Safety net that kills ONLY genuinely-stuck headless Chrome render processes
# (and their hung shell wrappers). These come from `Google Chrome --headless`
# screenshot / dump-dom / print-to-pdf invocations that hang indefinitely (a
# known macOS failure mode of --dump-dom).
#
# CONCURRENT-SESSION SAFE. The browser-render skill launches legit renders with
# the exact same signature (--headless=old --user-data-dir=/tmp/render-$$), so a
# render in active use in another Claude session is indistinguishable from a hung
# one by command line alone. We therefore gate on three independent signals and
# only reap when ALL agree the process is abandoned:
#
#   1. Identity   -- cmd carries --user-data-dir=/tmp/ AND a Chrome/headless marker
#   2. Age        -- older than THRESHOLD_SECS (a real render finishes in seconds)
#   3. Inactivity -- accrues ~no CPU over a live sample window (a working render is
#                    CPU-bound; a hung one sits at 0%). THIS is the in-use guard:
#                    anything still doing work is never touched, regardless of age.
#
# Also never touches anything driven via --remote-debugging (an attached client =
# in use), nor LinkedIn MCP's chrome-headless-shell (~/.linkedin-mcp, not /tmp),
# nor Plaud / other Electron apps (different binary, no /tmp profile).
#
# Run by com.exobrain.headless-chrome-reaper (launchd, every 120s).

THRESHOLD_SECS="${REAPER_THRESHOLD_SECS:-600}"   # min age before considered (10 min)
SAMPLE_SECS="${REAPER_SAMPLE_SECS:-2}"           # CPU-activity sampling window
CPU_BUSY_DELTA="${REAPER_CPU_BUSY_DELTA:-0.05}"  # cpu-secs over window = "working"

# Convert ps etime ([[DD-]HH:]MM:SS) to integer seconds.
etime_to_secs() {
  awk -v e="$1" 'BEGIN{
    d=0; rest=e; n=index(rest,"-");
    if(n>0){ d=substr(rest,1,n-1); rest=substr(rest,n+1); }
    nf=split(rest,p,":");
    if(nf==3){ h=p[1]; m=p[2]; s=p[3]; } else { h=0; m=p[1]; s=p[2]; }
    print (d*86400)+(h*3600)+(m*60)+s;
  }'
}

# Convert ps cputime ([[DD-]HH:]MM:SS.ss) to float seconds.
cputime_to_secs() {
  awk -v e="$1" 'BEGIN{
    d=0; rest=e; n=index(rest,"-");
    if(n>0){ d=substr(rest,1,n-1); rest=substr(rest,n+1); }
    nf=split(rest,p,":");
    if(nf==3){ h=p[1]; m=p[2]; s=p[3]; } else { h=0; m=p[1]; s=p[2]; }
    printf "%.2f", (d*86400)+(h*3600)+(m*60)+s;
  }'
}

# ---- Pass 1: find candidates that pass identity + age + not-driven gates ----
candidates=""   # space-separated "pid:cput1"
while IFS= read -r line; do
  pid=$(printf '%s\n' "$line"   | awk '{print $1}')
  etime=$(printf '%s\n' "$line" | awk '{print $2}')
  cput=$(printf '%s\n' "$line"  | awk '{print $3}')
  cmd=$(printf '%s\n' "$line"   | cut -d' ' -f4-)

  [ "$pid" = "$$" ] && continue

  # 1. Identity: /tmp render profile AND a chrome/headless marker
  case "$cmd" in *"--user-data-dir=/tmp/"*) ;; *) continue ;; esac
  case "$cmd" in *"Google Chrome"*|*"--headless"*) ;; *) continue ;; esac

  # Never touch a browser with an attached debugger client (in use)
  case "$cmd" in *"--remote-debugging"*) continue ;; esac

  # 2. Age gate
  secs=$(etime_to_secs "$etime")
  [ "${secs:-0}" -gt "$THRESHOLD_SECS" ] || continue

  t1=$(cputime_to_secs "$cput")
  candidates="$candidates $pid:$t1"
done < <(ps -eo pid,etime,time,command)

[ -n "${candidates// }" ] || exit 0

# ---- Sample window: let any still-working process accrue CPU ----
sleep "$SAMPLE_SECS"

# ---- Pass 2: reap only those that stayed idle through the window ----
killed=0
for entry in $candidates; do
  pid=${entry%%:*}
  t1=${entry#*:}
  # Process may have exited on its own during the window -> nothing to do
  cput=$(ps -o time= -p "$pid" 2>/dev/null | tr -d ' ')
  [ -n "$cput" ] || continue
  t2=$(cputime_to_secs "$cput")

  busy=$(awk -v a="$t1" -v b="$t2" -v thr="$CPU_BUSY_DELTA" 'BEGIN{print ((b-a)>thr)?1:0}')
  if [ "$busy" -eq 1 ]; then
    continue   # actively working -> in use, leave it alone
  fi
  if kill -9 "$pid" 2>/dev/null; then
    killed=$((killed+1))
  fi
done

if [ "$killed" -gt 0 ]; then
  printf '%s reaped %d stale headless-chrome / wrapper process(es)\n' "$(date '+%Y-%m-%dT%H:%M:%S')" "$killed"
fi
