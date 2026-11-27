from urllib.parse import urlsplit

from django import forms
from django.core.exceptions import ValidationError
from django.db.models import Q

from .models import MenuCategory, MenuItem

# Explicit bounds so the rule no longer depends on the database backend
# (SQLite has no small-integer range; PostgreSQL rejects values above 32767).
DISPLAY_ORDER_MIN = 0
DISPLAY_ORDER_MAX = 999

IMAGE_URL_SCHEMES = ("http", "https")


class MenuCategoryForm(forms.ModelForm):
    class Meta:
        model = MenuCategory
        fields = ["category_name", "display_order", "is_active"]
        widgets = {
            "category_name": forms.TextInput(
                attrs={"class": "form-control", "maxlength": 50, "placeholder": "e.g., Milk Tea"}
            ),
            "display_order": forms.NumberInput(
                attrs={
                    "class": "form-control",
                    "min": DISPLAY_ORDER_MIN,
                    "max": DISPLAY_ORDER_MAX,
                }
            ),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        order = self.fields["display_order"]
        order.min_value = DISPLAY_ORDER_MIN
        order.max_value = DISPLAY_ORDER_MAX
        order.label = "Sort order"
        order.help_text = (
            f"Lower numbers appear first on the menu ({DISPLAY_ORDER_MIN}-{DISPLAY_ORDER_MAX})."
        )

    def clean_display_order(self):
        """Enforce 0-999 in Python, not via the database backend's integer range."""
        value = self.cleaned_data["display_order"]
        if value is None:
            return value
        if not DISPLAY_ORDER_MIN <= value <= DISPLAY_ORDER_MAX:
            raise ValidationError(
                f"Sort order must be between {DISPLAY_ORDER_MIN} and {DISPLAY_ORDER_MAX}."
            )
        return value

    def clean_category_name(self):
        """Reject 'main' when 'Main' already exists (the DB unique index is case-sensitive)."""
        name = self.cleaned_data["category_name"]
        duplicates = MenuCategory.objects.filter(category_name__iexact=name)
        if self.instance.pk:
            duplicates = duplicates.exclude(pk=self.instance.pk)
        if duplicates.exists():
            raise ValidationError("A category with this name already exists.")
        return name


class MenuItemForm(forms.ModelForm):
    class Meta:
        model = MenuItem
        fields = [
            "category",
            "item_name",
            "description",
            "price",
            "image_url",
            "is_available",
            "is_active",
        ]
        widgets = {
            "category": forms.Select(attrs={"class": "form-select"}),
            "item_name": forms.TextInput(
                attrs={"class": "form-control", "maxlength": 100, "placeholder": "e.g., Wintermelon"}
            ),
            "description": forms.TextInput(
                attrs={"class": "form-control", "maxlength": 255, "placeholder": "Optional description"}
            ),
            "price": forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "0.01"}),
            "image_url": forms.URLInput(
                attrs={"class": "form-control", "placeholder": "https://... (optional)"}
            ),
            "is_available": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Archived categories are not selectable, except the one this item already
        # belongs to: otherwise archiving a category makes its items uneditable.
        categories = MenuCategory.objects.filter(is_active=True)
        if self.instance.pk and self.instance.category_id:
            categories = MenuCategory.objects.filter(
                Q(is_active=True) | Q(pk=self.instance.category_id)
            )
        self.fields["category"].queryset = categories.order_by("display_order", "category_name")
        self.fields["description"].required = False
        self.fields["image_url"].required = False
        self.fields["image_url"].help_text = (
            "Optional http(s) link. Stored for reference; it is not shown on the customer menu yet."
        )

    def clean_image_url(self):
        url = (self.cleaned_data.get("image_url") or "").strip()
        if not url:
            return url
        if urlsplit(url).scheme.lower() not in IMAGE_URL_SCHEMES:
            raise ValidationError("Image links must start with http:// or https://.")
        return url

    def clean(self):
        cleaned = super().clean()
        name = cleaned.get("item_name")
        category = cleaned.get("category")
        if name and category:
            duplicates = MenuItem.objects.filter(category=category, item_name__iexact=name)
            if self.instance.pk:
                duplicates = duplicates.exclude(pk=self.instance.pk)
            if duplicates.exists():
                self.add_error(
                    "item_name",
                    "This item already exists in the selected category.",
                )
        return cleaned
