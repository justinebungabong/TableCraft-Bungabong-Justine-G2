from django.contrib import admin
from .models import DiningTable, MenuCategory, MenuItem, Order, OrderItem, generate_qr_token


def _is_admin(user):
    return user.is_superuser or getattr(user, "role", "") == "OWNER"


def _is_manager_or_admin(user):
    return _is_admin(user) or getattr(user, "role", "") == "MANAGER"


@admin.register(DiningTable)
class DiningTableAdmin(admin.ModelAdmin):
    list_display = ("table_number", "qr_token", "is_active")
    list_filter = ("is_active",)
    readonly_fields = ("qr_token",)
    actions = ["regenerate_qr_tokens", "deactivate_tables"]

    def has_module_permission(self, request):
        return _is_admin(request.user)

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.action(description="Regenerate QR tokens (invalidates old QR codes)")
    def regenerate_qr_tokens(self, request, queryset):
        for table in queryset:
            table.qr_token = generate_qr_token()
            table.save(update_fields=["qr_token"])

    @admin.action(description="Deactivate selected tables")
    def deactivate_tables(self, request, queryset):
        queryset.update(is_active=False)


@admin.register(MenuCategory)
class MenuCategoryAdmin(admin.ModelAdmin):
    list_display = ("category_name", "display_order", "is_active")
    list_editable = ("display_order", "is_active")

    def has_module_permission(self, request):
        return _is_manager_or_admin(request.user)

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(MenuItem)
class MenuItemAdmin(admin.ModelAdmin):
    list_display = ("item_name", "category", "price", "is_available", "is_active", "updated_at")
    list_filter = ("category", "is_available", "is_active")
    list_editable = ("is_available", "is_active")
    search_fields = ("item_name",)

    def has_module_permission(self, request):
        return _is_manager_or_admin(request.user)

    def has_delete_permission(self, request, obj=None):
        return False


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    readonly_fields = ("item", "item_name", "quantity", "unit_price", "line_total", "note")
    can_delete = False


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ("order_number", "table", "status", "total_amount", "payment_method", "created_at", "expires_at")
    list_filter = ("status", "payment_method", "table")
    inlines = [OrderItemInline]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False