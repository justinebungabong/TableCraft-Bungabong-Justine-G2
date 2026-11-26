"""PD3 hardening tests: tables, menu, customer menu, ordering API, access control.

Every behaviour asserted here was first verified end-to-end in a real browser
(Playwright) against the same views; these tests pin it so it cannot regress.
Runs on in-memory SQLite, never on the real database (see tablecraft.settings).
"""

import json
from decimal import Decimal

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import CustomUser
from pos.models import DiningTable, MenuCategory, MenuItem, Order, OrderItem

LOGIN = reverse("accounts:login")


def make_user(username, role=CustomUser.Role.CASHIER, is_superuser=False, **extra):
    user = CustomUser.objects.create_user(
        username=username,
        password="Tablecraft#2026",
        email=extra.pop("email", f"{username}@example.com"),
        role=role,
        **extra,
    )
    if is_superuser:
        user.is_superuser = True
        user.is_staff = True
        user.save(update_fields=["is_superuser", "is_staff"])
    return user


class TableCraftTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = make_user("owner", role=CustomUser.Role.MANAGER, is_superuser=True)
        cls.manager = make_user("manager", role=CustomUser.Role.MANAGER)
        cls.cashier = make_user("cashier", role=CustomUser.Role.CASHIER)
        cls.kitchen = make_user("kitchen", role=CustomUser.Role.KITCHEN)
        cls.inactive = make_user("inactive", role=CustomUser.Role.CASHIER, is_active=False)

        cls.main = MenuCategory.objects.create(category_name="Main", display_order=1)
        cls.milk_tea = MenuCategory.objects.create(category_name="Milk Tea", display_order=1)
        cls.snacks = MenuCategory.objects.create(category_name="Snacks", display_order=2)
        cls.item = MenuItem.objects.create(
            category=cls.main, item_name="Fried Chicken", price=Decimal("100.00")
        )
        cls.table = DiningTable.objects.create(table_number="T1")

    def login(self, username="owner"):
        self.assertTrue(self.client.login(username=username, password="Tablecraft#2026"))


class TablesTests(TableCraftTestCase):
    # --- access control -----------------------------------------------------
    def test_anonymous_redirected_to_login(self):
        response = self.client.get(reverse("pos:manage_tables"))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith(LOGIN))

    def test_owner_can_open_tables(self):
        self.login("owner")
        self.assertEqual(self.client.get(reverse("pos:manage_tables")).status_code, 200)

    def test_manager_cannot_manage_tables(self):
        self.login("manager")
        self.assertEqual(self.client.get(reverse("pos:manage_tables")).status_code, 403)

    def test_cashier_cannot_manage_tables(self):
        self.login("cashier")
        self.assertEqual(self.client.get(reverse("pos:manage_tables")).status_code, 403)
        response = self.client.post(
            reverse("pos:manage_tables"), {"action": "create", "table_number": "T9"}
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(DiningTable.objects.filter(table_number="T9").exists())

    def test_kitchen_cannot_manage_tables(self):
        self.login("kitchen")
        self.assertEqual(self.client.get(reverse("pos:manage_tables")).status_code, 403)

    def test_dead_owner_role_check_not_used(self):
        """A user with role 'OWNER' but no is_superuser flag gets no owner rights."""
        make_user("impostor", role="OWNER")
        self.assertTrue(self.client.login(username="impostor", password="Tablecraft#2026"))
        self.assertEqual(self.client.get(reverse("pos:manage_tables")).status_code, 403)

    # --- create -------------------------------------------------------------
    def test_create_table_normalises_and_uppercases(self):
        self.login()
        response = self.client.post(
            reverse("pos:manage_tables"), {"action": "create", "table_number": " t-9 "}
        )
        self.assertEqual(response.status_code, 302)
        table = DiningTable.objects.get(table_number="T-9")
        self.assertTrue(table.is_active)
        self.assertTrue(table.qr_token)
        self.assertGreaterEqual(len(table.qr_token), 32)

    def test_create_rejects_blank_and_too_long(self):
        self.login()
        for bad in ("", "   ", "X" * 11):
            self.client.post(reverse("pos:manage_tables"), {"action": "create", "table_number": bad})
        self.assertEqual(DiningTable.objects.count(), 1)

    def test_create_rejects_duplicate_case_insensitive(self):
        self.login()
        self.client.post(reverse("pos:manage_tables"), {"action": "create", "table_number": "t1"})
        self.assertEqual(DiningTable.objects.count(), 1)

    def test_create_accepts_unexpected_characters_known_gap(self):
        """Documents current behaviour: no charset rule on table labels (PD3 step 4 adds it)."""
        self.login()
        self.client.post(reverse("pos:manage_tables"), {"action": "create", "table_number": "@@@"})
        self.assertTrue(DiningTable.objects.filter(table_number="@@@").exists())

    def test_duplicate_label_message(self):
        self.login()
        self.client.post(reverse("pos:manage_tables"), {"action": "create", "table_number": "T1"})
        response = self.client.post(
            reverse("pos:manage_tables"), {"action": "create", "table_number": "t1"}, follow=True
        )
        self.assertContains(response, "already exists")

    def test_create_with_missing_action_does_nothing(self):
        self.login()
        self.client.post(reverse("pos:manage_tables"), {"table_number": "T9"})
        self.assertEqual(DiningTable.objects.count(), 1)

    # --- toggle -------------------------------------------------------------
    def test_toggle_active_flips_and_hides_from_customers(self):
        self.login()
        table = self.table
        token = table.qr_token
        self.client.post(reverse("pos:manage_tables"), {"action": "toggle", "table_id": table.pk})
        table.refresh_from_db()
        self.assertFalse(table.is_active)
        self.assertEqual(self.client.get(reverse("pos:customer_menu", args=[token])).status_code, 404)
        self.client.post(reverse("pos:manage_tables"), {"action": "toggle", "table_id": table.pk})
        table.refresh_from_db()
        self.assertTrue(table.is_active)
        self.assertEqual(self.client.get(reverse("pos:customer_menu", args=[token])).status_code, 200)

    def test_toggle_unknown_table_404(self):
        self.login()
        response = self.client.post(reverse("pos:manage_tables"), {"action": "toggle", "table_id": "999999"})
        self.assertEqual(response.status_code, 404)

    def test_toggle_non_numeric_table_id_500_known_gap(self):
        """Documents current behaviour: get_object_or_404(pk='abc') raises ValueError (step 4 -> 404/400)."""
        self.login()
        self.client.raise_request_exception = False
        response = self.client.post(reverse("pos:manage_tables"), {"action": "toggle", "table_id": "abc"})
        self.assertEqual(response.status_code, 500)

    def test_toggle_on_inactive_table_still_works_for_owner(self):
        self.login()
        table = DiningTable.objects.create(table_number="T9", is_active=False)
        self.client.post(reverse("pos:manage_tables"), {"action": "toggle", "table_id": table.pk})
        table.refresh_from_db()
        self.assertTrue(table.is_active)

    # --- QR rotation --------------------------------------------------------
    def test_regenerate_invalidates_old_token(self):
        self.login()
        table = self.table
        old_token = table.qr_token
        old_url = reverse("pos:customer_menu", args=[old_token])
        self.assertEqual(self.client.get(old_url).status_code, 200)

        self.client.post(reverse("pos:manage_tables"), {"action": "regenerate", "table_id": table.pk})
        table.refresh_from_db()
        self.assertNotEqual(table.qr_token, old_token)
        self.assertEqual(self.client.get(old_url).status_code, 404)
        self.assertEqual(
            self.client.get(reverse("pos:customer_menu", args=[table.qr_token])).status_code, 200
        )

    def test_regenerate_does_not_change_label_or_active(self):
        self.login()
        table = self.table
        self.client.post(reverse("pos:manage_tables"), {"action": "regenerate", "table_id": table.pk})
        table.refresh_from_db()
        self.assertEqual(table.table_number, "T1")
        self.assertTrue(table.is_active)

    def test_regenerate_unknown_table_404(self):
        self.login()
        response = self.client.post(reverse("pos:manage_tables"), {"action": "regenerate", "table_id": "999999"})
        self.assertEqual(response.status_code, 404)

    def test_tokens_unique_across_tables(self):
        a = DiningTable.objects.create(table_number="A")
        b = DiningTable.objects.create(table_number="B")
        self.assertNotEqual(a.qr_token, b.qr_token)


class MenuTests(TableCraftTestCase):
    # --- access control -----------------------------------------------------
    def test_anonymous_redirected(self):
        response = self.client.get(reverse("pos:manage_menu"))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith(LOGIN))

    def test_owner_and_manager_can_manage_menu(self):
        self.login("owner")
        self.assertEqual(self.client.get(reverse("pos:manage_menu")).status_code, 200)
        self.login("manager")
        self.assertEqual(self.client.get(reverse("pos:manage_menu")).status_code, 200)

    def test_cashier_and_kitchen_forbidden(self):
        self.login("cashier")
        self.assertEqual(self.client.get(reverse("pos:manage_menu")).status_code, 403)
        self.login("kitchen")
        self.assertEqual(self.client.get(reverse("pos:manage_menu")).status_code, 403)

    def test_cashier_cannot_post_menu_changes(self):
        self.login("cashier")
        before = MenuItem.objects.count()
        self.client.post(
            reverse("pos:manage_menu"),
            {"action": "create_item", "item-category": self.main.pk, "item-item_name": "Hack",
             "item-price": "1.00", "item-is_available": "on", "item-is_active": "on"},
        )
        self.assertEqual(MenuItem.objects.count(), before)

    def test_edit_requires_manager(self):
        self.login("cashier")
        self.assertEqual(
            self.client.get(reverse("pos:menu_item_edit", args=[self.item.pk])).status_code, 403
        )

    def test_edit_unknown_item_404(self):
        self.login("owner")
        self.assertEqual(self.client.get(reverse("pos:menu_item_edit", args=[999999])).status_code, 404)

    # --- categories ---------------------------------------------------------
    def test_create_category(self):
        self.login()
        self.client.post(
            reverse("pos:manage_menu"),
            {"action": "create_category", "category-category_name": "Dessert", "category-display_order": "5",
             "category-is_active": "on"},
        )
        cat = MenuCategory.objects.get(category_name="Dessert")
        self.assertEqual(cat.display_order, 5)
        self.assertTrue(cat.is_active)

    def test_category_duplicate_exact_rejected(self):
        self.login()
        before = MenuCategory.objects.count()
        self.client.post(
            reverse("pos:manage_menu"),
            {"action": "create_category", "category-category_name": "Main", "category-display_order": "1"},
        )
        self.assertEqual(MenuCategory.objects.count(), before)

    def test_category_blank_rejected(self):
        self.login()
        before = MenuCategory.objects.count()
        self.client.post(
            reverse("pos:manage_menu"),
            {"action": "create_category", "category-category_name": "", "category-display_order": "1"},
        )
        self.assertEqual(MenuCategory.objects.count(), before)

    def test_category_name_max_length(self):
        self.login()
        before = MenuCategory.objects.count()
        self.client.post(
            reverse("pos:manage_menu"),
            {"action": "create_category", "category-category_name": "X" * 51, "category-display_order": "1"},
        )
        self.assertEqual(MenuCategory.objects.count(), before)

    def test_category_duplicate_case_insensitive_known_gap(self):
        """Documents current behaviour: 'main' and 'Main' can coexist (PD3 step 4 fixes)."""
        self.login()
        self.client.post(
            reverse("pos:manage_menu"),
            {"action": "create_category", "category-category_name": "main", "category-display_order": "1"},
        )
        self.assertTrue(MenuCategory.objects.filter(category_name="main").exists())

    def test_category_negative_display_order_known_gap(self):
        """Documents current behaviour: only the HTML widget sets min=0; no server bound (step 4 adds)."""
        self.login()
        self.client.post(
            reverse("pos:manage_menu"),
            {"action": "create_category", "category-category_name": "QA", "category-display_order": "-5"},
        )
        self.assertEqual(MenuCategory.objects.get(category_name="QA").display_order, -5)

    def test_category_display_order_large_value_is_db_dependent_known_gap(self):
        """Documents a portability trap: the 32767 ceiling comes from the database backend.

        PostgreSQL rejects 99999 through the model field's range validators; SQLite has
        no small-integer range, so the same form accepts it. Step 4 adds explicit
        min_value/max_value so the rule no longer depends on the database.
        """
        self.login()
        self.client.post(
            reverse("pos:manage_menu"),
            {"action": "create_category", "category-category_name": "QA", "category-display_order": "99999"},
        )
        self.assertEqual(MenuCategory.objects.filter(category_name="QA").count(), 1)

    def test_category_ordering_ties_break_on_name(self):
        self.main.display_order = 1
        self.main.save()
        self.milk_tea.display_order = 1
        self.milk_tea.save()
        self.snacks.display_order = 2
        self.snacks.save()
        names = list(MenuCategory.objects.order_by("display_order", "category_name").values_list("category_name", flat=True))
        self.assertEqual(names, ["Main", "Milk Tea", "Snacks"])

    def test_archived_category_hidden_from_customers_but_kept_for_managers(self):
        self.login()
        self.client.post(reverse("pos:manage_menu"), {"action": "toggle_category", "category_id": self.snacks.pk})
        self.snacks.refresh_from_db()
        self.assertFalse(self.snacks.is_active)
        self.assertEqual(self.snacks.items.count(), 0)  # no items in Snacks in this fixture
        response = self.client.get(reverse("pos:manage_menu"))
        self.assertContains(response, "Snacks")

    def test_archiving_category_hides_its_items_from_customer_menu(self):
        item = MenuItem.objects.create(category=self.snacks, item_name="Fries", price=Decimal("75.00"))
        token = self.table.qr_token
        self.assertContains(self.client.get(reverse("pos:customer_menu", args=[token])), "Fries")
        self.login()
        self.client.post(reverse("pos:manage_menu"), {"action": "toggle_category", "category_id": self.snacks.pk})
        response = self.client.get(reverse("pos:customer_menu", args=[token]))
        self.assertNotContains(response, "Fries")
        self.assertTrue(MenuItem.objects.filter(pk=item.pk, is_active=True).exists())

    def test_archived_category_not_offered_in_item_form(self):
        self.login()
        self.snacks.is_active = False
        self.snacks.save(update_fields=["is_active"])
        response = self.client.get(reverse("pos:manage_menu"))
        # a form would not offer it; assert via the edit form for an item in it
        item = MenuItem.objects.create(category=self.snacks, item_name="Fries", price=Decimal("75.00"))
        edit = self.client.get(reverse("pos:menu_item_edit", args=[item.pk]))
        html = edit.content.decode()
        self.assertIn('value=""', html)
        self.assertNotIn(f'value="{self.snacks.pk}" selected', html)

    # --- items --------------------------------------------------------------
    def test_create_item(self):
        self.login()
        self.client.post(
            reverse("pos:manage_menu"),
            {"action": "create_item", "item-category": self.main.pk, "item-item_name": "Wintermelon",
             "item-description": "Classic", "item-price": "89.50", "item-image_url": "",
             "item-is_available": "on", "item-is_active": "on"},
        )
        item = MenuItem.objects.get(item_name="Wintermelon")
        self.assertEqual(item.price, Decimal("89.50"))
        self.assertTrue(item.is_available)
        self.assertTrue(item.is_active)

    def test_item_price_must_be_positive(self):
        self.login()
        before = MenuItem.objects.count()
        for price in ("0", "0.00", "-5", "-0.01"):
            self.client.post(
                reverse("pos:manage_menu"),
                {"action": "create_item", "item-category": self.main.pk, "item-item_name": f"QA{price}",
                 "item-price": price, "item-is_available": "on", "item-is_active": "on"},
            )
        self.assertEqual(MenuItem.objects.count(), before)

    def test_item_price_rejects_three_decimal_places(self):
        self.login()
        before = MenuItem.objects.count()
        self.client.post(
            reverse("pos:manage_menu"),
            {"action": "create_item", "item-category": self.main.pk, "item-item_name": "QA", "item-price": "10.999",
             "item-is_available": "on", "item-is_active": "on"},
        )
        self.assertEqual(MenuItem.objects.count(), before)

    def test_item_price_rejects_garbage_and_missing(self):
        self.login()
        before = MenuItem.objects.count()
        for price in ("abc", "", "NaN", "1e999999"):
            self.client.post(
                reverse("pos:manage_menu"),
                {"action": "create_item", "item-category": self.main.pk, "item-item_name": f"QA{price or 'x'}",
                 "item-price": price, "item-is_available": "on", "item-is_active": "on"},
            )
        self.assertEqual(MenuItem.objects.count(), before)

    def test_item_price_within_db_range(self):
        self.login()
        before = MenuItem.objects.count()
        self.client.post(
            reverse("pos:manage_menu"),
            {"action": "create_item", "item-category": self.main.pk, "item-item_name": "QA",
             "item-price": "9999999999.99", "item-is_available": "on", "item-is_active": "on"},
        )
        self.assertEqual(MenuItem.objects.count(), before)

    def test_item_requires_category(self):
        self.login()
        before = MenuItem.objects.count()
        self.client.post(
            reverse("pos:manage_menu"),
            {"action": "create_item", "item-item_name": "QA", "item-price": "1.00",
             "item-is_available": "on", "item-is_active": "on"},
        )
        self.assertEqual(MenuItem.objects.count(), before)

    def test_item_rejects_inactive_category_choice(self):
        self.login()
        self.snacks.is_active = False
        self.snacks.save(update_fields=["is_active"])
        before = MenuItem.objects.count()
        self.client.post(
            reverse("pos:manage_menu"),
            {"action": "create_item", "item-category": self.snacks.pk, "item-item_name": "QA", "item-price": "1.00",
             "item-is_available": "on", "item-is_active": "on"},
        )
        self.assertEqual(MenuItem.objects.count(), before)

    def test_item_name_required_and_max_length(self):
        self.login()
        before = MenuItem.objects.count()
        self.client.post(
            reverse("pos:manage_menu"),
            {"action": "create_item", "item-category": self.main.pk, "item-item_name": "", "item-price": "1.00"},
        )
        self.client.post(
            reverse("pos:manage_menu"),
            {"action": "create_item", "item-category": self.main.pk, "item-item_name": "X" * 101, "item-price": "1.00"},
        )
        self.assertEqual(MenuItem.objects.count(), before)

    def test_description_optional_and_max_length(self):
        self.login()
        self.client.post(
            reverse("pos:manage_menu"),
            {"action": "create_item", "item-category": self.main.pk, "item-item_name": "QA", "item-price": "1.00",
             "item-description": "D" * 300, "item-is_available": "on", "item-is_active": "on"},
        )
        self.assertFalse(MenuItem.objects.filter(item_name="QA").exists())

    def test_duplicate_item_in_same_category_rejected(self):
        self.login()
        before = MenuItem.objects.count()
        self.client.post(
            reverse("pos:manage_menu"),
            {"action": "create_item", "item-category": self.main.pk, "item-item_name": "Fried Chicken",
             "item-price": "1.00", "item-is_available": "on", "item-is_active": "on"},
        )
        self.assertEqual(MenuItem.objects.count(), before)

    def test_same_item_name_in_different_category_allowed(self):
        self.login()
        self.client.post(
            reverse("pos:manage_menu"),
            {"action": "create_item", "item-category": self.snacks.pk, "item-item_name": "Fried Chicken",
             "item-price": "1.00", "item-is_available": "on", "item-is_active": "on"},
        )
        self.assertEqual(MenuItem.objects.filter(item_name="Fried Chicken").count(), 2)

    def test_duplicate_item_case_insensitive_known_gap(self):
        """Documents current behaviour: 'fried chicken' can duplicate 'Fried Chicken' (step 4 fixes)."""
        self.login()
        self.client.post(
            reverse("pos:manage_menu"),
            {"action": "create_item", "item-category": self.main.pk, "item-item_name": "fried chicken",
             "item-price": "1.00", "item-is_available": "on", "item-is_active": "on"},
        )
        self.assertEqual(MenuItem.objects.filter(item_name__iexact="Fried Chicken").count(), 2)

    def test_image_url_rejects_bad_scheme_and_garbage(self):
        self.login()
        before = MenuItem.objects.count()
        for url in ("javascript:alert(1)", "not a url", "http://", "x" * 300):
            self.client.post(
                reverse("pos:manage_menu"),
                {"action": "create_item", "item-category": self.main.pk, "item-item_name": f"QA{before + len(url)}",
                 "item-price": "1.00", "item-image_url": url, "item-is_available": "on", "item-is_active": "on"},
            )
        self.assertEqual(MenuItem.objects.count(), before)

    def test_image_url_accepts_ftp_scheme_known_gap(self):
        """Documents current behaviour: URLValidator allows ftp:// (nothing renders it; step 4 restricts)."""
        self.login()
        self.client.post(
            reverse("pos:manage_menu"),
            {"action": "create_item", "item-category": self.main.pk, "item-item_name": "QA",
             "item-price": "1.00", "item-image_url": "ftp://example.com/x.png",
             "item-is_available": "on", "item-is_active": "on"},
        )
        self.assertTrue(MenuItem.objects.filter(item_name="QA").exists())

    def test_image_url_stored_but_not_rendered_known_gap(self):
        """Documents ISS-06: image_url is validated but no template renders it."""
        MenuItem.objects.create(
            category=self.main, item_name="WithImage", price=Decimal("10.00"),
            image_url="https://example.com/x.png",
        )
        response = self.client.get(reverse("pos:customer_menu", args=[self.table.qr_token]))
        self.assertNotContains(response, "https://example.com/x.png")
        self.assertNotContains(response, "<img")

    # --- sold out / archive -------------------------------------------------
    def test_toggle_sold_out(self):
        self.login()
        self.client.post(reverse("pos:manage_menu"), {"action": "toggle_item_available", "item_id": self.item.pk})
        self.item.refresh_from_db()
        self.assertFalse(self.item.is_available)
        self.client.post(reverse("pos:manage_menu"), {"action": "toggle_item_available", "item_id": self.item.pk})
        self.item.refresh_from_db()
        self.assertTrue(self.item.is_available)

    def test_sold_out_item_still_shown_but_not_orderable(self):
        self.item.is_available = False
        self.item.save(update_fields=["is_available"])
        token = self.table.qr_token
        response = self.client.get(reverse("pos:customer_menu", args=[token]))
        self.assertContains(response, "Fried Chicken")
        self.assertContains(response, "Sold Out")
        response = self.client.post(
            reverse("pos:api_order_submit", args=[token]),
            data=json.dumps({"items": [{"item_id": self.item.pk, "quantity": 1}]}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 409)

    def test_archive_item_hidden_from_customer_but_kept(self):
        self.login()
        token = self.table.qr_token
        self.client.post(reverse("pos:manage_menu"), {"action": "toggle_item_active", "item_id": self.item.pk})
        self.item.refresh_from_db()
        self.assertFalse(self.item.is_active)
        self.assertNotContains(self.client.get(reverse("pos:customer_menu", args=[token])), "Fried Chicken")
        self.assertTrue(MenuItem.objects.filter(pk=self.item.pk).exists())
        self.client.post(reverse("pos:manage_menu"), {"action": "toggle_item_active", "item_id": self.item.pk})
        self.item.refresh_from_db()
        self.assertTrue(self.item.is_active)

    def test_toggle_unknown_item_404(self):
        self.login()
        self.assertEqual(
            self.client.post(reverse("pos:manage_menu"), {"action": "toggle_item_active", "item_id": "999999"}).status_code,
            404,
        )

    def test_non_numeric_item_and_category_ids_500_known_gap(self):
        """Documents current behaviour: get_object_or_404(pk='abc') raises ValueError (step 4 -> 400)."""
        self.login()
        self.client.raise_request_exception = False
        for action, field in (("toggle_item_active", "item_id"), ("toggle_category", "category_id")):
            response = self.client.post(reverse("pos:manage_menu"), {"action": action, field: "abc"})
            self.assertEqual(response.status_code, 500, action)

    def test_unknown_action_does_nothing(self):
        self.login()
        count = MenuItem.objects.count()
        self.client.post(reverse("pos:manage_menu"), {"action": "delete_item", "item_id": self.item.pk})
        self.assertEqual(MenuItem.objects.count(), count)

    def test_no_delete_action_exists(self):
        self.login()
        self.client.post(reverse("pos:manage_menu"), {"action": "delete", "item_id": self.item.pk})
        self.assertTrue(MenuItem.objects.filter(pk=self.item.pk).exists())

    # --- edit ---------------------------------------------------------------
    def test_edit_item_updates_fields(self):
        self.login()
        self.client.post(
            reverse("pos:menu_item_edit", args=[self.item.pk]),
            {"category": self.main.pk, "item_name": "Fried Chicken Jumbo", "description": "Bigger",
             "price": "150.00", "image_url": "", "is_available": "on", "is_active": "on"},
        )
        self.item.refresh_from_db()
        self.assertEqual(self.item.item_name, "Fried Chicken Jumbo")
        self.assertEqual(self.item.price, Decimal("150.00"))

    def test_edit_item_price_must_stay_positive(self):
        self.login()
        response = self.client.post(
            reverse("pos:menu_item_edit", args=[self.item.pk]),
            {"category": self.main.pk, "item_name": "Fried Chicken", "description": "",
             "price": "0", "image_url": "", "is_available": "on", "is_active": "on"},
        )
        self.assertEqual(response.status_code, 200)
        self.item.refresh_from_db()
        self.assertEqual(self.item.price, Decimal("100.00"))

    def test_edit_item_duplicate_rename_rejected(self):
        other = MenuItem.objects.create(category=self.main, item_name="Wintermelon", price=Decimal("89.00"))
        self.login()
        self.client.post(
            reverse("pos:menu_item_edit", args=[other.pk]),
            {"category": self.main.pk, "item_name": "Fried Chicken", "description": "",
             "price": "89.00", "image_url": "", "is_available": "on", "is_active": "on"},
        )
        other.refresh_from_db()
        self.assertEqual(other.item_name, "Wintermelon")

    def test_edit_item_cannot_choose_inactive_category(self):
        self.login()
        self.snacks.is_active = False
        self.snacks.save(update_fields=["is_active"])
        self.client.post(
            reverse("pos:menu_item_edit", args=[self.item.pk]),
            {"category": self.snacks.pk, "item_name": "Fried Chicken", "description": "",
             "price": "100.00", "image_url": "", "is_available": "on", "is_active": "on"},
        )
        self.item.refresh_from_db()
        self.assertEqual(self.item.category_id, self.main.pk)

    # --- stats --------------------------------------------------------------
    def test_stats_present(self):
        self.login()
        response = self.client.get(reverse("pos:manage_menu"))
        self.assertEqual(response.context["item_count"], 1)
        self.assertEqual(response.context["sold_out_count"], 0)

    def test_stats_count_sold_out(self):
        self.item.is_available = False
        self.item.save(update_fields=["is_available"])
        self.login()
        response = self.client.get(reverse("pos:manage_menu"))
        self.assertEqual(response.context["sold_out_count"], 1)

    def test_stats_count_archived_known_gap(self):
        """Documents current behaviour: archived items inflate counts (PD3 step 4 filters is_active)."""
        self.item.is_active = False
        self.item.save(update_fields=["is_active"])
        self.item.is_available = False
        self.item.save(update_fields=["is_available"])
        self.login()
        response = self.client.get(reverse("pos:manage_menu"))
        self.assertEqual(response.context["item_count"], 1)
        self.assertEqual(response.context["sold_out_count"], 1)

    # --- ordering of categories/items on customer menu ----------------------
    def test_customer_menu_hides_inactive_items_and_categories(self):
        MenuItem.objects.create(category=self.main, item_name="Hidden", price=Decimal("1.00"), is_active=False)
        MenuCategory.objects.create(category_name="EmptyCat", is_active=True)
        token = self.table.qr_token
        response = self.client.get(reverse("pos:customer_menu", args=[token]))
        self.assertNotContains(response, "Hidden")
        self.assertNotContains(response, "EmptyCat")  # categories with no active items are skipped

    def test_empty_archived_items_do_not_crash(self):
        self.item.is_active = False
        self.item.save(update_fields=["is_active"])
        response = self.client.get(reverse("pos:customer_menu", args=[self.table.qr_token]))
        self.assertEqual(response.status_code, 200)


class CustomerMenuTests(TableCraftTestCase):
    def test_public_no_login_required(self):
        self.assertEqual(self.client.get(reverse("pos:customer_menu", args=[self.table.qr_token])).status_code, 200)

    def test_unknown_token_404(self):
        self.assertEqual(self.client.get(reverse("pos:customer_menu", args=["nope"])).status_code, 404)

    def test_inactive_table_404(self):
        self.table.is_active = False
        self.table.save(update_fields=["is_active"])
        self.assertEqual(self.client.get(reverse("pos:customer_menu", args=[self.table.qr_token])).status_code, 404)

    def test_pay_at_counter_is_communicated(self):
        response = self.client.get(reverse("pos:customer_menu", args=[self.table.qr_token]))
        self.assertContains(response, "Pay at Counter")

    def test_availability_api_shape(self):
        response = self.client.get(reverse("pos:api_menu_availability", args=[self.table.qr_token]))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["table"], "T1")
        entry = data["items"][str(self.item.pk)]
        self.assertEqual(entry["is_available"], True)
        self.assertEqual(entry["price"], "100.00")

    def test_availability_api_marks_sold_out(self):
        self.item.is_available = False
        self.item.save(update_fields=["is_available"])
        data = self.client.get(reverse("pos:api_menu_availability", args=[self.table.qr_token])).json()
        self.assertFalse(data["items"][str(self.item.pk)]["is_available"])

    def test_availability_api_marks_archived_category_unavailable(self):
        self.item.is_active = False
        self.item.save(update_fields=["is_active"])
        data = self.client.get(reverse("pos:api_menu_availability", args=[self.table.qr_token])).json()
        self.assertFalse(data["items"][str(self.item.pk)]["is_available"])

    def test_availability_api_unknown_token_404(self):
        self.assertEqual(self.client.get(reverse("pos:api_menu_availability", args=["nope"])).status_code, 404)

    def test_availability_api_inactive_table_404(self):
        self.table.is_active = False
        self.table.save(update_fields=["is_active"])
        self.assertEqual(
            self.client.get(reverse("pos:api_menu_availability", args=[self.table.qr_token])).status_code, 404
        )

    def test_customer_order_page_public_token(self):
        order = self.make_order()
        response = self.client.get(reverse("pos:customer_order", args=[order.public_token]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, order.order_number)

    def test_customer_order_unknown_token_404(self):
        self.assertEqual(self.client.get(reverse("pos:customer_order", args=["nope"])).status_code, 404)

    def test_customer_order_does_not_leak_pk(self):
        order = self.make_order()
        response = self.client.get(reverse("pos:customer_order", args=[order.public_token]))
        self.assertNotContains(response, f"/order/{order.pk}/")

    def test_order_status_api(self):
        order = self.make_order()
        response = self.client.get(reverse("pos:api_order_status", args=[order.public_token]))
        data = response.json()
        self.assertEqual(data["order_number"], order.order_number)
        self.assertEqual(data["status"], "Pending Payment")
        self.assertEqual(data["is_terminal"], False)
        self.assertIn("expires_at", data)
        self.assertIn("server_now", data)

    def test_order_status_api_unknown_token_404(self):
        self.assertEqual(self.client.get(reverse("pos:api_order_status", args=["nope"])).status_code, 404)

    def make_order(self):
        order = Order.objects.create(table=self.table, expires_at=timezone.now() + timezone.timedelta(minutes=15))
        OrderItem.objects.create(
            order=order, item=self.item, item_name=self.item.item_name,
            quantity=1, unit_price=self.item.price, line_total=self.item.price,
        )
        order.total_amount = self.item.price
        order.save(update_fields=["total_amount"])
        return order

    def test_order_number_format(self):
        order = self.make_order()
        self.assertRegex(order.order_number, r"^TC-\d{4}$")

    def test_expiry_defaults_to_setting(self):
        order = self.make_order()
        self.assertAlmostEqual((order.expires_at - order.created_at).total_seconds(), 15 * 60, delta=5)

    def test_public_token_not_pk(self):
        order = self.make_order()
        self.assertNotEqual(str(order.public_token), str(order.pk))
        self.assertGreaterEqual(len(order.public_token), 16)


class OrderingApiTests(TableCraftTestCase):
    def setUp(self):
        self.url = reverse("pos:api_order_submit", args=[self.table.qr_token])

    def submit(self, payload, raw=None, content_type="application/json"):
        return self.client.post(self.url, data=raw if raw is not None else json.dumps(payload), content_type=content_type)

    # --- happy path ---------------------------------------------------------
    def test_valid_order(self):
        response = self.submit({"items": [{"item_id": self.item.pk, "quantity": 2}]})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["ok"])
        self.assertIn("order_number", data)
        self.assertIn("redirect_url", data)
        order = Order.objects.get(order_number=data["order_number"])
        self.assertEqual(order.status, "Pending Payment")
        self.assertEqual(order.total_amount, Decimal("200.00"))
        self.assertEqual(order.items.count(), 1)
        item = order.items.first()
        self.assertEqual(item.quantity, 2)
        self.assertEqual(item.unit_price, Decimal("100.00"))
        self.assertEqual(item.line_total, Decimal("200.00"))
        self.assertEqual(item.item_name, "Fried Chicken")  # name snapshotted

    def test_price_is_server_computed_client_total_ignored(self):
        response = self.submit({"items": [{"item_id": self.item.pk, "quantity": 1}], "total_amount": "0.01", "price": "0.01"})
        order = Order.objects.get(order_number=response.json()["order_number"])
        self.assertEqual(order.total_amount, Decimal("100.00"))

    def test_item_name_and_price_snapshotted(self):
        response = self.submit({"items": [{"item_id": self.item.pk, "quantity": 1}]})
        order_number = response.json()["order_number"]
        self.item.item_name = "Renamed"
        self.item.price = Decimal("1.00")
        self.item.save()
        item = Order.objects.get(order_number=order_number).items.first()
        self.assertEqual(item.item_name, "Fried Chicken")
        self.assertEqual(item.unit_price, Decimal("100.00"))

    def test_note_stored(self):
        response = self.submit({"items": [{"item_id": self.item.pk, "quantity": 1, "note": " no onions "}]})
        item = Order.objects.get(order_number=response.json()["order_number"]).items.first()
        self.assertEqual(item.note, "no onions")

    def test_duplicate_lines_merged(self):
        response = self.submit({"items": [
            {"item_id": self.item.pk, "quantity": 1, "note": "a"},
            {"item_id": self.item.pk, "quantity": 2, "note": "b"},
        ]})
        order = Order.objects.get(order_number=response.json()["order_number"])
        self.assertEqual(order.items.count(), 1)
        self.assertEqual(order.items.first().quantity, 3)
        self.assertEqual(order.total_amount, Decimal("300.00"))

    def test_ordering_does_not_require_auth(self):
        self.client.logout()
        self.assertEqual(self.submit({"items": [{"item_id": self.item.pk, "quantity": 1}]}).status_code, 200)

    # --- validation ---------------------------------------------------------
    def test_requires_post(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)

    def test_invalid_json_400(self):
        response = self.submit(None, raw="{not json")
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()["ok"])

    def test_non_object_payload_500_known_gap(self):
        """Documents current behaviour: a JSON array/string body raises AttributeError (step 4 -> 400)."""
        self.client.raise_request_exception = False
        for raw in ("[]", '"x"', "1", "null"):
            response = self.submit(None, raw=raw)
            self.assertEqual(response.status_code, 500, raw)

    def test_missing_items_400(self):
        self.assertEqual(self.submit({}).status_code, 400)

    def test_non_dict_item_entries_500_known_gap(self):
        """Documents current behaviour: entry.get() on a non-dict raises AttributeError (step 4 -> 400)."""
        self.client.raise_request_exception = False
        for entry in ("x", 1, [], None):
            response = self.submit({"items": [entry]})
            self.assertEqual(response.status_code, 500, entry)

    def test_empty_items_400(self):
        self.assertEqual(self.submit({"items": []}).status_code, 400)

    def test_items_not_list_400(self):
        self.assertEqual(self.submit({"items": {}}).status_code, 400)

    def test_items_list_too_long_400(self):
        items = [{"item_id": self.item.pk, "quantity": 1}] * 21
        self.assertEqual(self.submit({"items": items}).status_code, 400)

    def test_item_id_not_integer_400(self):
        for bad in ("abc", None, "", {}, []):
            self.assertEqual(self.submit({"items": [{"item_id": bad, "quantity": 1}]}).status_code, 400, bad)

    def test_quantity_not_integer_400(self):
        for bad in ("abc", None, "", {}, []):
            self.assertEqual(self.submit({"items": [{"item_id": self.item.pk, "quantity": bad}]}).status_code, 400, bad)

    def test_float_quantity_is_truncated_known_gap(self):
        """Documents current behaviour: int(1.9) == 1, so a float quantity is silently truncated."""
        response = self.submit({"items": [{"item_id": self.item.pk, "quantity": 1.9}]})
        self.assertEqual(response.status_code, 200)
        order = Order.objects.get(order_number=response.json()["order_number"])
        self.assertEqual(order.items.first().quantity, 1)

    def test_quantity_bounds(self):
        self.assertEqual(self.submit({"items": [{"item_id": self.item.pk, "quantity": 0}]}).status_code, 400)
        self.assertEqual(self.submit({"items": [{"item_id": self.item.pk, "quantity": -1}]}).status_code, 400)
        self.assertEqual(self.submit({"items": [{"item_id": self.item.pk, "quantity": 20}]}).status_code, 200)
        self.assertEqual(self.submit({"items": [{"item_id": self.item.pk, "quantity": 21}]}).status_code, 400)

    def test_merged_quantity_cannot_exceed_20(self):
        items = [{"item_id": self.item.pk, "quantity": 15}, {"item_id": self.item.pk, "quantity": 15}]
        self.assertEqual(self.submit({"items": items}).status_code, 400)

    def test_note_length_140(self):
        self.assertEqual(self.submit({"items": [{"item_id": self.item.pk, "quantity": 1, "note": "N" * 140}]}).status_code, 200)
        self.assertEqual(self.submit({"items": [{"item_id": self.item.pk, "quantity": 1, "note": "N" * 141}]}).status_code, 400)

    def test_no_orders_created_on_validation_failure(self):
        before = Order.objects.count()
        self.submit({"items": [{"item_id": self.item.pk, "quantity": 0}]})
        self.submit({"items": [{"item_id": 999999, "quantity": 1}]})
        self.submit(None, raw="{not json")
        self.assertEqual(Order.objects.count(), before)
        self.assertEqual(OrderItem.objects.count(), 0)

    # --- availability -------------------------------------------------------
    def test_unknown_item_409(self):
        response = self.submit({"items": [{"item_id": 999999, "quantity": 1}]})
        self.assertEqual(response.status_code, 409)
        self.assertFalse(response.json()["ok"])

    def test_sold_out_item_409(self):
        self.item.is_available = False
        self.item.save(update_fields=["is_available"])
        self.assertEqual(self.submit({"items": [{"item_id": self.item.pk, "quantity": 1}]}).status_code, 409)

    def test_archived_item_409(self):
        self.item.is_active = False
        self.item.save(update_fields=["is_active"])
        self.assertEqual(self.submit({"items": [{"item_id": self.item.pk, "quantity": 1}]}).status_code, 409)

    def test_archived_category_item_409(self):
        self.main.is_active = False
        self.main.save(update_fields=["is_active"])
        self.assertEqual(self.submit({"items": [{"item_id": self.item.pk, "quantity": 1}]}).status_code, 409)

    def test_partial_availability_failure_is_atomic(self):
        other = MenuItem.objects.create(category=self.main, item_name="Other", price=Decimal("5.00"))
        before = Order.objects.count()
        response = self.submit({"items": [
            {"item_id": self.item.pk, "quantity": 1},
            {"item_id": other.pk, "quantity": 1},
            {"item_id": 999999, "quantity": 1},
        ]})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(Order.objects.count(), before)
        self.assertEqual(OrderItem.objects.count(), 0)

    # --- table state --------------------------------------------------------
    def test_inactive_table_404(self):
        self.table.is_active = False
        self.table.save(update_fields=["is_active"])
        response = self.submit({"items": [{"item_id": self.item.pk, "quantity": 1}]})
        self.assertEqual(response.status_code, 404)
        self.assertEqual(Order.objects.count(), 0)

    def test_unknown_token_404(self):
        url = reverse("pos:api_order_submit", args=["nope"])
        response = self.client.post(url, data=json.dumps({"items": [{"item_id": self.item.pk, "quantity": 1}]}),
                                    content_type="application/json")
        self.assertEqual(response.status_code, 404)

    # --- pending cap --------------------------------------------------------
    def test_three_unpaid_order_cap(self):
        for _ in range(3):
            self.assertEqual(self.submit({"items": [{"item_id": self.item.pk, "quantity": 1}]}).status_code, 200)
        response = self.submit({"items": [{"item_id": self.item.pk, "quantity": 1}]})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(Order.objects.filter(status="Pending Payment").count(), 3)

    def test_cap_is_per_table(self):
        other_table = DiningTable.objects.create(table_number="T2")
        for _ in range(3):
            self.submit({"items": [{"item_id": self.item.pk, "quantity": 1}]})
        url = reverse("pos:api_order_submit", args=[other_table.qr_token])
        response = self.client.post(url, data=json.dumps({"items": [{"item_id": self.item.pk, "quantity": 1}]}),
                                    content_type="application/json")
        self.assertEqual(response.status_code, 200)

    def test_paid_orders_do_not_count_toward_cap(self):
        for _ in range(3):
            self.submit({"items": [{"item_id": self.item.pk, "quantity": 1}]})
        Order.objects.update(status="Paid")
        self.assertEqual(self.submit({"items": [{"item_id": self.item.pk, "quantity": 1}]}).status_code, 200)

    # --- expiry -------------------------------------------------------------
    def test_expired_unpaid_order_cancelled_before_next_submit(self):
        """BR-20: an unpaid order past expires_at is cancelled, then the table can order again."""
        self.submit({"items": [{"item_id": self.item.pk, "quantity": 1}]})
        order = Order.objects.get()
        order.expires_at = timezone.now() - timezone.timedelta(seconds=1)
        order.save(update_fields=["expires_at"])

        response = self.submit({"items": [{"item_id": self.item.pk, "quantity": 1}]})
        self.assertEqual(response.status_code, 200)
        order.refresh_from_db()
        self.assertEqual(order.status, "Cancelled")
        self.assertEqual(order.cancel_type, "Expired")

    def test_expired_order_marked_cancelled_and_frees_cap(self):
        for _ in range(3):
            self.submit({"items": [{"item_id": self.item.pk, "quantity": 1}]})
        self.assertEqual(self.submit({"items": [{"item_id": self.item.pk, "quantity": 1}]}).status_code, 409)
        Order.objects.update(expires_at=timezone.now() - timezone.timedelta(minutes=1))
        self.assertEqual(self.submit({"items": [{"item_id": self.item.pk, "quantity": 1}]}).status_code, 200)
        cancelled = Order.objects.filter(status="Cancelled").count()
        self.assertEqual(cancelled, 3)
        cancelled_order = Order.objects.filter(status="Cancelled").first()
        self.assertEqual(cancelled_order.cancel_type, "Expired")
        self.assertEqual(cancelled_order.cancel_reason, "Expired")
        self.assertIsNotNone(cancelled_order.cancelled_at)

    def test_expired_order_not_reset_if_terminal(self):
        order = Order.objects.create(
            table=self.table, status="Paid", expires_at=timezone.now() - timezone.timedelta(minutes=1)
        )
        self.client.get(reverse("pos:api_order_status", args=[order.public_token]))
        order.refresh_from_db()
        self.assertEqual(order.status, "Paid")

    def test_expiry_only_applies_to_pending_payment(self):
        order = Order.objects.create(
            table=self.table, status="Served", expires_at=timezone.now() - timezone.timedelta(minutes=1)
        )
        self.client.get(reverse("pos:customer_order", args=[order.public_token]))
        order.refresh_from_db()
        self.assertEqual(order.status, "Served")

    def test_expiry_boundary_future_not_cancelled(self):
        self.submit({"items": [{"item_id": self.item.pk, "quantity": 1}]})
        order = Order.objects.get()
        order.expires_at = timezone.now() + timezone.timedelta(minutes=1)
        order.save(update_fields=["expires_at"])
        self.client.get(reverse("pos:customer_order", args=[order.public_token]))
        order.refresh_from_db()
        self.assertEqual(order.status, "Pending Payment")


class ErrorPageTests(TableCraftTestCase):
    """Custom 404/500 pages (hardening/error-pages). DEBUG must be False."""

    def test_404_branded_anonymous(self):
        with override_settings(DEBUG=False):
            response = self.client.get("/definitely-not-a-page/")
        self.assertEqual(response.status_code, 404)
        self.assertTemplateUsed(response, "404.html")
        self.assertContains(response, "TableCraft", status_code=404)

    def test_404_branded_signed_in(self):
        self.login()
        with override_settings(DEBUG=False):
            response = self.client.get("/definitely-not-a-page/")
        self.assertEqual(response.status_code, 404)
        self.assertTemplateUsed(response, "404.html")

    def test_404_does_not_leak_debug_details(self):
        with override_settings(DEBUG=False):
            response = self.client.get("/definitely-not-a-page/")
        html = response.content.decode()
        for leak in ("Traceback", "Request URL", "Django Version", "CSRF", "Exception Value"):
            self.assertNotIn(leak, html)

    def test_404_unknown_table_uses_404_page(self):
        self.login()
        with override_settings(DEBUG=False):
            response = self.client.get(reverse("pos:customer_menu", args=["nope"]))
        self.assertEqual(response.status_code, 404)
        self.assertTemplateUsed(response, "404.html")

    def test_500_branded(self):
        client = self.client
        client.raise_request_exception = False
        with override_settings(DEBUG=False, ROOT_URLCONF="pos.test_urls"):
            response = client.get("/boom/")
        self.assertEqual(response.status_code, 500)
        self.assertTemplateUsed(response, "500.html")
        html = response.content.decode()
        self.assertIn("TableCraft", html)
        self.assertNotIn("secret-detail", html)
        self.assertNotIn("Traceback", html)

    def test_handlers_declared(self):
        import tablecraft.urls as urls

        self.assertEqual(urls.handler404, "django.views.defaults.page_not_found")
        self.assertEqual(urls.handler500, "django.views.defaults.server_error")

    def test_403_anonymous_csrf_failure_shows_blank_panel_known_gap(self):
        """Documents a gap: 403.html fills only the signed-in block.

        An anonymous CSRF failure (e.g. a customer whose page sat open past the
        session) therefore renders no message at all. Step 4 mirrors the 404/500 fix.
        """
        from django.test import Client

        client = Client(enforce_csrf_checks=True)
        response = client.post(
            reverse("pos:api_order_submit", args=[self.table.qr_token]),
            data=json.dumps({"items": [{"item_id": self.item.pk, "quantity": 1}]}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)
        self.assertNotContains(response, "You do not have access", status_code=403)
