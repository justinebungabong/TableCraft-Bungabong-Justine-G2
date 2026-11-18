from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render

from .forms import MenuCategoryForm, MenuItemForm
from .models import MenuCategory, MenuItem


def _require_menu_manager(user):
    """Menu maintenance is shared by the Owner and Manager roles."""
    if not (user.is_superuser or getattr(user, "role", "") == "MANAGER"):
        raise PermissionDenied("Only the Owner or a Manager can manage menu data.")


@login_required
def manage_menu_view(request):
    """Feature 1.2.x: category and menu-item maintenance for Owner and Manager."""
    _require_menu_manager(request.user)

    category_form = MenuCategoryForm(prefix="category")
    item_form = MenuItemForm(prefix="item")

    if request.method == "POST":
        action = request.POST.get("action")

        if action == "create_category":
            category_form = MenuCategoryForm(request.POST, prefix="category")
            if category_form.is_valid():
                category = category_form.save()
                messages.success(request, f"Added menu category {category.category_name}.")
                return redirect("pos:manage_menu")
            messages.error(request, "The category could not be saved. Check the highlighted fields.")

        elif action == "create_item":
            item_form = MenuItemForm(request.POST, prefix="item")
            if item_form.is_valid():
                item = item_form.save()
                messages.success(request, f"Added {item.item_name} to {item.category.category_name}.")
                return redirect("pos:manage_menu")
            messages.error(request, "The menu item could not be saved. Check the highlighted fields.")

        elif action == "toggle_category":
            category = get_object_or_404(MenuCategory, pk=request.POST.get("category_id"))
            category.is_active = not category.is_active
            category.save(update_fields=["is_active"])
            state = "archived" if not category.is_active else "restored"
            messages.success(request, f"Category {category.category_name} {state}.")
            return redirect("pos:manage_menu")

        elif action in {"toggle_item_available", "toggle_item_active"}:
            item = get_object_or_404(MenuItem, pk=request.POST.get("item_id"))
            if action == "toggle_item_available":
                item.is_available = not item.is_available
                item.save(update_fields=["is_available", "updated_at"])
                state = "available" if item.is_available else "sold out"
                messages.success(request, f"{item.item_name} marked {state}.")
            else:
                item.is_active = not item.is_active
                item.save(update_fields=["is_active", "updated_at"])
                state = "restored" if item.is_active else "archived"
                messages.success(request, f"{item.item_name} {state}.")
            return redirect("pos:manage_menu")

    categories = MenuCategory.objects.prefetch_related("items").order_by(
        "display_order", "category_name"
    )
    return render(
        request,
        "pos/manage_menu.html",
        {
            "categories": categories,
            "category_form": category_form,
            "item_form": item_form,
            "item_count": MenuItem.objects.count(),
            "sold_out_count": MenuItem.objects.filter(is_available=False).count(),
        },
    )


@login_required
def menu_item_edit_view(request, pk):
    """Edit an existing menu item without leaving the manager workflow."""
    _require_menu_manager(request.user)
    item = get_object_or_404(MenuItem, pk=pk)

    if request.method == "POST":
        form = MenuItemForm(request.POST, instance=item)
        if form.is_valid():
            form.save()
            messages.success(request, f"Updated {item.item_name}.")
            return redirect("pos:manage_menu")
    else:
        form = MenuItemForm(instance=item)

    return render(request, "pos/menu_item_edit.html", {"form": form, "item": item})
