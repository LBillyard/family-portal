"""Gmail receipt dedupe (idempotent commit) + subscription name prettify."""

from server import database as db
from server.services import gmail_receipts
from server.services.subscriptions import _is_raw_ref, prettify_name


def _seed_account():
    """Ensure at least one account exists so transactions have a target."""
    existing = db.list_accounts(include_hidden=True)
    if existing:
        return existing[0]["id"]
    aid = db._new_id()
    with db.get_conn() as conn:
        conn.execute(
            "INSERT INTO accounts (id, name, type, balance, institution) VALUES (?, 'Test Current', 'current', 0, 'Test')",
            (aid,),
        )
    return aid


def test_gmail_commit_is_idempotent(client):
    _seed_account()
    user = db.list_users()[0]
    draft = {
        "message_id": "abc123",
        "description": "Amazon order",
        "amount": 19.99,
        "date": "2026-07-01",
        "category": "Shopping",
        "merchant": "Amazon",
    }

    before = len(db.existing_external_ids("gmail:"))
    first = gmail_receipts.commit_drafts([draft], user)
    assert len(first) == 1
    tid = first[0]["id"]

    # Committing the SAME message again must not create a second transaction.
    second = gmail_receipts.commit_drafts([draft], user)
    assert len(second) == 1
    assert second[0]["id"] == tid  # returns the existing row

    ids = db.existing_external_ids("gmail:")
    assert "gmail:abc123" in ids
    assert len(ids) == before + 1, "duplicate gmail transaction created"


def test_is_raw_ref_heuristic():
    for raw in ("0195254311/", "CARE-031459489400", "5180795200100002", "", "12/34"):
        assert _is_raw_ref(raw), f"{raw!r} should be flagged raw"
    for human in ("Google One", "Netflix", "Ultra plan fee", "Amazon Prime", "Spotify UK"):
        assert not _is_raw_ref(human), f"{human!r} should NOT be flagged raw"


def test_prettify_name():
    # A ref with a real word survives as a title-cased merchant.
    assert prettify_name("CARE-031459489400", "CARE") == "Care"
    # Pure-digit refs have no signal — left as-is rather than mangled.
    assert prettify_name("0195254311/", "") == "0195254311/"
    assert prettify_name("5180795200100002", "5180795200100002") == "5180795200100002"
    # Human names are never rewritten.
    assert prettify_name("Google One", "GOOGLE ONE") == "Google One"
