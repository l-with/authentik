"""passbook audit models"""
from datetime import timedelta
from json import dumps, loads
from logging import getLogger

from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext as _
from ipware import get_client_ip

from passbook.lib.models import CreatedUpdatedModel, UUIDModel

LOGGER = getLogger(__name__)

class AuditEntry(UUIDModel):
    """An individual audit log entry"""

    ACTION_LOGIN = 'login'
    ACTION_LOGIN_FAILED = 'login_failed'
    ACTION_LOGOUT = 'logout'
    ACTION_AUTHORIZE_APPLICATION = 'authorize_application'
    ACTION_SUSPICIOUS_REQUEST = 'suspicious_request'
    ACTION_SIGN_UP = 'sign_up'
    ACTION_PASSWORD_RESET = 'password_reset' # noqa
    ACTION_INVITE_CREATED = 'invitation_created'
    ACTION_INVITE_USED = 'invitation_used'
    ACTIONS = (
        (ACTION_LOGIN, ACTION_LOGIN),
        (ACTION_LOGIN_FAILED, ACTION_LOGIN_FAILED),
        (ACTION_LOGOUT, ACTION_LOGOUT),
        (ACTION_AUTHORIZE_APPLICATION, ACTION_AUTHORIZE_APPLICATION),
        (ACTION_SUSPICIOUS_REQUEST, ACTION_SUSPICIOUS_REQUEST),
        (ACTION_SIGN_UP, ACTION_SIGN_UP),
        (ACTION_PASSWORD_RESET, ACTION_PASSWORD_RESET),
        (ACTION_INVITE_CREATED, ACTION_INVITE_CREATED),
        (ACTION_INVITE_USED, ACTION_INVITE_USED),
    )

    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    action = models.TextField(choices=ACTIONS)
    date = models.DateTimeField(auto_now_add=True)
    app = models.TextField()
    _context = models.TextField()
    _context_cache = None
    request_ip = models.GenericIPAddressField()
    created = models.DateTimeField(auto_now_add=True)

    @property
    def context(self):
        """Load context data and load json"""
        if not self._context_cache:
            self._context_cache = loads(self._context)
        return self._context_cache

    @staticmethod
    def create(action, request, **kwargs):
        """Create AuditEntry from arguments"""
        client_ip, _ = get_client_ip(request)
        user = request.user
        if isinstance(user, AnonymousUser):
            user = kwargs.get('user', None)
        entry = AuditEntry.objects.create(
            action=action,
            user=user,
            # User 255.255.255.255 as fallback if IP cannot be determined
            request_ip=client_ip or '255.255.255.255',
            _context=dumps(kwargs))
        LOGGER.debug("Logged %s from %s (%s)", action, request.user, client_ip)
        return entry

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("you may not edit an existing %s" % self._meta.model_name)
        super().save(*args, **kwargs)

    class Meta:

        verbose_name = _('Audit Entry')
        verbose_name_plural = _('Audit Entries')


class LoginAttempt(CreatedUpdatedModel):
    """Track failed login-attempts"""

    target_uid = models.CharField(max_length=254)
    request_ip = models.GenericIPAddressField()
    attempts = models.IntegerField(default=1)

    @staticmethod
    def attempt(target_uid, request):
        """Helper function to create attempt or count up existing one"""
        client_ip, _ = get_client_ip(request)
        # Since we can only use 254 chars for target_uid, truncate target_uid.
        target_uid = target_uid[:254]
        time_threshold = timezone.now() - timedelta(minutes=10)
        existing_attempts = LoginAttempt.objects.filter(
            target_uid=target_uid,
            request_ip=client_ip,
            last_updated__gt=time_threshold).order_by('created')
        if existing_attempts.exists():
            attempt = existing_attempts.first()
            attempt.attempts += 1
            attempt.save()
            LOGGER.debug("Increased attempts on %s", attempt)
        else:
            attempt = LoginAttempt.objects.create(
                target_uid=target_uid,
                request_ip=client_ip)
            LOGGER.debug("Created new attempt %s", attempt)

    def __str__(self):
        return "LoginAttempt to %s from %s (x%d)" % (self.target_uid,
                                                     self.request_ip, self.attempts)

    class Meta:

        unique_together = (('target_uid', 'request_ip', 'created'),)
