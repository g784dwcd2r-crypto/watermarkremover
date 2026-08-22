"""CSRF protection using the double-submit cookie pattern.

Session cookies are ``SameSite=Lax``, which already blocks cross-site form
posts, but the API also accepts requests from a first-party SPA on another
port during development. Unsafe methods therefore require a header that
matches a non-HttpOnly cookie: script on another origin can neither read that
cookie nor set the header.
"""

from __future__ import annotations

from fastapi import Request

from .tokens import constant_time_equals, generate_token

CSRF_HEADER = "X-CSRF-Token"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})


class CSRFError(Exception):
    """The CSRF token was missing or did not match."""


def issue_csrf_token() -> str:
    return generate_token()


def verify_csrf(request: Request, cookie_name: str) -> None:
    if request.method in SAFE_METHODS:
        return
    cookie_value = request.cookies.get(cookie_name)
    header_value = request.headers.get(CSRF_HEADER)
    if not cookie_value or not header_value:
        raise CSRFError("This request needs a CSRF token. Reload the page and try again.")
    if not constant_time_equals(cookie_value, header_value):
        raise CSRFError("The CSRF token did not match. Reload the page and try again.")
