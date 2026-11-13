from django import forms
from django.contrib.auth.forms import UserCreationForm
from .models import CustomUser


class StaffRegistrationForm(UserCreationForm):
    first_name = forms.CharField(max_length=150, required=True)
    last_name = forms.CharField(max_length=150, required=True)
    email = forms.EmailField(required=True)

    class Meta:
        model = CustomUser
        fields = [
            "username",
            "first_name",
            "last_name",
            "email",
            "role",
            "contact_number",
            "password1",
            "password2",
        ]


class StaffProfileForm(forms.ModelForm):
    class Meta:
        model = CustomUser
        fields = ["first_name", "last_name", "email", "contact_number", "profile_photo"]