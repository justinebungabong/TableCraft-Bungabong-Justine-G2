from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from .forms import StaffProfileForm, StaffRegistrationForm


def signup_view(request):
    if request.user.is_authenticated:
        return redirect("accounts:profile")

    if request.method == "POST":
        form = StaffRegistrationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            messages.success(request, f"Welcome to TableCraft, {user.first_name or user.username}.")
            return redirect("accounts:profile")
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