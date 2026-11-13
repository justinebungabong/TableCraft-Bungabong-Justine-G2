from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from .forms import StaffManageForm, StaffProfileForm, StaffRegistrationForm
from .models import CustomUser


@login_required
def signup_view(request):
    if not request.user.is_manager:
        messages.error(request, "Access denied. Only Managers can create staff accounts.")
        return redirect("dashboard:index")

    if request.method == "POST":
        form = StaffRegistrationForm(request.POST, user=request.user)
        if form.is_valid():
            user = form.save()
            messages.success(request, f"Staff account created for {user.get_full_name() or user.username} ({user.get_role_display()}).")
            return redirect("dashboard:index")
    else:
        form = StaffRegistrationForm(user=request.user)

    return render(request, "accounts/signup.html", {"form": form})


@login_required
def staff_edit_view(request, pk):
    if not request.user.is_manager:
        messages.error(request, "Access denied. Only Managers can edit staff accounts.")
        return redirect("dashboard:index")

    member = get_object_or_404(CustomUser, pk=pk)

    if not request.user.is_superuser and (member.is_superuser or member.role == CustomUser.Role.MANAGER):
        messages.error(request, "Only the Owner can modify Manager or Owner accounts.")
        return redirect("dashboard:index")

    if request.method == "POST":
        form = StaffManageForm(request.POST, instance=member, current_user=request.user)
        if form.is_valid():
            updated_member = form.save(commit=False)
            if updated_member == request.user and not updated_member.is_active:
                messages.error(request, "You cannot deactivate your own active account.")
                return redirect("accounts:staff_edit", pk=member.pk)
            updated_member.save()
            messages.success(request, f"Updated staff record for {updated_member.get_full_name() or updated_member.username}.")
            return redirect("dashboard:index")
    else:
        form = StaffManageForm(instance=member, current_user=request.user)

    return render(request, "accounts/staff_edit.html", {"form": form, "member": member})


@login_required
def staff_toggle_active_view(request, pk):
    if request.method != "POST" or not request.user.is_manager:
        return redirect("dashboard:index")

    member = get_object_or_404(CustomUser, pk=pk)

    if member == request.user:
        messages.error(request, "You cannot deactivate your own account.")
        return redirect("dashboard:index")

    if not request.user.is_superuser and (member.is_superuser or member.role == CustomUser.Role.MANAGER):
        messages.error(request, "Only the Owner can change the status of Manager accounts.")
        return redirect("dashboard:index")

    member.is_active = not member.is_active
    member.save(update_fields=["is_active"])
    status_label = "activated" if member.is_active else "deactivated"
    messages.success(request, f"{member.get_full_name() or member.username} has been {status_label}.")
    return redirect("dashboard:index")


@login_required
def profile_view(request):
    if request.method == "POST":
        form = StaffProfileForm(request.POST, request.FILES, instance=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, "Staff profile updated.")
            return redirect("accounts:profile")
    else:
        form = StaffProfileForm(instance=request.user)

    return render(request, "accounts/profile.html", {"form": form})