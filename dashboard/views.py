from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from accounts.models import CustomUser


@login_required
def index_view(request):
    staff_members = CustomUser.objects.order_by("role", "first_name", "username")
    active_staff = staff_members.filter(is_active=True)

    context = {
        "staff_members": staff_members,
        "total_staff": active_staff.count(),
        "manager_count": active_staff.filter(role=CustomUser.Role.MANAGER).count(),
        "cashier_count": active_staff.filter(role=CustomUser.Role.CASHIER).count(),
        "kitchen_count": active_staff.filter(role=CustomUser.Role.KITCHEN).count(),
    }
    return render(request, "dashboard/index.html", context)