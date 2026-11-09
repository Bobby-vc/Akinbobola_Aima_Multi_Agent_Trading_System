"""Sign-in for the dashboard, using Streamlit's st.login with Google.

Sign-in is on when .streamlit/secrets.toml has an [auth] section (see
.streamlit/secrets.toml.example). Each person who signs in gets their own
practice portfolio. People listed in AIMA_ADMIN_EMAILS can also open the
shared Alpaca account that builds AIMA's track record.

Without an [auth] section, the dashboard runs for one local user on the
account in AIMA_ACCOUNT, as before.
"""
import os

import streamlit as st

from first_ai_agents.database import DEFAULT_ACCOUNT, sign_in_user


def auth_configured() -> bool:
    return st.secrets.load_if_toml_exists() and "auth" in st.secrets


def current_identity() -> dict | None:
    """The signed-in person's details from Google (sub, iss, email, name, ...), or None."""
    return dict(st.user) if st.user.is_logged_in else None


def user_for(identity: dict) -> dict:
    """The AIMA user for a sign-in identity, created on their first sign-in."""
    issuer = identity.get("iss") or identity.get("provider") or "unknown"
    return sign_in_user(issuer, str(identity["sub"]), identity.get("email"), identity.get("name"))


def is_admin(identity: dict) -> bool:
    """Admins are listed by email in AIMA_ADMIN_EMAILS. Only an email Google has verified counts."""
    admins = {e.strip().lower() for e in os.getenv("AIMA_ADMIN_EMAILS", "").split(",") if e.strip()}
    email = (identity.get("email") or "").lower()
    return bool(email) and email in admins and identity.get("email_verified") is True


def accounts_for(user: dict, identity: dict) -> list[str]:
    """The accounts this person may open, their own practice portfolio first."""
    return [user["account"]] + ([DEFAULT_ACCOUNT] if is_admin(identity) else [])
