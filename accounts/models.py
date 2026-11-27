from django.contrib.auth.models import AbstractUser
from django.db import models


class CustomUser(AbstractUser):
    class Role(models.TextChoices):
        CASHIER = "CASHIER", "Cashier"
        KITCHEN = "KITCHEN", "Kitchen Staff"
        MANAGER = "MANAGER", "Manager"

    email = models.EmailField(unique=True)
    role = models.CharField(
        max_length=15,
        choices=Role.choices,
        default=Role.CASHIER,
    )
    contact_number = models.CharField(max_length=20, blank=True)
    profile_photo = models.ImageField(upload_to="profiles/", blank=True, null=True)

    @property
    def is_manager(self):
        return self.role == self.Role.MANAGER

    @property
    def display_role(self):
        if self.is_superuser:
            return "Owner"
        return self.get_role_display()

    @property
    def can_access_cashier(self):
        return self.role in (self.Role.CASHIER, self.Role.MANAGER)

    @property
    def can_access_kitchen(self):
        return self.role in (self.Role.KITCHEN, self.Role.MANAGER)

    @property
    def has_profile_photo(self):
        """True only when a photo is set *and* the file still exists in storage.

        The database can outlive a deleted upload, so checking the field alone
        renders a broken image; templates use this instead.
        """
        if not self.profile_photo:
            return False
        try:
            return self.profile_photo.storage.exists(self.profile_photo.name)
        except (OSError, ValueError):
            return False

    def __str__(self):
        return f"{self.username} ({self.get_role_display()})"