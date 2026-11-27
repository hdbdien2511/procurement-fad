def notifications(request):
    """Số thông báo chưa đọc cho thanh đầu trang (một truy vấn count, chỉ khi đã đăng nhập)."""
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {}
    from apps.notifications.models import Notification

    return {"unread_notification_count": Notification.objects.filter(user=user, read_at__isnull=True).count()}
