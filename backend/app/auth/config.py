import os

from app.db import DATABASE_URL
from app.instance_secrets import load_instance_secrets

# A self-hosted SQLite instance supplies its own generated secrets when unset.
load_instance_secrets(DATABASE_URL)

# Local development and tests only: startup refuses it. Long enough for HS256
# so signing with it raises no key-length warning.
DEV_SESSION_SECRET = "dev-secret-change-me-local-development-only"
SESSION_SECRET: str = os.environ.get("SESSION_SECRET", DEV_SESSION_SECRET)
