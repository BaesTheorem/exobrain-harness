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
# SECOND JOB: sweeping orphaned code-sign clones (see sweep_clones below). The
# kill -9 above is what strands them, so the two belong in the same script.
#
# Run by com.exobrain.headless-chrome-reaper (launchd, every 120s).

THRESHOLD_SECS="${REAPER_THRESHOLD_SECS:-600}"   # min age before considered (10 min)
SAMPLE_SECS="${REAPER_SAMPLE_SECS:-2}"           # CPU-activity sampling window
CPU_BUSY_DELTA="${REAPER_CPU_BUSY_DELTA:-0.05}"  # cpu-secs over window = "working"
CLONE_GRACE="${REAPER_CLONE_GRACE_SECS:-300}"    # never touch a clone younger than this
CLONE_MATCH_TOL="${REAPER_CLONE_MATCH_TOL:-180}" # clone/process age match window
DRY_RUN="${REAPER_DRY_RUN:-0}"                   # 1 = report sweep targets, delete nothing

# Chrome and Brave clone their own .app bundle at launch to validate the code
# signature, then delete the clone on a graceful exit. A render that hangs (the
# --headless=old failure mode this script exists for) never exits gracefully,
# and neither does anything we kill -9 above, so the clone is stranded forever.
# Nothing else on the system ever removes one.
#
# Each stray is a full app bundle (~2GB logical). APFS shares the underlying
# blocks so real free space barely moves, but macOS storage reporting bills
# every clone at full size: 88 strays once presented as 182GB of "System Data"
# while df showed the disk was fine.
#
# Discriminator: a clone's mtime is set within a second or two of the launch it
# belongs to, so a clone is live iff some running main process of that same app
# has a matching age. Anything unmatched is an orphan. Matching per-process
# rather than against the oldest process matters -- a browser that has been up
# for days would otherwise shield every orphan younger than itself.
#
# Do NOT reach for lsof here. It reports no holder even for a live browser's
# own clone, so it cannot tell live from orphan and would happily delete both.
CLONE_ROOT="$(dirname "$(getconf DARWIN_USER_TEMP_DIR)")/X"

sweep_clones() {
  [ -d "$CLONE_ROOT" ] || return 0
  local now parent appname b live_ages line e s clone m age matched a d swept
  now=$(date +%s)
  swept=0

  for parent in "$CLONE_ROOT"/*.code_sign_clone; do
    [ -d "$parent" ] || continue

    # The clone names its own owner: code_sign_clone.XXXX/Google Chrome.app.bundle
    appname=""
    for b in "$parent"/*/*.app.bundle; do
      [ -e "$b" ] || continue
      appname=$(basename "$b" .bundle)
      break
    done
    [ -n "$appname" ] || continue

    # Ages of live MAIN processes for this app. Helpers carry --type= and spawn
    # later than the launch that made the clone, so they are excluded.
    live_ages=""
    while IFS= read -r line; do
      e=$(printf '%s\n' "$line" | awk '{print $1}')
      s=$(etime_to_secs "$e")
      live_ages="$live_ages ${s:-0}"
    done < <(ps -eo etime,command 2>/dev/null \
             | grep -F "/$appname/Contents/MacOS/" \
             | grep -v -- " --type=" \
             | grep -v grep)

    for clone in "$parent"/code_sign_clone.*; do
      [ -d "$clone" ] || continue
      m=$(stat -f %m "$clone" 2>/dev/null) || continue
      age=$((now - m))

      # Too fresh to judge -- a browser may be mid-launch
      [ "$age" -gt "$CLONE_GRACE" ] || continue

      matched=0
      for a in $live_ages; do
        d=$((age - a)); [ "$d" -lt 0 ] && d=$(( -d ))
        if [ "$d" -le "$CLONE_MATCH_TOL" ]; then matched=1; break; fi
      done
      [ "$matched" -eq 1 ] && continue   # belongs to a running process

      if [ "$DRY_RUN" = "1" ]; then
        printf 'would sweep: %s (age %ss, app %s)\n' "$clone" "$age" "$appname"
        swept=$((swept+1))
      elif rm -rf "$clone" 2>/dev/null; then
        swept=$((swept+1))
      fi
    done
  done

  if [ "$swept" -gt 0 ] && [ "$DRY_RUN" != "1" ]; then
    printf '%s swept %d orphaned code-sign clone(s)\n' "$(date '+%Y-%m-%dT%H:%M:%S')" "$swept"
  fi
  return 0
}

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

# No hung processes is the common case, but orphans from earlier runs outlive
# the process that made them, so the sweep still has to happen.
[ -n "${candidates// }" ] || { sweep_clones; exit 0; }

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

# Runs after the kills above, since those are what strand clones in the first
# place. The grace window means this pass sees them on a later run, not now.
sweep_clones
