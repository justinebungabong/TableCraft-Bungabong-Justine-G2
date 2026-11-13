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

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user and not user.is_superuser:
            self.fields["role"].choices = [
                choice for choice in CustomUser.Role.choices
                if choice[0] != CustomUser.Role.MANAGER
            ]


class StaffProfileForm(forms.ModelForm):
    class Meta:
        model = CustomUser
        fields = ["first_name", "last_name", "email", "contact_number", "profile_photo"]

class StaffManageForm(forms.ModelForm):
    first_name = forms.CharField(max_length=150, required=True)
    last_name = forms.CharField(max_length=150, required=True)
    email = forms.EmailField(required=True)

    class Meta:
        model = CustomUser
        fields = ["first_name", "last_name", "email", "role", "contact_number", "is_active"]

    def __init__(self, *args, current_user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if current_user and not current_user.is_superuser:
            self.fields["role"].choices = [
                choice for choice in CustomUser.Role.choices
                if choice[0] != CustomUser.Role.MANAGER
            ]