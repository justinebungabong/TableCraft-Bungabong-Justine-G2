"""PD3 hardening tests: authentication, staff management, profile, roles.

Runs on in-memory SQLite, never on the real database (see tablecraft.settings).
"""

import shutil
import tempfile
from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.forms import StaffRegistrationForm
from accounts.models import CustomUser

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


def png_bytes(size=(10, 10), color=(20, 40, 60)):
    from PIL import Image

    buffer = BytesIO()
    Image.new("RGB", size, color).save(buffer, format="PNG")
    return buffer.getvalue()


class AuthTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = make_user("owner", role=CustomUser.Role.MANAGER, is_superuser=True)
        cls.cashier = make_user("cashier")

    def test_anonymous_home_redirects_to_login(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith(LOGIN))

    def test_authenticated_home_redirects_to_dashboard(self):
        self.client.login(username="owner", password="Tablecraft#2026")
        response = self.client.get("/")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("dashboard:index"))

    def test_login_page_renders(self):
        self.assertEqual(self.client.get(LOGIN).status_code, 200)

    def test_login_redirects_authenticated_user(self):
        self.client.login(username="owner", password="Tablecraft#2026")
        response = self.client.get(LOGIN)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("dashboard:index"))

    def test_login_wrong_password_shows_error(self):
        response = self.client.post(LOGIN, {"username": "owner", "password": "wrong"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "did not match an active account")

    def test_login_unknown_user_shows_same_error(self):
        response = self.client.post(LOGIN, {"username": "ghost", "password": "wrong"})
        self.assertContains(response, "did not match an active account")

    def test_inactive_user_cannot_log_in(self):
        make_user("gone", is_active=False)
        response = self.client.post(LOGIN, {"username": "gone", "password": "Tablecraft#2026"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "did not match an active account")

    def test_login_honours_next_parameter(self):
        response = self.client.post(f"{LOGIN}?next=/pos/menu/", {"username": "owner", "password": "Tablecraft#2026"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/pos/menu/")

    def test_login_ignores_offsite_next(self):
        response = self.client.post(
            f"{LOGIN}?next=https://evil.example.com/", {"username": "owner", "password": "Tablecraft#2026"}
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("dashboard:index"))

    def test_logout_requires_post(self):
        self.client.login(username="owner", password="Tablecraft#2026")
        self.assertEqual(self.client.get(reverse("accounts:logout")).status_code, 405)

    def test_logout_post_redirects_to_login(self):
        self.client.login(username="owner", password="Tablecraft#2026")
        response = self.client.post(reverse("accounts:logout"))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, LOGIN)
        self.assertEqual(self.client.get(reverse("dashboard:index")).status_code, 302)

    def test_dashboard_requires_login(self):
        self.assertEqual(self.client.get(reverse("dashboard:index")).status_code, 302)

    def test_password_change_route_absent_known_gap(self):
        """Documents current behaviour: no self-service password change/reset URL exists."""
        self.client.login(username="owner", password="Tablecraft#2026")
        for path in ("/accounts/password-change/", "/accounts/password_change/", "/accounts/password-reset/"):
            self.assertEqual(self.client.get(path).status_code, 404, path)


class RoleTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = make_user("owner", role=CustomUser.Role.MANAGER, is_superuser=True)
        cls.manager = make_user("manager", role=CustomUser.Role.MANAGER)
        cls.cashier = make_user("cashier", role=CustomUser.Role.CASHIER)
        cls.kitchen = make_user("kitchen", role=CustomUser.Role.KITCHEN)

    def test_role_properties(self):
        self.assertTrue(self.manager.is_manager)
        self.assertFalse(self.cashier.is_manager)
        self.assertTrue(self.manager.can_access_cashier)
        self.assertTrue(self.manager.can_access_kitchen)
        self.assertTrue(self.cashier.can_access_cashier)
        self.assertFalse(self.cashier.can_access_kitchen)
        self.assertTrue(self.kitchen.can_access_kitchen)
        self.assertFalse(self.kitchen.can_access_cashier)

    def test_display_role_for_owner(self):
        self.assertEqual(self.owner.display_role, "Owner")
        self.assertEqual(self.manager.display_role, "Manager")

    def test_owner_counts_as_superuser_not_role(self):
        self.assertTrue(self.owner.is_superuser)
        self.assertEqual(self.owner.role, CustomUser.Role.MANAGER)

    def test_dashboard_roster_owner_and_manager_only(self):
        for username, visible in (("owner", True), ("manager", True), ("cashier", False), ("kitchen", False)):
            self.client.login(username=username, password="Tablecraft#2026")
            response = self.client.get(reverse("dashboard:index"))
            self.assertEqual(response.status_code, 200)
            self.assertEqual("Staff member" in response.content.decode(), visible, username)

    def test_owner_sees_add_staff_button(self):
        self.client.login(username="owner", password="Tablecraft#2026")
        self.assertContains(self.client.get(reverse("dashboard:index")), "Add staff member")
        self.client.login(username="manager", password="Tablecraft#2026")
        self.assertNotContains(self.client.get(reverse("dashboard:index")), "Add staff member")

    def test_dashboard_counts_include_inactive_known_gap(self):
        """Documents current behaviour: the shift summary counts deactivated accounts (step 4 filters)."""
        make_user("gone", is_active=False)
        self.client.login(username="owner", password="Tablecraft#2026")
        response = self.client.get(reverse("dashboard:index"))
        self.assertEqual(response.context["total_staff"], 5)
        self.assertEqual(response.context["cashier_count"], 2)


class SignupTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = make_user("owner", role=CustomUser.Role.MANAGER, is_superuser=True)
        cls.manager = make_user("manager", role=CustomUser.Role.MANAGER)
        cls.cashier = make_user("cashier", role=CustomUser.Role.CASHIER)

    def payload(self, **over):
        data = {
            "username": "newstaff", "first_name": "New", "last_name": "Staff",
            "email": "newstaff@example.com", "role": CustomUser.Role.CASHIER,
            "contact_number": "09171234567",
            "password1": "Tablecraft#2026", "password2": "Tablecraft#2026",
        }
        data.update(over)
        return data

    def test_anonymous_redirected(self):
        response = self.client.get(reverse("accounts:signup"))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith(LOGIN))

    def test_manager_denied(self):
        self.client.login(username="manager", password="Tablecraft#2026")
        response = self.client.get(reverse("accounts:signup"))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("dashboard:index"))

    def test_manager_cannot_post_create(self):
        self.client.login(username="manager", password="Tablecraft#2026")
        self.client.post(reverse("accounts:signup"), self.payload())
        self.assertFalse(CustomUser.objects.filter(username="newstaff").exists())

    def test_cashier_denied(self):
        self.client.login(username="cashier", password="Tablecraft#2026")
        self.client.post(reverse("accounts:signup"), self.payload())
        self.assertFalse(CustomUser.objects.filter(username="newstaff").exists())

    def test_owner_creates_staff(self):
        self.client.login(username="owner", password="Tablecraft#2026")
        response = self.client.post(reverse("accounts:signup"), self.payload(), follow=True)
        self.assertEqual(response.status_code, 200)
        user = CustomUser.objects.get(username="newstaff")
        self.assertEqual(user.role, CustomUser.Role.CASHIER)
        self.assertTrue(user.is_active)
        self.assertTrue(user.check_password("Tablecraft#2026"))
        self.assertContains(response, "Staff account created")

    def test_owner_can_create_manager(self):
        self.client.login(username="owner", password="Tablecraft#2026")
        self.client.post(reverse("accounts:signup"), self.payload(role=CustomUser.Role.MANAGER))
        self.assertEqual(CustomUser.objects.get(username="newstaff").role, CustomUser.Role.MANAGER)

    def test_manager_role_not_offered_to_non_owner_form(self):
        form = StaffRegistrationForm(user=self.manager)
        values = [value for value, _ in form.fields["role"].choices]
        self.assertNotIn(CustomUser.Role.MANAGER, values)

    def test_duplicate_username_rejected(self):
        self.client.login(username="owner", password="Tablecraft#2026")
        response = self.client.post(reverse("accounts:signup"), self.payload(username="cashier"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "already exists")

    def test_duplicate_email_rejected(self):
        self.client.login(username="owner", password="Tablecraft#2026")
        response = self.client.post(reverse("accounts:signup"), self.payload(email="cashier@example.com"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "already exists")

    def test_weak_password_rejected(self):
        self.client.login(username="owner", password="Tablecraft#2026")
        response = self.client.post(
            reverse("accounts:signup"), self.payload(password1="123", password2="123")
        )
        self.assertContains(response, "too short")
        self.assertFalse(CustomUser.objects.filter(username="newstaff").exists())

    def test_password_mismatch_rejected(self):
        self.client.login(username="owner", password="Tablecraft#2026")
        response = self.client.post(
            reverse("accounts:signup"), self.payload(password2="Different#2026")
        )
        self.assertContains(response, "didn’t match")
        self.assertFalse(CustomUser.objects.filter(username="newstaff").exists())

    def test_invalid_role_rejected(self):
        self.client.login(username="owner", password="Tablecraft#2026")
        response = self.client.post(reverse("accounts:signup"), self.payload(role="OWNER"))
        self.assertContains(response, "Select a valid choice")
        self.assertFalse(CustomUser.objects.filter(username="newstaff").exists())

    def test_blank_required_fields_rejected(self):
        self.client.login(username="owner", password="Tablecraft#2026")
        for field in ("username", "first_name", "last_name", "email"):
            response = self.client.post(reverse("accounts:signup"), self.payload(**{field: ""}))
            self.assertEqual(response.status_code, 200)
            self.assertFalse(CustomUser.objects.filter(username="newstaff").exists(), field)

    def test_contact_number_is_optional(self):
        self.client.login(username="owner", password="Tablecraft#2026")
        self.client.post(reverse("accounts:signup"), self.payload(contact_number=""))
        self.assertTrue(CustomUser.objects.filter(username="newstaff").exists())

    def test_contact_number_format_unvalidated_known_gap(self):
        """Documents current behaviour: contact_number accepts arbitrary text (step 4 adds a regex)."""
        self.client.login(username="owner", password="Tablecraft#2026")
        self.client.post(reverse("accounts:signup"), self.payload(contact_number="call me maybe"))
        self.assertTrue(CustomUser.objects.filter(username="newstaff", contact_number="call me maybe").exists())

    def test_contact_number_max_length(self):
        self.client.login(username="owner", password="Tablecraft#2026")
        response = self.client.post(reverse("accounts:signup"), self.payload(contact_number="0" * 40))
        self.assertContains(response, "at most 20 characters")


class StaffManageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = make_user("owner", role=CustomUser.Role.MANAGER, is_superuser=True)
        cls.manager = make_user("manager", role=CustomUser.Role.MANAGER)
        cls.cashier = make_user("cashier", role=CustomUser.Role.CASHIER)

    def login(self, username="owner"):
        self.assertTrue(self.client.login(username=username, password="Tablecraft#2026"))

    def edit_payload(self, member, **over):
        data = {
            "first_name": member.first_name or "Name", "last_name": member.last_name or "Last",
            "email": member.email, "role": member.role,
            "contact_number": member.contact_number or "",
        }
        if member.is_active:
            data["is_active"] = "on"
        data.update(over)
        return data

    def deactivate_payload(self, member):
        data = self.edit_payload(member)
        data.pop("is_active", None)
        return data

    # --- edit ---------------------------------------------------------------
    def test_anonymous_redirected(self):
        response = self.client.get(reverse("accounts:staff_edit", args=[self.cashier.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith(LOGIN))

    def test_manager_cannot_edit(self):
        self.login("manager")
        self.assertEqual(self.client.get(reverse("accounts:staff_edit", args=[self.cashier.pk])).status_code, 302)
        self.client.post(reverse("accounts:staff_edit", args=[self.cashier.pk]),
                         self.edit_payload(self.cashier, role=CustomUser.Role.MANAGER))
        self.cashier.refresh_from_db()
        self.assertEqual(self.cashier.role, CustomUser.Role.CASHIER)

    def test_owner_edits_role(self):
        self.login()
        self.client.post(reverse("accounts:staff_edit", args=[self.cashier.pk]),
                         self.edit_payload(self.cashier, role=CustomUser.Role.KITCHEN))
        self.cashier.refresh_from_db()
        self.assertEqual(self.cashier.role, CustomUser.Role.KITCHEN)

    def test_edit_unknown_member_404(self):
        self.login()
        self.assertEqual(self.client.get(reverse("accounts:staff_edit", args=[999999])).status_code, 404)

    def test_invalid_role_rejected_on_edit(self):
        self.login()
        response = self.client.post(reverse("accounts:staff_edit", args=[self.cashier.pk]),
                                    self.edit_payload(self.cashier, role="OWNER"))
        self.assertContains(response, "Select a valid choice")
        self.cashier.refresh_from_db()
        self.assertEqual(self.cashier.role, CustomUser.Role.CASHIER)

    def test_owner_cannot_deactivate_self_via_edit(self):
        self.login()
        response = self.client.post(reverse("accounts:staff_edit", args=[self.owner.pk]),
                                    self.deactivate_payload(self.owner), follow=True)
        self.assertContains(response, "cannot deactivate your own")
        self.owner.refresh_from_db()
        self.assertTrue(self.owner.is_active)

    def test_owner_can_deactivate_other_via_edit(self):
        self.login()
        self.client.post(reverse("accounts:staff_edit", args=[self.cashier.pk]),
                         self.deactivate_payload(self.cashier))
        self.cashier.refresh_from_db()
        self.assertFalse(self.cashier.is_active)

    # --- toggle -------------------------------------------------------------
    def test_toggle_requires_post(self):
        self.login()
        self.assertEqual(self.client.get(reverse("accounts:staff_toggle_active", args=[self.cashier.pk])).status_code, 302)
        self.cashier.refresh_from_db()
        self.assertTrue(self.cashier.is_active)

    def test_toggle_by_manager_does_nothing(self):
        self.login("manager")
        self.client.post(reverse("accounts:staff_toggle_active", args=[self.cashier.pk]))
        self.cashier.refresh_from_db()
        self.assertTrue(self.cashier.is_active)

    def test_toggle_self_blocked(self):
        self.login()
        response = self.client.post(reverse("accounts:staff_toggle_active", args=[self.owner.pk]), follow=True)
        self.assertContains(response, "cannot deactivate your own")
        self.owner.refresh_from_db()
        self.assertTrue(self.owner.is_active)

    def test_toggle_other_twice(self):
        self.login()
        url = reverse("accounts:staff_toggle_active", args=[self.cashier.pk])
        self.client.post(url)
        self.cashier.refresh_from_db()
        self.assertFalse(self.cashier.is_active)
        self.client.post(url)
        self.cashier.refresh_from_db()
        self.assertTrue(self.cashier.is_active)

    def test_toggle_unknown_member_404(self):
        self.login()
        self.assertEqual(self.client.post(reverse("accounts:staff_toggle_active", args=[999999])).status_code, 404)

    def test_deactivated_user_session_ends(self):
        self.login("cashier")
        self.assertEqual(self.client.get(reverse("dashboard:index")).status_code, 200)
        self.cashier.is_active = False
        self.cashier.save(update_fields=["is_active"])
        self.assertEqual(self.client.get(reverse("dashboard:index")).status_code, 302)


class ProfileTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = make_user("owner", role=CustomUser.Role.MANAGER, is_superuser=True)
        cls.cashier = make_user("cashier")

    def setUp(self):
        self.media_root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.media_root, True)
        self.override = override_settings(MEDIA_ROOT=self.media_root)
        self.override.enable()
        self.addCleanup(self.override.disable)

    def login(self, username="owner"):
        self.assertTrue(self.client.login(username=username, password="Tablecraft#2026"))

    def test_anonymous_redirected(self):
        response = self.client.get(reverse("accounts:profile"))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith(LOGIN))

    def test_any_role_can_open_own_profile(self):
        self.login("cashier")
        self.assertEqual(self.client.get(reverse("accounts:profile")).status_code, 200)

    def test_update_profile_fields(self):
        self.login("cashier")
        self.client.post(reverse("accounts:profile"), {
            "first_name": "Cash", "last_name": "Ier",
            "email": "cashier@example.com", "contact_number": "09998887777",
        })
        self.cashier.refresh_from_db()
        self.assertEqual(self.cashier.first_name, "Cash")
        self.assertEqual(self.cashier.contact_number, "09998887777")

    def test_profile_cannot_change_role(self):
        self.login("cashier")
        self.client.post(reverse("accounts:profile"), {
            "first_name": "Cash", "last_name": "Ier", "email": "cashier@example.com",
            "contact_number": "", "role": CustomUser.Role.MANAGER, "is_superuser": "on",
        })
        self.cashier.refresh_from_db()
        self.assertEqual(self.cashier.role, CustomUser.Role.CASHIER)
        self.assertFalse(self.cashier.is_superuser)

    def test_duplicate_email_rejected(self):
        self.login("cashier")
        response = self.client.post(reverse("accounts:profile"), {
            "first_name": "Cash", "last_name": "Ier",
            "email": "owner@example.com", "contact_number": "",
        })
        self.assertEqual(response.status_code, 200)
        self.cashier.refresh_from_db()
        self.assertEqual(self.cashier.email, "cashier@example.com")

    def test_valid_photo_upload(self):
        self.login("cashier")
        upload = SimpleUploadedFile("me.png", png_bytes(), content_type="image/png")
        response = self.client.post(reverse("accounts:profile"), {
            "first_name": "Cash", "last_name": "Ier", "email": "cashier@example.com",
            "contact_number": "", "profile_photo": upload,
        }, follow=True)
        self.assertContains(response, "Staff profile updated")
        self.cashier.refresh_from_db()
        self.assertTrue(self.cashier.profile_photo)
        self.assertTrue(self.cashier.has_profile_photo)
        self.assertContains(response, self.cashier.profile_photo.url)

    def test_fake_image_rejected(self):
        self.login("cashier")
        upload = SimpleUploadedFile("fake.png", b"not an image", content_type="image/png")
        response = self.client.post(reverse("accounts:profile"), {
            "first_name": "Cash", "last_name": "Ier", "email": "cashier@example.com",
            "contact_number": "", "profile_photo": upload,
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Upload a valid image")
        self.cashier.refresh_from_db()
        self.assertFalse(self.cashier.profile_photo)

    def test_photo_size_cap_absent_known_gap(self):
        """Documents ISS-01 follow-up: no upload size/dimension limit (step 4 adds 2 MB cap)."""
        self.login("cashier")
        upload = SimpleUploadedFile("big.png", png_bytes(size=(600, 600)), content_type="image/png")
        self.client.post(reverse("accounts:profile"), {
            "first_name": "Cash", "last_name": "Ier", "email": "cashier@example.com",
            "contact_number": "", "profile_photo": upload,
        })
        self.cashier.refresh_from_db()
        self.assertTrue(self.cashier.profile_photo)

    def test_has_profile_photo_false_when_file_missing(self):
        self.cashier.profile_photo = "profiles/does-not-exist.png"
        self.cashier.save(update_fields=["profile_photo"])
        self.assertFalse(self.cashier.has_profile_photo)

    def test_has_profile_photo_false_when_unset(self):
        self.assertFalse(self.cashier.has_profile_photo)

    def test_avatar_falls_back_without_photo(self):
        self.login("cashier")
        response = self.client.get(reverse("accounts:profile"))
        self.assertContains(response, "avatar")
