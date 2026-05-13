from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from . import views

urlpatterns = [
    # --- Public Pages ---
    path('', views.catalog, name='catalog'),
    path('categories/', views.categories_overview, name='categories_overview'),
    path('artists/', views.artists, name='artists'),
    path('artist/<int:artist_id>/', views.artist_detail, name='artist_detail'),
    path('about/', views.about, name='about'),
    path('popular/', views.popular, name='popular'),
    path('apply-artist/', views.artist_application, name='artist_application'),
    path('profile/', views.profile_view, name='profile'),
    path('cart/', views.view_cart, name='view_cart'),
    path('cart/add/<int:product_id>/', views.add_to_cart, name='add_to_cart'),
    path('cart/remove/<int:item_id>/', views.remove_from_cart, name='remove_from_cart'),
    path('checkout/', views.checkout_view, name='checkout'),
    path('cart/update/<int:item_id>/<str:action>/', views.update_cart_quantity, name='update_cart_quantity'),
    path('place-order/', views.place_order, name='place_order'),
    path('cart/toggle/<int:item_id>/', views.toggle_cart_item, name='toggle_cart_item'),
    path('category/<int:cat_id>/', views.category_detail, name='category_detail'),
    path('search/', views.search_results, name='search_results'),
    path('orders/<int:order_id>/', views.order_detail, name='order_detail'),
    path('likes/', views.liked_items, name='liked_items'),
    path('likes/toggle/<int:product_id>/', views.toggle_like, name='toggle_like'),


    path('product/<int:prod_id>/', views.product_detail, name='product_detail'),
    path('logout/customer/', views.logout_view, name='logout_view'),

    # --- Order ---
    path('order/cancel/<int:order_id>/', views.cancel_order, name='cancel_order'),
    path('order/received/<int:order_id>/', views.confirm_order_received, name='confirm_order_received'),
    path('submit-review/', views.submit_review, name='submit_review'),
    path('review/edit/<int:review_id>/', views.edit_review, name='edit_review'),
    path('review/delete/<int:review_id>/', views.delete_review, name='delete_review'),
   



    # --- Authentication ---
    path('accounts/login/', views.UserLoginView.as_view(), name='login'),
    path('accounts/', include('django.contrib.auth.urls')),
    path('signup/', views.signup, name='signup'),

    
    # Forgot Password Mockup Flow
    path('forgot-password/', views.forgot_password_request, name='forgot_password_request'),
    path('forgot-password/verify/', views.forgot_password_verify, name='forgot_password_verify'),
    path('forgot-password/reset/', views.forgot_password_reset, name='forgot_password_reset'),

    # --- Administrative / Management Hub ---
    path('management/dashboard/', views.admin_dashboard, name='admin_dashboard'),
    path('management/search/', views.admin_search, name='admin_search'),
    path('management/analytics/', views.admin_analytics, name='admin_analytics'),
    path('bk-staff-entry-7721/login/', views.HiddenAdminLoginView.as_view(), name='admin_login'),
    path('bk-staff-entry-7721/logout/', views.admin_logout, name='admin_logout'),
    

    path('ai-chat/', views.bicolikha_ai_chat, name='ai_chat'),
    
    # User Management Sub-routes
    path('management/users/', views.admin_users, name='admin_users'),
    path('management/users/artists/', views.admin_manage_artists, name='manage_artists'),
    path('management/users/accounts/', views.admin_manage_accounts, name='manage_accounts'),
    path('management/users/admins/', views.admin_manage_admins, name='manage_admins'),

    # Product, Orders, Reports
    path('management/products/', views.admin_products, name='admin_products'),
    path('management/orders/', views.admin_orders, name='admin_orders'),
    path('management/messages/', views.admin_messages, name='admin_messages'),
    path('management/notify-artist/<int:order_id>/<int:artist_id>/', views.notify_artist, name='notify_artist'),
    path('management/reports/', views.admin_reports, name='admin_reports'),
]

# This is where your error was happening. 
# It must be OUTSIDE the square brackets of urlpatterns.
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
