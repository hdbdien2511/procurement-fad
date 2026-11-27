from django import forms

from .models import EmailSettings


class EmailSettingsForm(forms.ModelForm):
    password = forms.CharField(
        label="Mật khẩu",
        required=False,
        widget=forms.PasswordInput(render_value=False, attrs={"autocomplete": "new-password"}),
        help_text="Để trống để giữ nguyên mật khẩu hiện tại.",
    )

    class Meta:
        model = EmailSettings
        fields = ["host", "port", "use_tls", "use_ssl", "username", "from_address", "timeout_seconds"]

    field_order = ["host", "port", "use_tls", "use_ssl", "username", "password", "from_address", "timeout_seconds"]

    def clean_port(self):
        port = self.cleaned_data["port"]
        if not 1 <= port <= 65535:
            raise forms.ValidationError("Cổng phải từ 1 đến 65535.")
        return port

    def clean_timeout_seconds(self):
        t = self.cleaned_data["timeout_seconds"]
        if not 1 <= t <= 120:
            raise forms.ValidationError("Thời gian chờ phải từ 1 đến 120 giây.")
        return t
