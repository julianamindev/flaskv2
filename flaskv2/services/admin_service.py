from typing import Dict
from sqlalchemy import or_, asc, desc
from flaskv2 import db
from flaskv2.models import User

DATETIME_FMT = "%Y-%m-%d %H:%M"

def _fmt(dt):
    return dt.strftime(DATETIME_FMT) if dt else "NULL"

# Whitelist columns allowed for sorting (prevents injection via ?sort=)
ALLOWED_SORTS = {
    "id":          User.id,
    "email":       User.email,
    "username":    User.username,
    "created_date":getattr(User, "created_date"),
    "last_login":  getattr(User, "last_login"),
    "is_active":   getattr(User, "is_active"),
    "is_admin":    getattr(User, "is_admin"),
}

def _user_to_dict(u: User) -> Dict:
    return {
        "id": u.id,
        "email": u.email,
        "username": u.username,

        # created_date in both machine- and display-friendly forms
        "created_date": u.created_date.isoformat() if u.created_date else None,
        "created_date_display": _fmt(u.created_date),

        "is_active": bool(u.is_active),
        "is_admin": bool(u.is_admin),

        # last_login in both forms; show "NULL" when missing
        "last_login": u.last_login.isoformat() if u.last_login else None,
        "last_login_display": _fmt(u.last_login),
    }