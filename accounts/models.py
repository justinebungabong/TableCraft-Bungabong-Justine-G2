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
    def can_access_cashier(self):
        return self.role in (self.Role.CASHIER, self.Role.MANAGER)

    @property
    def can_access_kitchen(self):
        return self.role in (self.Role.KITCHEN, self.Role.MANAGER)

    def __str__(self):
        return f"{self.username} ({self.get_role_display()})"