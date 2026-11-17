from django import forms

from .models import MenuCategory, MenuItem


class MenuCategoryForm(forms.ModelForm):
    class Meta:
        model = MenuCategory
        fields = ["category_name", "display_order", "is_active"]
        widgets = {
            "category_name": forms.TextInput(
                attrs={"class": "form-control", "maxlength": 50, "placeholder": "e.g., Milk Tea"}
            ),
            "display_order": forms.NumberInput(attrs={"class": "form-control", "min": 0}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }


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
        self.fields["category"].queryset = MenuCategory.objects.filter(is_active=True)
        self.fields["description"].required = False
        self.fields["image_url"].required = False
