"""fantasy/bin/chat-watch: who is allowed to answer a message, and whether it landed.

Two things here are quiet when broken. A DM leaking back onto the model's list
reads as a working watcher right up until it answers a friend unprompted, and
an escalation whose three delivery paths all failed looks identical to one that
worked unless the return value says otherwise. Both get a positive control.
"""

import importlib.machinery
import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "fantasy"))
_loader = importlib.machinery.SourceFileLoader("chat_watch", str(REPO / "fantasy" / "bin" / "chat-watch"))
spec = importlib.util.spec_from_loader("chat_watch", _loader)   # no .py suffix, so name the loader
assert spec is not None and spec.loader is not None
chat_watch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(chat_watch)


def m(mid, who, kind, topic="t1", content="hi"):
    return {"id": mid, "who": who, "type": kind, "topic": topic,
            "with": [who], "content": content, "date": 0, "at": ""}


DM = "CHAT_DIRECT_MESSAGE"


def test_a_dm_never_reaches_the_model_and_the_league_chat_still_does():
    pending = [m("1", "Namaslay", DM), m("2", "The Winners", "CHAT", topic="league"),
               m("3", "LM", "CHAT_ALL_MEMBERS", topic="all")]
    hot, dms, league = chat_watch.classify(pending, partners=set(), guard_ok=True)

    assert [x["id"] for x in dms] == ["1"]
    # The positive control: the split has to let something through, or "no DM
    # was answered" would be satisfied by a watcher that answers nothing.
    assert [x["id"] for x in league] == ["2", "3"]
    assert hot == []


def test_a_trade_partner_escalates_once_under_the_sharper_reason():
    pending = [m("1", "KC Breathmints", DM), m("2", "KC Breathmints", "CHAT", topic="league")]
    hot, dms, league = chat_watch.classify(pending, {"KC Breathmints"}, guard_ok=True)

    assert [x["id"] for x in hot] == ["1", "2"]   # the league one too: it is about the offer
    assert dms == [] and league == []             # and the DM is not escalated twice


def test_a_broken_partner_lookup_escalates_everything():
    pending = [m("1", "Namaslay", DM), m("2", "The Winners", "CHAT", topic="league")]
    hot, dms, league = chat_watch.classify(pending, partners=set(), guard_ok=False)

    assert len(hot) == 2 and dms == [] and league == []


def test_escalate_groups_by_thread_and_reports_delivery(monkeypatch):
    chats, dms_sent = [], []
    monkeypatch.setattr(chat_watch, "console_chat",
                        lambda title, seed: chats.append((title, seed)) or "s9")
    monkeypatch.setattr(chat_watch, "discord_dm", lambda text: dms_sent.append(text) or True)
    monkeypatch.setattr(chat_watch, "NOTIFY", Path("/nonexistent"))

    landed = chat_watch.escalate(
        [m("1", "Namaslay", DM, content="first"), m("2", "Namaslay", DM, content="second"),
         m("3", "The Winners", DM, topic="t2", content="other")],
        "direct message")

    assert landed
    assert len(chats) == 2                      # one chat per thread, not per message
    assert "first" in chats[0][1] and "second" in chats[0][1]
    assert len(dms_sent) == 2
    assert "Namaslay" in dms_sent[0]


def test_escalate_reports_failure_when_every_path_fails(monkeypatch):
    monkeypatch.setattr(chat_watch, "console_chat", lambda title, seed: None)
    monkeypatch.setattr(chat_watch, "discord_dm", lambda text: False)
    monkeypatch.setattr(chat_watch, "NOTIFY", Path("/nonexistent"))

    # The caller burns the message id on a True, so a False here is the only
    # thing standing between a delivery outage and a DM nobody ever sees.
    assert not chat_watch.escalate([m("1", "Namaslay", DM)], "direct message")
