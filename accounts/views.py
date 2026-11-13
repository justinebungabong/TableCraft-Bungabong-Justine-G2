from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from .forms import StaffProfileForm, StaffRegistrationForm


@login_required
def signup_view(request):
    if not request.user.is_manager:
        messages.error(request, "Access denied. Only Managers can create staff accounts.")
        return redirect("dashboard:index")

    if request.method == "POST":
        form = StaffRegistrationForm(request.POST)
        if form.is_valid():
            user = form.save()
            messages.success(request, f"Staff account created for {user.get_full_name() or user.username} ({user.get_role_display()}).")
            return redirect("dashboard:index")
    else:
        form = StaffRegistrationForm()

    return render(request, "accounts/signup.html", {"form": form})


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