#!/usr/bin/env python3
"""
MCP server for Alex's Missouri unemployment claim (UInteract / DES).

SCOPE, AND WHY IT IS WHAT IT IS
-------------------------------
This server does NOT log into uinteract.labor.mo.gov and does NOT read or write
anything on the portal. That is not an unfinished feature.

DES runs an anti-automation control that reacts to the Chrome debugging
protocol: credentials fill fine, but clicking LOG IN closes the window, and
attaching to a profile that has already tried closes it on connect (reproduced
repeatedly on 2026-08-02). Routing around that means defeating a security
control on a state benefits portal to save about three minutes of clicking, so
the portal half stays manual and this server covers everything else.

There is also deliberately no tool that submits a weekly request for payment.
The weekly certification is a sworn statement under RSMo 288.380. Its questions
about earnings, self-employment, severance, and availability have answers only
Alex has, and the penalties for a wrong one land on him. The division is: this
server prepares, Alex certifies.

What it does cover: which weeks are open and when their money expires, the
work-search evidence behind each week, the local filing ledger, the
correspondence queue, and handing Alex a login URL.

All state lives in unemployment/data/ (gitignored). Nothing here writes a name,
SSN, dollar figure, or claim number into a tracked file.
"""

import json
import os
import re
import subprocess
import sys
import traceback
from datetime import date, datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
HARNESS = HERE.parent
DATA = HERE / "data"
VAULT = Path("/Users/alexhedtke/Exobrain")
LISTINGS = VAULT / "Projects/Get new job/Job Listings"
DAILY = VAULT / "Daily notes"

LOGIN_URL = "https://uinteract.labor.mo.gov/benefits/#/benefits/login"
DES_PHONE = "800-320-2519"
PLAYBOOK = "Research/Layoff Benefits Playbook (Missouri 2026).md"

LAYOFF_DATE = "2026-07-17"
CLAIM_FILED = "2026-07-19"

SERVER_NAME = "uinteract"
SERVER_VERSION = "1.0.0"
PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")

FILINGS = DATA / "filings.json"
ACTIVITIES = DATA / "activities.json"
CORRESPONDENCE = DATA / "correspondence.json"

MIN_ACTIVITIES = 3
DEADLINE_DAYS = 14

ACTIVITY_KINDS = [
    "application", "interview", "recruiter_screen", "job_fair",
    "workshop", "resea", "resume", "networking", "mojobs_search",
]


# ---------------------------------------------------------------- local state

def read_json(path, default):
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def write_json(path, value):
    DATA.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


# ---------------------------------------------------------------- week math

def parse_day(s, field="date"):
    try:
        return datetime.strptime(s.strip(), "%Y-%m-%d").date()
    except (ValueError, AttributeError):
        raise ValueError(f"{field} must be YYYY-MM-DD, got {s!r}")


def week_ending_for(d):
    """The Saturday that closes the Sunday-Saturday week containing d."""
    return d + timedelta(days=(5 - d.weekday()) % 7)


def normalize_week(s):
    """Accept any date in a week, return that week's Saturday."""
    we = week_ending_for(parse_day(s, "week_ending"))
    return we


def recent_weeks(count, today=None):
    today = today or date.today()
    last = week_ending_for(today)
    if last >= today:            # current week has not closed yet
        last -= timedelta(days=7)
    return [last - timedelta(days=7 * i) for i in range(count)]


def week_record(we, filings, today=None):
    today = today or date.today()
    deadline = we + timedelta(days=DEADLINE_DAYS)
    rec = filings.get(we.isoformat(), {})
    filed = bool(rec.get("filed"))
    days_left = (deadline - today).days
    if filed:
        state = "filed"
    elif we.isoformat() < CLAIM_FILED:
        # Weeks that closed before the initial claim was filed were never
        # claimable. Reporting them as forfeited money is a false alarm.
        state = "pre-claim -- not a claimable week"
    elif days_left < 0:
        state = "EXPIRED -- this week's payment is forfeited"
    else:
        state = "OPEN"
    return {
        "week_ending": we.isoformat(),
        "covers": f"{(we - timedelta(days=6)).isoformat()} .. {we.isoformat()}",
        "request_deadline": deadline.isoformat(),
        "days_until_deadline": days_left,
        "state": state,
        "filed_at": rec.get("filed_at"),
        "confirmation": rec.get("confirmation"),
        "note": rec.get("note"),
    }


# ---------------------------------------------------------------- vault reads

def frontmatter(path):
    """Flat `key: value` frontmatter. These notes have no nested YAML."""
    out = {}
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return out
    if not text.startswith("---"):
        return out
    body = text.split("---", 2)
    if len(body) < 3:
        return out
    for line in body[1].splitlines():
        if ":" in line and not line.startswith(" "):
            k, v = line.split(":", 1)
            out[k.strip()] = v.strip()
    return out


ORDINALS = {1: "st", 2: "nd", 3: "rd", 21: "st", 22: "nd", 23: "rd", 31: "st"}


def daily_note_path(d):
    suffix = ORDINALS.get(d.day, "th")
    return DAILY / f"{d:%A, %B} {d.day}{suffix}, {d.year}.md"


DAILY_HINTS = re.compile(
    r"\b(applied|application|interview|recruiter|screen(?:ing)?|"
    r"phone screen|job fair|career fair|networking|coffee chat|"
    r"resume|job center|RESEA|MoJobs|jobs\.mo\.gov)\b", re.I)


def scan_daily_notes(start, end):
    """Lines in the week's daily notes that look like work-search activity.

    These are hints, not evidence. Every one needs Alex to confirm it happened
    before it is logged -- the skill's rule is that nothing gets invented.
    """
    hits = []
    d = start
    while d <= end:
        path = daily_note_path(d)
        if path.exists():
            try:
                lines = path.read_text(errors="replace").splitlines()
            except OSError:
                lines = []
            for line in lines:
                stripped = line.strip().lstrip("-*#> ").strip()
                if len(stripped) < 12 or len(stripped) > 300:
                    continue
                if DAILY_HINTS.search(stripped):
                    hits.append({
                        "date": d.isoformat(),
                        "text": stripped,
                        "source": f"daily note: {path.name}",
                        "confidence": "unconfirmed -- ask Alex before logging",
                    })
        d += timedelta(days=1)
    return hits


def scan_listings(start, end):
    """Job-listing notes whose application_date falls inside the week."""
    hits = []
    if not LISTINGS.is_dir():
        return hits
    for path in sorted(LISTINGS.glob("*.md")):
        fm = frontmatter(path)
        raw = (fm.get("application_date") or "").strip()
        if not raw:
            continue
        try:
            when = parse_day(raw)
        except ValueError:
            continue
        if start <= when <= end:
            hits.append({
                "date": when.isoformat(),
                "kind": "application",
                "employer": fm.get("company", "").strip(),
                "detail": fm.get("role", "").strip(),
                "status": fm.get("status", "").strip(),
                "apply_url": fm.get("apply_url", "").strip(),
                "source": f"job listing note: {path.name}",
                "confidence": "vault-recorded -- confirm against the Gmail receipt",
            })
    return sorted(hits, key=lambda h: h["date"])


# ---------------------------------------------------------------- tools

def tool_weeks(args):
    count = int(args.get("weeks_back", 4))
    count = max(1, min(count, 26))
    filings = read_json(FILINGS, {})
    weeks = [week_record(we, filings) for we in recent_weeks(count)]
    open_weeks = [w for w in weeks if w["state"] == "OPEN"]
    lost = [w for w in weeks if w["state"].startswith("EXPIRED")]
    return {
        "today": date.today().isoformat(),
        "weeks": weeks,
        "open_count": len(open_weeks),
        "expired_unfiled": [w["week_ending"] for w in lost],
        "rules": [
            "Weeks run Sunday through Saturday.",
            f"A request must be filed within {DEADLINE_DAYS} days of the week-ending "
            "Saturday or that week's money is gone. No rollover.",
            f"At least {MIN_ACTIVITIES} work-search activities must be logged in "
            "UInteract BEFORE the request, or the week is denied.",
            "The waiting week is unpaid but the request still must be filed.",
        ],
        "note": "'filed' reflects this local ledger, not the portal. Verify on the "
                "portal after Alex submits, then call uinteract_record_filing.",
    }


def tool_record_filing(args):
    we = normalize_week(args["week_ending"])
    filings = read_json(FILINGS, {})
    filings[we.isoformat()] = {
        "filed": bool(args.get("filed", True)),
        "filed_at": args.get("filed_at") or datetime.now().isoformat(timespec="seconds"),
        "confirmation": args.get("confirmation"),
        "note": args.get("note"),
    }
    write_json(FILINGS, filings)
    return {
        "recorded": week_record(we, filings),
        "reminder": "Only record a week after seeing it read as filed on the portal. "
                    "This ledger is what the deadline warnings key off.",
    }


def tool_work_search(args):
    we = normalize_week(args["week_ending"])
    start = we - timedelta(days=6)
    logged = [a for a in read_json(ACTIVITIES, [])
              if start.isoformat() <= a.get("date", "") <= we.isoformat()]
    listings = scan_listings(start, we)
    hints = scan_daily_notes(start, we)

    count = len(logged)
    short = max(0, MIN_ACTIVITIES - count)
    deadline = we + timedelta(days=DEADLINE_DAYS)
    days_left = (deadline - date.today()).days

    out = {
        "week": f"{start.isoformat()} .. {we.isoformat()}",
        "request_deadline": deadline.isoformat(),
        "days_until_deadline": days_left,
        "confirmed_activities": logged,
        "confirmed_count": count,
        "required": MIN_ACTIVITIES,
        "candidates_from_job_listings": listings,
        "hints_from_daily_notes": hints,
        "gmail_not_checked": "This server cannot reach Gmail. Application "
                             "confirmation emails are the strongest evidence -- "
                             "search them separately before trusting a count. A "
                             "submitted-looking Workday form with no confirmation "
                             "may never have submitted.",
    }
    if short:
        out["SHORTFALL"] = (
            f"{count} confirmed, {MIN_ACTIVITIES} required -- {short} short. "
            "Do not pad this. Say so plainly and, if the window is still open, "
            "fix it for real: a jobs.mo.gov search, a resume revision, or a "
            "networking reach-out all count and can be done today."
        )
    else:
        out["status"] = f"{count} confirmed activities meets the {MIN_ACTIVITIES} minimum."
    return out


def tool_log_activity(args):
    when = parse_day(args["date"])
    kind = args["kind"].strip()
    if kind not in ACTIVITY_KINDS:
        raise ValueError(f"kind must be one of {', '.join(ACTIVITY_KINDS)}")
    detail = args["detail"].strip()
    if not detail:
        raise ValueError("detail is required -- an activity with no specifics is not evidence")
    entry = {
        "date": when.isoformat(),
        "kind": kind,
        "employer": (args.get("employer") or "").strip(),
        "detail": detail,
        "source": (args.get("source") or "").strip(),
        "week_ending": week_ending_for(when).isoformat(),
        "logged_at": datetime.now().isoformat(timespec="seconds"),
    }
    entries = read_json(ACTIVITIES, [])
    for e in entries:
        if (e.get("date") == entry["date"] and e.get("kind") == entry["kind"]
                and e.get("detail") == entry["detail"]):
            return {"duplicate": True, "existing": e}
    entries.append(entry)
    entries.sort(key=lambda e: e.get("date", ""))
    write_json(ACTIVITIES, entries)
    return {
        "logged": entry,
        "reminder": "Log only what actually happened, with a date it traces to. "
                    "This is a local mirror -- the activity still has to be entered "
                    "in UInteract before that week's request.",
    }


def tool_certification_questions(args):
    return {
        "hard_rule": "MIST never submits the weekly request. Alex answers these "
                     "himself and clicks submit himself. If he says 'just submit "
                     "it,' hand him these questions instead -- it is thirty "
                     "seconds and it keeps the attestation his.",
        "why": "The weekly certification is a sworn statement. Missouri prosecutes "
               "false statements made to obtain benefits (RSMo 288.380), and the "
               "penalty lands on Alex, not on the assistant that filled the form.",
        "questions": [
            {
                "question": "Did you work in any capacity during the week?",
                "why_it_is_tricky": "Working Order LLC is an active consultancy. "
                                    "Self-employment and coaching hours count as work "
                                    "even when unpaid or unbilled.",
            },
            {
                "question": "What were your gross earnings for the week?",
                "why_it_is_tricky": "Earnings are reported for the week they were "
                                    "EARNED, not the week they were paid.",
            },
            {
                "question": "How should the severance package be reported?",
                "why_it_is_tricky": "UNRESOLVED, and do not guess. The DES FAQ says "
                                    "severance is 'not reportable'; RSMo 288.036 says "
                                    "lump-sum severance is prorated as wages. The public "
                                    f"sources do not reconcile. Call DES at {DES_PHONE} "
                                    "(Mon-Fri 8-5) and get an answer on the record.",
            },
            {
                "question": "Were you able to and available for full-time work all week?",
                "why_it_is_tricky": "Covers illness, travel, and anything that would "
                                    "have stopped him taking a job that week.",
            },
            {
                "question": "Did you refuse any offer of work or any referral?",
                "why_it_is_tricky": "Includes referrals through jobs.mo.gov, not just "
                                    "direct offers.",
            },
        ],
        "before_answering": "Read the correspondence queue first. A fact-finding "
                            "questionnaire can change the answers on a weekly request.",
        "playbook": f"Vault: {PLAYBOOK} -- read it rather than restating benefit math "
                    "from memory.",
    }


def tool_claim_facts(args):
    filings = read_json(FILINGS, {})
    filed_weeks = sorted(k for k, v in filings.items() if v.get("filed"))
    return {
        "portal": "https://uinteract.labor.mo.gov",
        "login_url": LOGIN_URL,
        "des_phone": f"{DES_PHONE} (Mon-Fri 8-5)",
        "layoff_date": LAYOFF_DATE,
        "layoff_context": "Clyde outsourced IT to Accenture -- a clean no-fault separation.",
        "initial_claim_filed": CLAIM_FILED,
        "weeks_recorded_filed": filed_weeks,
        "mojobs": "jobs.mo.gov registration is automatic on filing. Visit at least "
                  "monthly; the visit itself counts as a work-search activity.",
        "training_waiver": "Enrolling in WIOA-approved training can waive the "
                           f"{MIN_ACTIVITIES}-per-week work-search requirement. Ties to the "
                           "FEC-KC dislocated-worker intake. Worth chasing: it kills the "
                           "weekly chore and funds a cert.",
        "playbook": f"Vault: {PLAYBOOK}",
        "automation_boundary": "The portal cannot be driven. DES runs an anti-automation "
                               "control that closes the browser on an automated login. Do "
                               "not try to defeat it -- login is manual, always.",
    }


def tool_open_login(args):
    if not args.get("confirm"):
        return {
            "opened": False,
            "why": "confirm must be true. Every login fires an SMS to Alex "
                   "('Your account was accessed on ...'), so an idle check costs him "
                   "a notification and makes a genuinely suspicious login harder to "
                   "spot. Open the portal when there is something to do on it.",
        }
    subprocess.run(["open", LOGIN_URL], check=False)
    return {
        "opened": True,
        "url": LOGIN_URL,
        "next": "Alex signs in by hand. Credentials do not get typed for him and the "
                "window does not get driven -- a mistargeted password is a genuinely "
                "bad failure.",
        "expect_sms": "He will get an account-accessed text. If he ever reports one he "
                      f"cannot account for, that is a real security question: call {DES_PHONE}.",
    }


def tool_correspondence(args):
    action = args.get("action", "list")
    items = read_json(CORRESPONDENCE, [])
    if action == "list":
        today = date.today()
        for it in items:
            dl = it.get("deadline")
            if dl and not it.get("resolved"):
                try:
                    it["days_until_deadline"] = (parse_day(dl) - today).days
                except ValueError:
                    pass
        openq = [i for i in items if not i.get("resolved")]
        return {
            "items": sorted(items, key=lambda i: i.get("received", "")),
            "open_count": len(openq),
            "reminder": "Viewing is not responding. Correspondence with a deadline "
                        "needs a Things task with the real date -- fact-finding "
                        "questionnaires and wage audits can suspend payment.",
        }
    if action == "add":
        entry = {
            "received": parse_day(args["received"], "received").isoformat(),
            "subject": args["subject"].strip(),
            "deadline": parse_day(args["deadline"], "deadline").isoformat()
                        if args.get("deadline") else None,
            "action_required": (args.get("action_required") or "").strip(),
            "resolved": False,
            "logged_at": datetime.now().isoformat(timespec="seconds"),
        }
        items.append(entry)
        write_json(CORRESPONDENCE, items)
        return {
            "added": entry,
            "next": "Create a Things task with the real deadline. Reading the notice "
                    "is not answering it.",
        }
    if action == "resolve":
        subject = args["subject"].strip().lower()
        hit = None
        for it in items:
            if it.get("subject", "").strip().lower() == subject:
                it["resolved"] = True
                it["resolved_at"] = datetime.now().isoformat(timespec="seconds")
                hit = it
        if not hit:
            raise ValueError(f"No correspondence item with subject {args['subject']!r}")
        write_json(CORRESPONDENCE, items)
        return {"resolved": hit}
    raise ValueError("action must be list, add, or resolve")


DATE_SCHEMA = {"type": "string", "description": "YYYY-MM-DD"}

TOOLS = [
    {
        "name": "uinteract_weeks",
        "description": (
            "List recent Sunday-Saturday benefit weeks with their 14-day request "
            "deadlines and whether the local ledger shows them filed. Start here: "
            "it is how you find out which weeks are still open and which have "
            "already expired."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "weeks_back": {"type": "integer",
                               "description": "How many closed weeks to list (default 4, max 26)"},
            },
        },
        "handler": tool_weeks,
    },
    {
        "name": "uinteract_work_search",
        "description": (
            "Assemble the work-search evidence for one benefit week: activities "
            "already confirmed in the local ledger, candidates from job-listing "
            "notes, and unconfirmed hints from daily notes. Flags a shortfall "
            "against the 3-per-week minimum. Never invents activities, and cannot "
            "see Gmail confirmations -- check those separately."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "week_ending": dict(DATE_SCHEMA,
                                    description="Any date in the week; resolves to that week's Saturday"),
            },
            "required": ["week_ending"],
        },
        "handler": tool_work_search,
    },
    {
        "name": "uinteract_log_activity",
        "description": (
            "Record a work-search activity that actually happened, with a date it "
            "traces to. Local mirror only -- the activity still has to be entered "
            "in UInteract before that week's request is filed."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "date": DATE_SCHEMA,
                "kind": {"type": "string", "enum": ACTIVITY_KINDS},
                "employer": {"type": "string"},
                "detail": {"type": "string",
                           "description": "What actually happened. Required."},
                "source": {"type": "string",
                           "description": "Where this is evidenced (confirmation email, note, transcript)"},
            },
            "required": ["date", "kind", "detail"],
        },
        "handler": tool_log_activity,
    },
    {
        "name": "uinteract_certification_questions",
        "description": (
            "The questions on the weekly request that only Alex can answer, with "
            "the traps on each one (self-employment through Working Order LLC, "
            "earned-vs-paid timing, the unresolved severance conflict). Use this "
            "to prepare him for the form. There is no tool that submits it."),
        "inputSchema": {"type": "object", "properties": {}},
        "handler": tool_certification_questions,
    },
    {
        "name": "uinteract_record_filing",
        "description": (
            "Mark a benefit week as filed in the local ledger, after verifying on "
            "the portal that it actually reads as filed. The deadline warnings key "
            "off this, so do not record a week optimistically."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "week_ending": dict(DATE_SCHEMA,
                                    description="Any date in the week; resolves to that week's Saturday"),
                "filed": {"type": "boolean", "description": "Default true"},
                "filed_at": {"type": "string", "description": "ISO timestamp; defaults to now"},
                "confirmation": {"type": "string", "description": "Confirmation number, if the portal gave one"},
                "note": {"type": "string"},
            },
            "required": ["week_ending"],
        },
        "handler": tool_record_filing,
    },
    {
        "name": "uinteract_correspondence",
        "description": (
            "Track DES correspondence and its deadlines. action=list shows the "
            "queue with days remaining, action=add logs a new notice, "
            "action=resolve closes one out. Read the queue before preparing a "
            "week: a fact-finding questionnaire can change the answers on a "
            "weekly request."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["list", "add", "resolve"],
                           "description": "Default list"},
                "received": dict(DATE_SCHEMA, description="For add: date the notice arrived"),
                "subject": {"type": "string", "description": "For add/resolve"},
                "deadline": dict(DATE_SCHEMA, description="For add: response deadline, if any"),
                "action_required": {"type": "string",
                                    "description": "For add: what it actually asks for"},
            },
        },
        "handler": tool_correspondence,
    },
    {
        "name": "uinteract_claim_facts",
        "description": (
            "Static facts about the claim: portal and login URLs, the DES phone "
            "number, layoff and filing dates, MoJobs and training-waiver rules, "
            "and the automation boundary. Cheap context that costs Alex nothing "
            "(no login, no SMS)."),
        "inputSchema": {"type": "object", "properties": {}},
        "handler": tool_claim_facts,
    },
    {
        "name": "uinteract_open_login",
        "description": (
            "Open the UInteract login page in Alex's browser so he can sign in by "
            "hand. Requires confirm=true: every login fires an account-accessed "
            "SMS to him, so the portal does not get opened idly. Does not type "
            "credentials and does not drive the window."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "confirm": {"type": "boolean",
                            "description": "Must be true. Acknowledges that this texts Alex."},
            },
            "required": ["confirm"],
        },
        "handler": tool_open_login,
    },
]

HANDLERS = {t["name"]: t.pop("handler") for t in TOOLS}


# ---------------------------------------------------------------- jsonrpc

def respond(msg_id, result=None, error=None):
    msg = {"jsonrpc": "2.0", "id": msg_id}
    if error is not None:
        msg["error"] = error
    else:
        msg["result"] = result
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()


def handle(msg):
    method = msg.get("method")
    msg_id = msg.get("id")
    params = msg.get("params") or {}

    if msg_id is None:                       # notification; no reply
        return

    if method == "initialize":
        wanted = params.get("protocolVersion")
        version = wanted if wanted in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0]
        respond(msg_id, {
            "protocolVersion": version,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            "instructions": (
                "Missouri unemployment claim management. This server does not touch "
                "the UInteract portal (DES blocks automated login by design) and has "
                "no tool that submits a weekly request -- that form is a sworn "
                "statement only Alex can sign. It prepares; he certifies."),
        })
    elif method == "ping":
        respond(msg_id, {})
    elif method == "tools/list":
        respond(msg_id, {"tools": TOOLS})
    elif method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        fn = HANDLERS.get(name)
        if fn is None:
            respond(msg_id, error={"code": -32601, "message": f"Unknown tool: {name}"})
            return
        try:
            result = fn(args)
            payload = json.dumps(result, indent=2, default=str)
            respond(msg_id, {"content": [{"type": "text", "text": payload}]})
        except (ValueError, KeyError) as e:
            respond(msg_id, {"content": [{"type": "text", "text": f"Error: {e}"}],
                             "isError": True})
        except Exception:
            respond(msg_id, {"content": [{"type": "text",
                                          "text": "Error:\n" + traceback.format_exc()}],
                             "isError": True})
    else:
        respond(msg_id, error={"code": -32601, "message": f"Unknown method: {method}"})


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        try:
            handle(msg)
        except Exception:
            print(traceback.format_exc(), file=sys.stderr)


if __name__ == "__main__":
    main()
