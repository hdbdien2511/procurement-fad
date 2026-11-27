from django.core.validators import RegexValidator
from django.db import models
from django.db.models import Q


class Setting(models.Model):
    key = models.CharField("Khoá", max_length=100, unique=True)
    value = models.JSONField("Giá trị")

    def __str__(self):
        return self.key


class ExchangeRate(models.Model):
    currency = models.CharField(
        "Ngoại tệ", max_length=3, validators=[RegexValidator(r"^[A-Z]{3}$", "Mã ngoại tệ gồm 3 chữ cái.")]
    )
    date = models.DateField("Ngày hiệu lực")
    rate = models.DecimalField("Tỷ giá", max_digits=12, decimal_places=4)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["currency", "date"], name="uniq_exchangerate_currency_date"),
            models.CheckConstraint(condition=Q(rate__gt=0), name="exchangerate_rate_positive"),
        ]

    def clean(self):
        from django.core.exceptions import ValidationError

        if self.currency:
            self.currency = self.currency.strip().upper()
        if self.rate is not None and self.rate <= 0:
            raise ValidationError({"rate": "Tỷ giá phải lớn hơn 0."})

    def save(self, *args, **kwargs):
        if self.currency:
            self.currency = self.currency.strip().upper()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.currency} {self.date} {self.rate}"


class NumberSequence(models.Model):
    prefix = models.CharField(max_length=10)
    year = models.PositiveIntegerField()
    last = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["prefix", "year"], name="uniq_numbersequence_prefix_year")]
