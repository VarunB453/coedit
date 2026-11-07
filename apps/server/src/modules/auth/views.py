import re

from django.contrib.auth import (
    authenticate,
    get_user_model,
    login,
    logout,
    update_session_auth_hash,
)
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import IntegrityError
from django.http import JsonResponse
from django.middleware.csrf import get_token
from django.views.decorators.http import require_http_methods

from editor.models import UserProfile
from modules.shared.http import error, parse_json_object
from modules.shared.permissions import is_authenticated


def _parse_body(request):
    return parse_json_object(request)


@require_http_methods(["GET"])
def csrf_token(request):
    return JsonResponse({"csrfToken": get_token(request)})


def user_payload(user):
    profile, _ = UserProfile.objects.get_or_create(user=user)
    return {
        "id": user.id,
        "username": user.get_username(),
        "display_name": profile.display_name or user.get_username(),
        "email": user.email,
    }


def display_name(user):
    profile = getattr(user, "profile", None)
    return (profile.display_name if profile else "") or user.get_username()


@require_http_methods(["GET", "POST"])
def auth_session(request):
    if request.method == "GET":
        if not is_authenticated(request):
            return error("Authentication required.", 401)
        return JsonResponse(user_payload(request.user))
    body = _parse_body(request)
    if body is None:
        return error("Request body must be a JSON object.", 400)
    username = body.get("username", "")
    password = body.get("password", "")
    if not isinstance(username, str) or not isinstance(password, str):
        return error("Username or password is incorrect.", 401)
    user = authenticate(request, username=username, password=password)
    if user is None:
        return error("Username or password is incorrect.", 401)
    login(request, user)
    return JsonResponse(user_payload(user))


@require_http_methods(["GET", "PATCH"])
def auth_profile(request):
    if not is_authenticated(request):
        return error("Authentication required.", 401)
    if request.method == "GET":
        return JsonResponse(user_payload(request.user))
    body = _parse_body(request)
    if body is None:
        return error("Request body must be a JSON object.", 400)
    allowed = {"display_name", "email", "current_password", "new_password"}
    if set(body) - allowed:
        return error("Profile fields are invalid.", 400)
    display_name_value = body.get("display_name")
    email = body.get("email")
    if display_name_value is not None and (
        not isinstance(display_name_value, str) or len(display_name_value.strip()) > 100
    ):
        return error("Display name must be 100 characters or fewer.", 400)
    if email is not None and (not isinstance(email, str) or len(email.strip()) > 254):
        return error("Email must be 254 characters or fewer.", 400)
    if email is not None:
        try:
            validate_email(email.strip())
        except ValidationError:
            if email.strip():
                return error("Enter a valid email address.", 400)
    new_password = body.get("new_password")
    if new_password is not None:
        if not isinstance(new_password, str):
            return error("New password must be a string.", 400)
        if not isinstance(
            body.get("current_password"), str
        ) or not request.user.check_password(body["current_password"]):
            return error("Current password is incorrect.", 400)
        try:
            validate_password(new_password, request.user)
        except ValidationError as exception:
            return error(" ".join(exception.messages), 400)
        request.user.set_password(new_password)
    user_update_fields = []
    if email is not None:
        request.user.email = email.strip()
        user_update_fields.append("email")
    if new_password is not None:
        user_update_fields.append("password")
    if user_update_fields:
        request.user.save(update_fields=user_update_fields)
    if display_name_value is not None:
        profile, _ = UserProfile.objects.get_or_create(user=request.user)
        profile.display_name = display_name_value.strip()
        profile.save(update_fields=["display_name"])
    if new_password is not None:
        update_session_auth_hash(request, request.user)
    return JsonResponse(user_payload(request.user))


@require_http_methods(["POST"])
def register(request):
    body = _parse_body(request)
    if body is None:
        return error("Request body must be a JSON object.", 400)
    username = body.get("username")
    password = body.get("password")
    if not isinstance(username, str) or not re.fullmatch(
        r"[A-Za-z0-9_.@+-]{1,150}", username.strip()
    ):
        return error("Enter a valid username.", 400)
    if not isinstance(password, str):
        return error("Password is required.", 400)
    user_model = get_user_model()
    user = user_model(username=username.strip())
    try:
        validate_password(password, user)
        user.set_password(password)
        user.save()
    except ValidationError as exception:
        return error(" ".join(exception.messages), 400)
    except IntegrityError:
        return error("That username is already in use.", 409)
    login(request, user)
    return JsonResponse(user_payload(user), status=201)


@require_http_methods(["POST"])
def end_session(request):
    logout(request)
    return JsonResponse({})
