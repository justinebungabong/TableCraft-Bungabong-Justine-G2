import re

from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.core.exceptions import ValidationError

from .models import CustomUser

# The model only enforces max_length; keep numbers in a dialable shape.
CONTACT_NUMBER_PATTERN = re.compile(r"^[0-9+()\- ]{7,20}$")
MAX_PROFILE_PHOTO_BYTES = 2 * 1024 * 1024


class ContactNumberMixin:
    """Shared contact-number validation for the three staff forms."""

    def clean_contact_number(self):
        value = (self.cleaned_data.get("contact_number") or "").strip()
        if not value:
            return ""
        if not CONTACT_NUMBER_PATTERN.fullmatch(value):
            raise ValidationError("Enter a valid contact number, e.g. 09171234567.")
        return value


class StaffRegistrationForm(ContactNumberMixin, UserCreationForm):
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


class StaffProfileForm(ContactNumberMixin, forms.ModelForm):
    class Meta:
        model = CustomUser
        fields = ["first_name", "last_name", "email", "contact_number", "profile_photo"]

    def clean_profile_photo(self):
        photo = self.cleaned_data.get("profile_photo")
        if photo and getattr(photo, "size", 0) > MAX_PROFILE_PHOTO_BYTES:
            raise ValidationError("Profile photos must be 2 MB or smaller.")
        return photo


class StaffManageForm(ContactNumberMixin, forms.ModelForm):
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
