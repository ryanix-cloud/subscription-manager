"""Compatibility entry point for the existing course project."""
from repository import Repository


def authenticate_user(login, password):
    try:
        return Repository().authenticate(login, password), None
    except Exception as error:
        return None, str(error)
