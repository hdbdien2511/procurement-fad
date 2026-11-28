from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django_otp.plugins.otp_totp.models import TOTPDevice


class Command(BaseCommand):
    help = "Tạo thiết bị TOTP cho người dùng và in provisioning URI"

    def add_arguments(self, parser):
        parser.add_argument("username")

    def handle(self, *args, **opts):
        try:
            user = get_user_model().objects.get(username=opts["username"])
        except get_user_model().DoesNotExist:
            raise CommandError(f"Không có người dùng {opts['username']}")
        if TOTPDevice.objects.filter(user=user, confirmed=True).exists():
            raise CommandError("Người dùng đã có thiết bị TOTP.")
        device = TOTPDevice.objects.create(user=user, name="default", confirmed=True)
        self.stdout.write(device.config_url)
