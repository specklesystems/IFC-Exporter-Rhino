"""Receive a bundle version outside Automate, for local runs and debugging.

Reads SPECKLE_SERVER_URL and SPECKLE_TOKEN from the environment (or ``.env``);
without a token it falls back to the default local Speckle account.
"""

import os

from dotenv import load_dotenv
from specklepy.api import operations
from specklepy.api.credentials import Account, get_default_account
from specklepy.bundle.model import Model

load_dotenv()


def get_account() -> Account:
    host = os.getenv("SPECKLE_SERVER_URL", "https://app.speckle.systems")
    token = os.getenv("SPECKLE_TOKEN", "")
    if token:
        return Account.from_token(token, host)
    account = get_default_account()
    if account is None:
        raise RuntimeError(
            "No Speckle account found: set SPECKLE_TOKEN (and SPECKLE_SERVER_URL) "
            "in .env, or add an account in the Speckle desktop app."
        )
    return account


def receive_model(project_id: str, model_id: str, version_id: str) -> Model:
    """Download a version's bundle. Close the returned Model when done."""
    account = get_account()
    print(
        f"Receiving {account.serverInfo.url} project={project_id} "
        f"model={model_id} version={version_id}"
    )
    return operations.receive3(account, project_id, model_id, version_id)
