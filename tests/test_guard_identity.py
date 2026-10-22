"""The identity guard stops Alex's identifiers in web requests, with controls.

Every case uses a fake identity, so the test never reads the real .env.
"""

from conftest import load_script

g = load_script(".claude/hooks/guard-identity.py")

ENV = {
    "MYKCMO_CONTACT_FIRST": "Pat",
    "MYKCMO_CONTACT_LAST": "Quimby",
    "MYKCMO_CONTACT_EMAIL": "pat.quimby@example.org",
    "MYKCMO_CONTACT_PHONE": "(555) 010-4477",
    "MYKCMO_HOME_ADDRESS": "123 Fake Street, Springfield, MO 00000",
}


def bash(cmd):
    return g.decide("Bash", {"command": cmd}, ENV)


def test_email_in_user_agent_is_stopped():
    assert bash('curl -s -A "MIST (pat.quimby@example.org)" https://api.weather.gov/points/1,2')


def test_url_encoded_email_in_query_is_stopped():
    assert bash("curl 'https://x.test/unsub?email=pat.quimby%40example.org'")


def test_phone_and_street_are_stopped():
    assert bash("curl -d 'phone=555-010-4477' https://x.test/form")
    assert bash("curl --data-urlencode 'addr=123 Fake Street' https://x.test/geo")


def test_name_in_header_is_stopped_but_name_elsewhere_passes():
    assert bash("curl -H 'User-Agent: Quimby research' https://x.test")
    assert bash("curl https://x.test/search?q=Quimby") is None


def test_identity_header_with_any_value_is_stopped():
    assert bash("curl -H 'From: someone@else.test' https://x.test")
    assert bash("curl -H 'X-On-Behalf-Of: user' https://x.test")


def test_python_requests_code_is_checked():
    assert bash("python3 -c \"import requests; requests.get('https://x.test', headers={'User-Agent': 'pat.quimby@example.org'})\"")


def test_ordinary_requests_pass():
    assert bash("curl -s -A 'exobrain-harness/1.0 (+https://github.com/BaesTheorem/exobrain-harness)' https://api.weather.gov/x") is None
    assert bash("curl -s https://example.com") is None


def test_non_network_commands_pass():
    assert bash("git log --author pat.quimby@example.org") is None
    assert bash("grep pat.quimby@example.org notes.md") is None


def test_loopback_only_passes():
    assert bash("curl -d 'email=pat.quimby@example.org' http://127.0.0.1:5014/x") is None
    assert bash("curl http://127.0.0.1:5014/x https://x.test/?e=pat.quimby@example.org")


def test_webfetch_url_is_checked():
    assert g.decide("WebFetch", {"url": "https://x.test/?e=pat.quimby@example.org"}, ENV)
    assert g.decide("WebFetch", {"url": "https://x.test/"}, ENV) is None


def test_write_with_header_identity_is_stopped_but_plain_mention_passes():
    assert g.decide("Write", {"content": "UA = 'bot'\nheaders = {'User-Agent': 'pat.quimby@example.org'}"}, ENV)
    assert g.decide("Write", {"content": "Contact: pat.quimby@example.org"}, ENV) is None


def test_canary_is_stopped_with_empty_env():
    assert g.decide("Bash", {"command": "curl -A __MIST_IDENTITY_CANARY__ https://x.test"}, {})


def test_prose_with_a_url_is_not_a_request():
    # A heredoc that writes docs: a URL and "User-Agent" near the name, no client.
    assert bash("python3 - <<'X'\ns='User-Agent rule for Pat, see https://x.test'\nX") is None
