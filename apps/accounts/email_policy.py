"""Rules: Account (citizen/worker) emails must not duplicate Admin portal emails."""

from __future__ import annotations


def normalize_account_email(email: str | None) -> str:
    return (email or "").strip().lower()


def is_email_reserved_for_admin(email: str | None) -> bool:
    """True if this address is already used by an Admin (separate admins table)."""
    n = normalize_account_email(email)
    if not n:
        return False
    from apps.admins.models import Admin

    return Admin.objects.filter(email__iexact=n).exists()


ADMIN_EMAIL_RESERVED_MESSAGE = (
    "This email is reserved for the admin dashboard. "
    "Use a different email for the citizen or worker app."
)
