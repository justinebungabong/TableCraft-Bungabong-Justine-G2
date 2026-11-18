from django.urls import path

from . import menu_views, views

app_name = "pos"

urlpatterns = [
    path("menu/", menu_views.manage_menu_view, name="manage_menu"),
    path("menu/item/<int:pk>/edit/", menu_views.menu_item_edit_view, name="menu_item_edit"),
    path("table/<str:qr_token>/", views.customer_menu_view, name="customer_menu"),
    path("api/table/<str:qr_token>/availability/", views.api_menu_availability, name="api_menu_availability"),
    path("api/table/<str:qr_token>/submit/", views.api_order_submit, name="api_order_submit"),
    path("order/<str:public_token>/", views.customer_order_view, name="customer_order"),
    path("api/order/<str:public_token>/status/", views.api_order_status, name="api_order_status"),
    path("tables/", views.manage_tables_view, name="manage_tables"),
]
