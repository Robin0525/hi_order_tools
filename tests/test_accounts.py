from pathlib import Path

from hipersonalization_assistant.accounts import AccountStore


class FakeKeyring:
    def __init__(self):
        self.values = {}

    def get_password(self, service, username):
        return self.values.get((service, username))

    def set_password(self, service, username, password):
        self.values[(service, username)] = password

    def delete_password(self, service, username):
        self.values.pop((service, username), None)


def test_accounts_keep_password_out_of_metadata(tmp_path: Path):
    backend = FakeKeyring()
    path = tmp_path / "accounts.json"
    store = AccountStore(path, backend=backend)

    store.save("seller-one", "secret-password")

    assert store.accounts() == ["seller-one"]
    assert store.last_account() == "seller-one"
    assert store.password("seller-one") == "secret-password"
    assert "secret-password" not in path.read_text(encoding="utf-8")


def test_remove_account_removes_vault_password(tmp_path: Path):
    backend = FakeKeyring()
    store = AccountStore(tmp_path / "accounts.json", backend=backend)
    store.save("seller-one", "secret")

    store.remove("seller-one")

    assert store.accounts() == []
    assert store.password("seller-one") is None
