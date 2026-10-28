from functools import wraps
from flask import abort
from flask_login import LoginManager, UserMixin, current_user

login_manager = LoginManager()


class User(UserMixin):
    def __init__(self, record):
        self.id = record["id"]
        self.name = record["name"]
        self.email = record["email"]
        self.role = record["role"]
        self._active = bool(record["is_active"])

    @property
    def is_active(self):
        return self._active

    @classmethod
    def from_record(cls, record):
        return cls(record) if record else None


@login_manager.user_loader
def load_user(user_id):
    from database import get_user
    try:
        user = User.from_record(get_user(int(user_id)))
        return user if user and user.is_active else None
    except (TypeError, ValueError):
        return None


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated:
            return login_manager.unauthorized()
        if current_user.role != "admin":
            abort(403)
        return view(*args, **kwargs)
    return wrapped


def customer_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated:
            return login_manager.unauthorized()
        if current_user.role != "customer":
            abort(403)
        return view(*args, **kwargs)
    return wrapped
