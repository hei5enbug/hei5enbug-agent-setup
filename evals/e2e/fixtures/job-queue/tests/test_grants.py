from jobq.grants import GrantStore


def test_a_grant_is_kept_per_session(tmp_path):
    store = GrantStore(tmp_path / "grants.json")
    store.grant("s1", "write")
    assert store.has("s1", "write")
    assert not store.has("s2", "write")


def test_revoking_a_session_drops_its_grants(tmp_path):
    store = GrantStore(tmp_path / "grants.json")
    store.grant("s1", "write")
    store.revoke_session("s1")
    assert not store.has("s1", "write")
