import re

from django.conf import settings
from django.core.checks import Critical
from django.core.exceptions import ValidationError

from .models import validate_blacklist_hours, validate_retention

_planb_settings_checks = []
_is_planb_settings_check = (lambda x: _planb_settings_checks.append(x) or x)


def check_planb_settings(app_configs, **kwargs):
    errors = []
    for checkfunc in _planb_settings_checks:
        errors.extend(checkfunc())
    return errors


@_is_planb_settings_check
def _settings__planb_blacklist_hours():
    if settings.PLANB_BLACKLIST_HOURS:
        try:
            validate_blacklist_hours(settings.PLANB_BLACKLIST_HOURS)
        except ValidationError as e:
            return [Critical(
                'settings.PLANB_BLACKLIST_HOURS is invalid', hint=e.message,
                id='planb.E001')]
    return []


@_is_planb_settings_check
def _settings__planb_retention():
    if settings.PLANB_RETENTION:
        try:
            validate_retention(settings.PLANB_RETENTION)
        except ValidationError as e:
            return [Critical(
                'settings.PLANB_RETENTION is invalid', hint=e.message,
                id='planb.E002')]
    return []


@_is_planb_settings_check
def _settings__planb_prefix():
    if (settings.PLANB_PREFIX
            and not re.match(r'^[a-zA-Z]+$', settings.PLANB_PREFIX)):
        return [Critical(
            'PLANB_PREFIX can only contain ascii letters',
            id='planb.E003')]
    return []


@_is_planb_settings_check
def _settings__secret_key():
    if len(getattr(settings, 'SECRET_KEY', '')) < 20:
        return [Critical(
            'settings.STATIC_KEY is too short',
            hint='Please use pwgen -ys 58', id='planb.E004')]
    return []
