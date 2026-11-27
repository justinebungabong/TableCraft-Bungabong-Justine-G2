import secrets
from datetime import timedelta
from decimal import Decimal
from django.conf import settings
from django.db import models, transaction
from django.db.models import F, Q
from django.db.models.functions import Lower
from django.utils import timezone


# ISS-05 on_delete review: every foreign key deliberately uses PROTECT.
# Orders, order lines and menu records are audit/financial history, so no delete
# may silently rewrite them. SET_NULL on paid_by/cancelled_by would erase who
# handled the money; CASCADE on OrderItem.order would erase proof of what was
# served. Deactivation/archiving is the reversible way to retire a record.


def generate_qr_token():
    return secrets.token_urlsafe(32)


def generate_public_token():
    return secrets.token_urlsafe(24)


class DiningTable(models.Model):
    table_number = models.CharField(max_length=10, unique=True)
    qr_token = models.CharField(max_length=64, unique=True, default=generate_qr_token)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "dining_table"
        ordering = ["table_number"]

    def __str__(self):
        return f"{self.table_number} ({'Active' if self.is_active else 'Inactive'})"


class MenuCategory(models.Model):
    category_name = models.CharField(max_length=50, unique=True)
    display_order = models.SmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "menu_category"
        ordering = ["display_order", "category_name"]
        verbose_name_plural = "Menu categories"
        constraints = [
            models.CheckConstraint(
                condition=Q(display_order__gte=0) & Q(display_order__lte=999),
                name="chk_category_display_order_range",
            ),
            models.UniqueConstraint(
                Lower("category_name"),
                name="uq_category_name_case_insensitive",
            ),
        ]

    def __str__(self):
        return self.category_name


class MenuItem(models.Model):
    category = models.ForeignKey(
        MenuCategory,
        on_delete=models.PROTECT,
        related_name="items",
    )
    item_name = models.CharField(max_length=100)
    description = models.CharField(max_length=255, blank=True, null=True)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    image_url = models.URLField(max_length=255, blank=True, null=True)
    is_available = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "menu_item"
        ordering = ["category__display_order", "item_name"]
        constraints = [
            models.UniqueConstraint(
                fields=["category", "item_name"],
                name="uq_menu_item_category_name",
            ),
            models.CheckConstraint(
                condition=Q(price__gt=Decimal("0.00")),
                name="chk_menu_item_price_positive",
            ),
            models.UniqueConstraint(
                "category",
                Lower("item_name"),
                name="uq_menu_item_category_name_case_insensitive",
            ),
        ]

    def __str__(self):
        return f"{self.item_name} (₱{self.price})"


class Order(models.Model):
    STATUS_CHOICES = [
        ("Pending Payment", "Pending Payment"),
        ("Paid", "Paid"),
        ("Preparing", "Preparing"),
        ("Ready", "Ready"),
        ("Served", "Served"),
        ("Cancelled", "Cancelled"),
    ]
    PAYMENT_METHOD_CHOICES = [
        ("Cash", "Cash"),
        ("Card", "Card"),
        ("E-Wallet", "E-Wallet"),
    ]
    CANCEL_TYPE_CHOICES = [
        ("Expired", "Expired"),
        ("Cashier", "Cashier"),
        ("Void", "Void"),
    ]

    table = models.ForeignKey(
        DiningTable,
        on_delete=models.PROTECT,
        related_name="orders",
    )
    order_number = models.CharField(max_length=20, unique=True, blank=True)
    public_token = models.CharField(max_length=64, unique=True, default=generate_public_token)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="Pending Payment")
    total_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()

    paid_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="paid_orders",
        null=True,
        blank=True,
    )
    payment_method = models.CharField(max_length=10, choices=PAYMENT_METHOD_CHOICES, null=True, blank=True)
    reference_no = models.CharField(max_length=50, null=True, blank=True)
    amount_tendered = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    change_amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    paid_at = models.DateTimeField(null=True, blank=True)
    preparing_at = models.DateTimeField(null=True, blank=True)
    ready_at = models.DateTimeField(null=True, blank=True)
    served_at = models.DateTimeField(null=True, blank=True)

    cancelled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="cancelled_orders",
        null=True,
        blank=True,
    )
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancel_type = models.CharField(max_length=10, choices=CANCEL_TYPE_CHOICES, null=True, blank=True)
    cancel_reason = models.CharField(max_length=255, null=True, blank=True)

    class Meta:
        db_table = "orders"
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["status", "created_at"], name="idx_orders_status_created"),
            models.Index(fields=["table", "status"], name="idx_orders_table_status"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(total_amount__gte=Decimal("0.00")),
                name="chk_order_total_non_negative",
            ),
            models.CheckConstraint(
                condition=Q(amount_tendered__gte=Decimal("0.00")) | Q(amount_tendered__isnull=True),
                name="chk_order_tendered_non_negative",
            ),
            models.CheckConstraint(
                condition=Q(change_amount__gte=Decimal("0.00")) | Q(change_amount__isnull=True),
                name="chk_order_change_non_negative",
            ),
            models.CheckConstraint(
                condition=Q(status__in=[
                    "Pending Payment", "Paid", "Preparing", "Ready", "Served", "Cancelled",
                ]),
                name="chk_order_status_valid",
            ),
            models.CheckConstraint(
                condition=Q(payment_method__in=["Cash", "Card", "E-Wallet"])
                | Q(payment_method__isnull=True)
                | Q(payment_method=""),
                name="chk_order_payment_method_valid",
            ),
            # Expiry is system-generated (BR-20), so it has no human actor.
            # Cashier/Void cancellations must name who cancelled the order.
            models.CheckConstraint(
                condition=~Q(status="Cancelled")
                | (
                    Q(cancelled_at__isnull=False)
                    & Q(cancel_type__isnull=False)
                    & Q(cancel_type__in=["Expired", "Cashier", "Void"])
                    & (
                        Q(cancelled_by__isnull=False)
                        | Q(cancel_type__isnull=False, cancel_type="Expired")
                    )
                ),
                name="chk_order_cancelled_fields",
            ),
            models.CheckConstraint(
                condition=~Q(status__in=["Paid", "Preparing", "Ready", "Served"])
                | Q(paid_at__isnull=False, paid_by__isnull=False),
                name="chk_order_paid_fields",
            ),
            models.CheckConstraint(
                condition=Q(expires_at__gt=F("created_at")),
                name="chk_order_expires_after_created",
            ),
        ]

    def save(self, *args, **kwargs):
        if not self.expires_at:
            now = self.created_at or timezone.now()
            expiry_minutes = getattr(settings, "ORDER_EXPIRY_MINUTES", 15)
            self.expires_at = now + timedelta(minutes=expiry_minutes)
        # ISS-05: the insert and the order_number update are one unit. A crash
        # between them used to leave a blank (unique!) number behind.
        with transaction.atomic():
            super().save(*args, **kwargs)
            if not self.order_number:
                self.order_number = f"TC-{self.pk:04d}"
                Order.objects.filter(pk=self.pk).update(order_number=self.order_number)

    def __str__(self):
        return f"{self.order_number} ({self.table.table_number} — {self.status})"


class OrderItem(models.Model):
    order = models.ForeignKey(
        Order,
        on_delete=models.PROTECT,
        related_name="items",
    )
    item = models.ForeignKey(
        MenuItem,
        on_delete=models.PROTECT,
        related_name="order_items",
    )
    item_name = models.CharField(max_length=100)
    quantity = models.PositiveSmallIntegerField()
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    line_total = models.DecimalField(max_digits=10, decimal_places=2)
    note = models.CharField(max_length=140, blank=True, null=True)

    class Meta:
        db_table = "order_item"
        indexes = [
            models.Index(fields=["order"], name="idx_order_item_order"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(quantity__gt=0),
                name="chk_order_item_quantity_positive",
            ),
            models.CheckConstraint(
                condition=Q(line_total=F("quantity") * F("unit_price")),
                name="chk_order_item_line_total",
            ),
        ]

    def save(self, *args, **kwargs):
        if not self.item_name:
            self.item_name = self.item.item_name
        if self.unit_price is None:
            self.unit_price = self.item.price
        self.line_total = self.unit_price * self.quantity
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.quantity}x {self.item_name}"