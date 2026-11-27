from django import template

from apps.core.money import amount_in_words_vi, format_vnd

register = template.Library()


@register.filter
def vnd(value):
    if value in (None, ""):
        return ""
    return format_vnd(value)


@register.filter
def bang_chu(value):
    if value in (None, ""):
        return ""
    return amount_in_words_vi(value)
