import json
from decimal import Decimal
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST
from .models import DiningTable, MenuCategory, MenuItem, Order, OrderItem
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from .models import generate_qr_token


def expire_overdue_orders(queryset=None):
    """BR-20: Automatically cancel unpaid orders past expires_at."""
    now = timezone.now()
    qs = queryset if queryset is not None else Order.objects.all()
    qs.filter(status="Pending Payment", expires_at__lte=now).update(
        status="Cancelled",
        cancelled_at=now,
        cancel_type="Expired",
        cancel_reason="Expired",
    )


@require_GET
def customer_menu_view(request, qr_token):
    """Feature 1.3.1: Digital Menu & Cart for an active DiningTable QR token (BR-10)."""
    table = get_object_or_404(DiningTable, qr_token=qr_token, is_active=True)
    categories = (
        MenuCategory.objects.filter(is_active=True)
        .prefetch_related("items")
        .order_by("display_order", "category_name")
    )

    menu_sections = []
    for cat in categories:
        active_items = [item for item in cat.items.all() if item.is_active]
        if active_items:
            menu_sections.append({"category": cat, "items": active_items})

    return render(
        request,
        "pos/customer_menu.html",
        {
            "table": table,
            "menu_sections": menu_sections,
        },
    )


@require_GET
def api_menu_availability(request, qr_token):
    """BR-08: Lightweight JSON endpoint polled every 10s while menu tab is visible."""
    table = get_object_or_404(DiningTable, qr_token=qr_token, is_active=True)
    items = MenuItem.objects.filter(category__is_active=True).values(
        "id", "is_available", "is_active", "price"
    )
    availability = {
        str(row["id"]): {
            "is_available": row["is_available"] and row["is_active"],
            "price": str(row["price"]),
        }
        for row in items
    }
    return JsonResponse({"table": table.table_number, "items": availability})


@require_POST
def api_order_submit(request, qr_token):
    """Feature 1.3.2: Atomic order submission enforcing BR-09 through BR-15."""
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({"ok": False, "error": "Invalid request payload."}, status=400)

    raw_lines = payload.get("items", [])
    if not isinstance(raw_lines, list) or not (1 <= len(raw_lines) <= 20):
        return JsonResponse(
            {"ok": False, "error": "An order must contain between 1 and 20 items."},
            status=400,
        )

    merged_lines = {}
    for entry in raw_lines:
        try:
            item_id = int(entry.get("item_id"))
            qty = int(entry.get("quantity", 0))
        except (TypeError, ValueError):
            return JsonResponse({"ok": False, "error": "Invalid item or quantity."}, status=400)

        note = (entry.get("note") or "").strip()
        if len(note) > 140:
            return JsonResponse(
                {"ok": False, "error": "Item notes must be 140 characters or fewer."},
                status=400,
            )

        if item_id in merged_lines:
            merged_lines[item_id]["quantity"] += qty
            if note:
                combined = f"{merged_lines[item_id]['note']}; {note}".strip("; ")
                merged_lines[item_id]["note"] = combined[:140]
        else:
            merged_lines[item_id] = {"quantity": qty, "note": note}

    for line in merged_lines.values():
        if not (1 <= line["quantity"] <= 20):
            return JsonResponse(
                {"ok": False, "error": "Each item quantity must be between 1 and 20."},
                status=400,
            )

    with transaction.atomic():
        table = DiningTable.objects.select_for_update().filter(
            qr_token=qr_token, is_active=True
        ).first()
        if not table:
            return JsonResponse(
                {"ok": False, "error": "This table QR code is invalid or inactive."},
                status=404,
            )

        expire_overdue_orders(Order.objects.filter(table=table))

        pending_count = Order.objects.filter(
            table=table, status="Pending Payment"
        ).count()
        if pending_count >= 3:
            return JsonResponse(
                {
                    "ok": False,
                    "error": "This table already has 3 unpaid orders. Please pay or wait for an order to expire first.",
                },
                status=409,
            )

        db_items = {
            item.id: item
            for item in MenuItem.objects.select_related("category").filter(
                id__in=merged_lines.keys()
            )
        }
        unavailable_names = []
        for item_id in merged_lines:
            item = db_items.get(item_id)
            if (
                not item
                or not item.is_active
                or not item.is_available
                or not item.category.is_active
            ):
                unavailable_names.append(item.item_name if item else f"Item #{item_id}")

        if unavailable_names:
            return JsonResponse(
                {
                    "ok": False,
                    "error": f"Sorry, these items are no longer available: {', '.join(unavailable_names)}.",
                    "unavailable_items": unavailable_names,
                },
                status=409,
            )

        order = Order.objects.create(table=table)
        total = Decimal("0.00")
        order_items = []
        for item_id, line_data in merged_lines.items():
            menu_item = db_items[item_id]
            line_total = menu_item.price * line_data["quantity"]
            total += line_total
            order_items.append(
                OrderItem(
                    order=order,
                    item=menu_item,
                    item_name=menu_item.item_name,
                    quantity=line_data["quantity"],
                    unit_price=menu_item.price,
                    line_total=line_total,
                    note=line_data["note"] or None,
                )
            )

        OrderItem.objects.bulk_create(order_items)
        order.total_amount = total
        order.save(update_fields=["total_amount"])

    return JsonResponse(
        {
            "ok": True,
            "order_number": order.order_number,
            "redirect_url": f"/pos/order/{order.public_token}/",
        }
    )


@require_GET
def customer_order_view(request, public_token):
    """BR-15: Customer order status & receipt page accessed solely via public_token."""
    expire_overdue_orders(Order.objects.filter(public_token=public_token))
    order = get_object_or_404(
        Order.objects.select_related("table").prefetch_related("items"),
        public_token=public_token,
    )
    return render(request, "pos/customer_order.html", {"order": order})


@require_GET
def api_order_status(request, public_token):
    """BR-27: Single small JSON status endpoint polled every 2s until terminal state."""
    expire_overdue_orders(Order.objects.filter(public_token=public_token))
    order = get_object_or_404(Order, public_token=public_token)
    return JsonResponse(
        {
            "order_number": order.order_number,
            "status": order.status,
            "expires_at": order.expires_at.isoformat(),
            "server_now": timezone.now().isoformat(),
            "payment_method": order.payment_method,
            "cancel_reason": order.cancel_reason,
            "is_terminal": order.status in ("Served", "Cancelled"),
        }
    )

def _require_owner(user):
    if not (user.is_superuser or getattr(user, "role", "") == "OWNER"):
        raise PermissionDenied("Only the Owner/Admin can manage tables and QR codes.")


@login_required
def manage_tables_view(request):
    """Feature 1.1.2: Owner/Admin table setup, QR link generation, and soft-deactivation (BR-02, BR-28)."""
    _require_owner(request.user)

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "create":
            table_number = (request.POST.get("table_number") or "").strip().upper()
            if not table_number or len(table_number) > 10:
                messages.error(request, "Table number must be 1 to 10 characters (e.g., T-01).")
            elif DiningTable.objects.filter(table_number__iexact=table_number).exists():
                messages.error(request, f"Table {table_number} already exists.")
            else:
                DiningTable.objects.create(table_number=table_number)
                messages.success(request, f"Added table {table_number} with a new QR token.")
        elif action == "toggle":
            table = get_object_or_404(DiningTable, pk=request.POST.get("table_id"))
            table.is_active = not table.is_active
            table.save(update_fields=["is_active"])
            state = "activated" if table.is_active else "deactivated"
            messages.success(request, f"Table {table.table_number} {state}.")
        elif action == "regenerate":
            table = get_object_or_404(DiningTable, pk=request.POST.get("table_id"))
            table.qr_token = generate_qr_token()
            table.save(update_fields=["qr_token"])
            messages.warning(request, f"Regenerated QR token for {table.table_number}. Old QR codes are now invalid.")
        return redirect("pos:manage_tables")

    tables = DiningTable.objects.all().order_by("table_number")
    return render(request, "pos/manage_tables.html", {"tables": tables})