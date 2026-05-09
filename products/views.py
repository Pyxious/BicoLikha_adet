from django.shortcuts import render, redirect, get_object_or_404
import base64
import re

from django.contrib.auth import get_user_model
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.decorators import user_passes_test, login_required
from django.db import transaction
from django.db.models import Q, Sum, Count, F, Case, When, Value, IntegerField, Min
from django.db.models.functions import TruncDate
from django.http import JsonResponse
from django.core.paginator import Paginator
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.mail import send_mail
from django.conf import settings
from django.utils import timezone
from django.utils.text import slugify
from django.urls import reverse_lazy
from django.contrib.auth.views import LoginView
from django.contrib import messages
from datetime import timedelta
import calendar
from datetime import datetime
from django.utils import timezone
from django.db.models import Count

# Models
from .models import (
    Artwork, Artist, Category, Address, 
    Order, Cart, CartItem, OrderDetail, Payment, Like, Review, Notification, Shipment, SupplyInventory,
    ArtistApplication, ArtistApplicationProduct, ArtistStockAdjustmentRequest, PopularAd, AuditLog
)

# Forms
from .forms import (
    ProductForm, CategoryForm, BicolikhaSignupForm,
    CustomerAuthenticationForm, AdminAuthenticationForm, PopularAdForm
)

User = get_user_model()


def _address_is_complete(address):
    if not address:
        return False
    required_fields = [address.street, address.brgy, address.municipality, address.zipcode, address.phone_num]
    return all((value or '').strip() for value in required_fields)


def _get_user_addresses(user):
    return Address.objects.filter(user=user).order_by('-is_default', '-address_id')


def _get_primary_address(user):
    addresses = _get_user_addresses(user)
    primary = addresses.filter(is_default=True).first() or addresses.first()
    return primary if _address_is_complete(primary) else None


def _create_or_update_address_from_post(request, user, instance=None):
    street = (request.POST.get('st_name') or '').strip()
    brgy = (request.POST.get('brgy') or '').strip()
    municipality = (request.POST.get('municipality') or '').strip()
    zipcode = (request.POST.get('zipcode') or '').strip()
    phone = (request.POST.get('phone') or '').strip()

    if not all([street, brgy, municipality, zipcode, phone]):
        raise ValueError("Please complete all address fields before saving.")

    address = instance or Address(user=user)
    address.street = street
    address.brgy = brgy
    address.municipality = municipality
    address.zipcode = zipcode
    address.phone_num = phone
    address.latitude = request.POST.get('lat') or None
    address.longitude = request.POST.get('lng') or None

    if instance is None:
        has_complete_address = any(_address_is_complete(existing) for existing in _get_user_addresses(user))
        address.is_default = not has_complete_address

    address.save()
    return address


def _get_artist_application_status(user):
    return ArtistApplication.objects.filter(user=user).order_by('-date_submitted').first()


def _get_client_ip(request):
    forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if forwarded_for:
        return forwarded_for.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')


def _log_audit(request, action):
    if not request.user.is_authenticated:
        return

    AuditLog.objects.create(
        user=request.user,
        action=action,
        ip_address=_get_client_ip(request)
    )


def _send_mock_artist_email(artist, subject, body):
    artist_email = artist.artist_email if artist and artist.artist_email else ''
    if not artist_email:
        return False

    send_mail(
        subject,
        body,
        getattr(settings, 'DEFAULT_FROM_EMAIL', 'no-reply@bicolikha.local'),
        [artist_email],
        fail_silently=True,
    )
    return True


def _get_application_applicant_name(application):
    if application.applicant_name:
        return application.applicant_name
    if application.user:
        return application.user.get_full_name() or application.user.username
    return 'Guest applicant'


def _get_application_applicant_email(application):
    if application.applicant_email:
        return application.applicant_email
    if application.user:
        return application.user.email
    return ''


def _send_application_email(application, subject, body):
    applicant_email = _get_application_applicant_email(application)
    if not applicant_email:
        return False

    send_mail(
        subject,
        body,
        getattr(settings, 'DEFAULT_FROM_EMAIL', 'no-reply@bicolikha.local'),
        [applicant_email],
        fail_silently=True,
    )
    return True


def _get_application_category(selected_category_id, requested_category_name):
    requested_category_name = (requested_category_name or '').strip()

    if requested_category_name:
        category, _ = Category.objects.get_or_create(
            category_name='Other',
            defaults={'category_desc': 'Requested by artists for review.'}
        )
        return category, requested_category_name

    if not selected_category_id:
        raise ValueError("Please choose a category or enter a new category request.")

    return get_object_or_404(Category, category_id=selected_category_id), ''


def _save_artist_application_image(owner_key, uploaded_file, product_name):
    if not uploaded_file:
        return ''

    safe_name = slugify(product_name or uploaded_file.name.rsplit('.', 1)[0]) or 'artwork'
    owner_slug = slugify(str(owner_key or 'guest')) or 'guest'
    path = default_storage.save(
        f'artist_application_submissions/{owner_slug}/{timezone.now().strftime("%Y%m%d%H%M%S%f")}_{safe_name}_{uploaded_file.name}',
        uploaded_file
    )
    return path


def _save_artist_application_image_data(owner_key, image_data, filename, product_name):
    image_data = (image_data or '').strip()
    if not image_data:
        return ''

    try:
        header, encoded = image_data.split(',', 1)
    except ValueError:
        return ''

    extension = 'png'
    if ';base64' in header and '/' in header:
        mime_type = header.split(';', 1)[0]
        extension = mime_type.rsplit('/', 1)[-1] or extension

    original_name = filename or f'{slugify(product_name) or "artwork"}.{extension}'
    safe_name = slugify(product_name or original_name.rsplit('.', 1)[0]) or 'artwork'
    stored_name = f'{timezone.now().strftime("%Y%m%d%H%M%S%f")}_{safe_name}_{original_name}'
    owner_slug = slugify(str(owner_key or 'guest')) or 'guest'

    try:
        decoded = base64.b64decode(encoded)
    except (ValueError, TypeError):
        return ''

    path = default_storage.save(
        f'artist_application_submissions/{owner_slug}/{stored_name}',
        ContentFile(decoded, name=stored_name)
    )
    return path


def _save_artist_profile_image(owner_key, uploaded_file, artist_name):
    if not uploaded_file:
        return ''

    safe_name = slugify(artist_name or uploaded_file.name.rsplit('.', 1)[0]) or 'artist'
    owner_slug = slugify(str(owner_key or 'guest')) or 'guest'
    path = default_storage.save(
        f'artist_profiles/{owner_slug}/{timezone.now().strftime("%Y%m%d%H%M%S%f")}_{safe_name}_{uploaded_file.name}',
        uploaded_file
    )
    return path


def _parse_application_product_details(application_product):
    description = application_product.product_description or ''
    requested_category = ''
    marker = 'Requested category:'
    if marker in description:
        before, after = description.rsplit(marker, 1)
        description = before.strip()
        requested_category = after.strip()

    application_product.clean_description = description
    application_product.requested_category = requested_category
    return application_product


def _create_artist_application_from_post(request, artist_name):
    product_keys = [key for key in request.POST.getlist('product_key') if key.strip()]
    applicant_user = request.user if request.user.is_authenticated else None
    applicant_name = (request.POST.get('applicant_name') or '').strip()
    applicant_email = (request.POST.get('applicant_email') or '').strip().lower()
    applicant_phone = re.sub(r'\D', '', request.POST.get('applicant_phone') or '')
    artist_description = (request.POST.get('artist_description') or '').strip()
    artist_municipality = (request.POST.get('artist_municipality') or '').strip()
    artist_brgy = (request.POST.get('artist_brgy') or '').strip()
    artist_zipcode = (request.POST.get('artist_zipcode') or '').strip()
    storage_owner = applicant_user.pk if applicant_user else applicant_email

    if not artist_name:
        raise ValueError("Please enter the artist name you want reviewed.")
    if not artist_description:
        raise ValueError("Please enter an artist description.")
    if not artist_municipality:
        raise ValueError("Please enter the artist municipality.")
    if not artist_brgy:
        raise ValueError("Please enter the artist barangay.")
    if not artist_zipcode:
        raise ValueError("Please enter the artist ZIP code.")

    if not applicant_user:
        if not applicant_name:
            raise ValueError("Please enter your full name.")
        if not applicant_email:
            raise ValueError("Please enter your email address.")
        if not applicant_phone:
            raise ValueError("Please enter your phone number.")
    else:
        applicant_name = applicant_name or applicant_user.get_full_name() or applicant_user.username
        applicant_email = applicant_email or applicant_user.email
        applicant_phone = applicant_phone or getattr(applicant_user, 'phone_number', '') or ''

    if not product_keys:
        raise ValueError("Please add at least one product to your application.")

    application = ArtistApplication.objects.create(
        user=applicant_user,
        applicant_name=applicant_name,
        applicant_email=applicant_email,
        applicant_phone=applicant_phone,
        artist_name=artist_name,
        artist_description=artist_description,
        artist_municipality=artist_municipality,
        artist_brgy=artist_brgy,
        artist_zipcode=artist_zipcode,
        artist_image=_save_artist_profile_image(
            applicant_user.pk if applicant_user else applicant_email,
            request.FILES.get('artist_image'),
            artist_name
        ),
        application_status='Pending'
    )

    created_products = 0
    for key in product_keys:
        product_name = (request.POST.get(f'prod_name_{key}') or '').strip()
        product_description = (request.POST.get(f'prod_description_{key}') or '').strip()
        product_price = (request.POST.get(f'prod_price_{key}') or '').strip()
        product_stock_qty = (request.POST.get(f'prod_stock_qty_{key}') or '').strip()
        selected_category_id = (request.POST.get(f'category_id_{key}') or '').strip()
        requested_category_name = (request.POST.get(f'new_category_{key}') or '').strip()
        product_image_data = request.POST.get(f'prod_image_data_{key}') or ''
        product_image_filename = (request.POST.get(f'prod_image_filename_{key}') or '').strip()

        if not any([product_name, product_description, product_price, product_stock_qty, selected_category_id, requested_category_name]):
            continue

        if not product_name:
            raise ValueError("Each product entry needs a product name.")
        if not product_price:
            raise ValueError(f"Please add a price for {product_name}.")
        if not product_stock_qty:
            raise ValueError(f"Please add the starting stock for {product_name}.")

        try:
            stock_value = int(product_stock_qty)
        except (TypeError, ValueError):
            raise ValueError(f"Stock quantity for {product_name} must be a whole number.")

        if stock_value < 0:
            raise ValueError(f"Stock quantity for {product_name} cannot be negative.")

        category, category_request_note = _get_application_category(selected_category_id, requested_category_name)
        full_description = product_description
        if category_request_note:
            full_description = (
                f"{product_description}\n\nRequested category: {category_request_note}".strip()
            )

        ArtistApplicationProduct.objects.create(
            application=application,
            category=category,
            product_name=product_name,
            product_description=full_description,
            product_price=product_price,
            product_stock_qty=stock_value,
            product_image=(
                _save_artist_application_image(
                    storage_owner,
                    request.FILES.get(f'prod_image_{key}'),
                    product_name
                ) or _save_artist_application_image_data(
                    storage_owner,
                    product_image_data,
                    product_image_filename,
                    product_name
                )
            )
        )
        created_products += 1

    if created_products == 0:
        raise ValueError("Please complete at least one product before submitting your application.")

    return application


def _approve_artist_application(application):
    if application.application_status == 'Approved':
        return

    with transaction.atomic():
        applicant_address = None
        if application.user:
            applicant_address = Address.objects.filter(user=application.user, is_default=True).first() or Address.objects.filter(user=application.user).first()

        artist = Artist.objects.create(
            artist_name=application.artist_name,
            artist_email=_get_application_applicant_email(application),
            artist_phone_num=(application.applicant_phone or (applicant_address.phone_num if applicant_address else '') or ''),
            artist_municipality=application.artist_municipality or (applicant_address.municipality if applicant_address else '') or '',
            artist_brgy=application.artist_brgy or (applicant_address.brgy if applicant_address else '') or '',
            artist_zipcode=application.artist_zipcode or (applicant_address.zipcode if applicant_address else '') or '',
            artist_description=application.artist_description or 'Verified Artist',
            artist_image=application.artist_image or None,
        )

        for application_product in application.products.select_related('category').all():
            _parse_application_product_details(application_product)
            category = application_product.category

            if application_product.requested_category:
                category, _ = Category.objects.get_or_create(
                    category_name=application_product.requested_category,
                    defaults={'category_desc': 'Submitted by artist application and approved by admin.'}
                )

            product = Artwork.objects.create(
                artist=artist,
                category=category,
                title=application_product.product_name,
                description=application_product.clean_description,
                price=application_product.product_price,
                stock_qty=application_product.product_stock_qty,
                image=application_product.product_image or None
            )

            if product.stock_qty and product.stock_qty > 0:
                SupplyInventory.objects.create(
                    product=product,
                    supplied_qty=product.stock_qty
                )

        application.application_status = 'Approved'
        application.date_reviewed = timezone.now()
        application.save(update_fields=['application_status', 'date_reviewed'])


def _decorate_artist_applications(applications):
    for application in applications:
        existing_category_products = []
        requested_category_products = []
        for product in application.products.all():
            product = _parse_application_product_details(product)
            product.preview_image_url = f"{settings.MEDIA_URL}{product.product_image}" if product.product_image else ''
            if product.requested_category:
                requested_category_products.append(product)
            else:
                existing_category_products.append(product)

        application.existing_category_products = existing_category_products
        application.requested_category_products = requested_category_products
    return applications


def _deduct_latest_supply_inventory(product, quantity):
    remaining = quantity
    supplies = SupplyInventory.objects.filter(product=product).order_by('-supplied_date', '-supply_id')

    for supply in supplies:
        if remaining <= 0:
            break

        available = supply.supplied_qty or 0
        if available <= 0:
            continue

        deduction = min(available, remaining)
        supply.supplied_qty = available - deduction
        supply.save(update_fields=['supplied_qty'])
        remaining -= deduction

    return remaining == 0


def _approve_stock_adjustment_request(stock_request):
    if stock_request.status == 'Approved':
        return

    product = stock_request.product
    current_stock = product.stock_qty or 0

    with transaction.atomic():
        if stock_request.adjustment_type == 'Add':
            product.stock_qty = current_stock + stock_request.quantity
            product.save(update_fields=['stock_qty'])
            SupplyInventory.objects.create(product=product, supplied_qty=stock_request.quantity)
        else:
            if stock_request.quantity > current_stock:
                raise ValueError(f"Cannot subtract more than the current stock for {product.title}.")
            product.stock_qty = current_stock - stock_request.quantity
            product.save(update_fields=['stock_qty'])
            _deduct_latest_supply_inventory(product, stock_request.quantity)

        stock_request.status = 'Approved'
        stock_request.date_reviewed = timezone.now()
        stock_request.save(update_fields=['status', 'date_reviewed'])


def _reject_stock_adjustment_request(stock_request):
    if stock_request.status == 'Approved':
        raise ValueError("Approved stock requests can no longer be rejected.")

    if stock_request.status != 'Rejected':
        stock_request.status = 'Rejected'
        stock_request.date_reviewed = timezone.now()
        stock_request.save(update_fields=['status', 'date_reviewed'])

# --- 1. AUTHENTICATION & PORTAL SECURITY ---

class UserLoginView(LoginView):
    """PORTAL 1: CUSTOMER LOGIN - Strictly rejects staff via CustomerAuthenticationForm."""
    template_name = 'registration/login.html'
    authentication_form = CustomerAuthenticationForm

    def form_valid(self, form):
        if form.get_user().is_staff:
            form.add_error(None, "We couldn't sign you in with that email or phone number and password.")
            return self.form_invalid(form)
        return super().form_valid(form)

    def get_success_url(self):
        return reverse_lazy('catalog')

class HiddenAdminLoginView(LoginView):
    """PORTAL 2: SECRET ADMIN LOGIN - Strictly rejects customers via AdminAuthenticationForm."""
    template_name = 'admin/admin_login.html'
    authentication_form = AdminAuthenticationForm

    def form_valid(self, form):
        response = super().form_valid(form)
        _log_audit(self.request, "Admin logged in")
        return response

    def get_success_url(self):
        return reverse_lazy('admin_dashboard')

def admin_logout(request):
    _log_audit(request, "Admin logged out")
    logout(request)
    return redirect('admin_login')

def logout_view(request):
    logout(request)
    return redirect('catalog')

def signup(request):
    """Register regular customers only."""
    if request.user.is_authenticated and request.user.is_staff:
        return redirect('admin_dashboard')
    if request.method == 'POST':
        form = BicolikhaSignupForm(request.POST)
        if form.is_valid():
            try:
                with transaction.atomic():
                    user = form.save(commit=False)
                    user.username = form.cleaned_data['email']
                    user.phone_number = form.cleaned_data['phone_number']
                    user.set_password(form.cleaned_data['password'])
                    user.save() # Names are saved here automatically by the form into auth_user
                    Cart.objects.get_or_create(user=user)


                login(request, user, backend='django.contrib.auth.backends.ModelBackend')
                return redirect('catalog')
            except Exception as e:
                form.add_error(None, f"Signup Error: {e}")
    else:
        form = BicolikhaSignupForm()
    return render(request, 'registration/signup.html', {'form': form})


def artist_application(request):
    if request.user.is_authenticated and request.user.is_staff:
        return redirect('admin_dashboard')

    if request.method == 'POST':
        try:
            with transaction.atomic():
                artist_name = (request.POST.get('artist_name') or '').strip()
                application = _create_artist_application_from_post(request, artist_name)

            _send_application_email(
                application,
                "Bicolikha Artist Application Received",
                f"Your artist application for {application.artist_name} has been received and is pending admin review."
            )
            messages.success(request, "Your artist application has been submitted and is waiting for admin review.")
            return redirect('artist_application')
        except ValueError as exc:
            messages.error(request, str(exc))

    initial_name = ''
    initial_email = ''
    initial_phone = ''
    initial_municipality = ''
    initial_brgy = ''
    initial_zipcode = ''
    if request.user.is_authenticated:
        initial_name = request.user.get_full_name() or request.user.username
        initial_email = request.user.email
        initial_phone = getattr(request.user, 'phone_number', '') or ''
        primary_address = _get_primary_address(request.user)
        if primary_address:
            initial_phone = initial_phone or primary_address.phone_num or ''
            initial_municipality = primary_address.municipality or ''
            initial_brgy = primary_address.brgy or ''
            initial_zipcode = primary_address.zipcode or ''

    return render(request, 'products/artist_application.html', {
        'application_categories': Category.objects.order_by('category_name'),
        'initial_name': initial_name,
        'initial_email': initial_email,
        'initial_phone': initial_phone,
        'initial_municipality': initial_municipality,
        'initial_brgy': initial_brgy,
        'initial_zipcode': initial_zipcode,
    })

# --- 2. ADMINISTRATIVE / MANAGEMENT HUB ---

from django.utils import timezone
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import user_passes_test

@user_passes_test(lambda u: u.is_staff, login_url='admin_login')
def admin_users(request):
    """General Users overview page for the dashboard."""
    
    # 1. --- HANDLE POST ACTIONS (Approve/Reject) ---
    if request.method == 'POST':
        application = get_object_or_404(
            ArtistApplication.objects.select_related('user'),
            application_id=request.POST.get('application_id')
        )

        if 'approve_artist_application' in request.POST:
            # Security Check: Only allow if status is still Pending
            if application.application_status != 'Pending':
                messages.error(request, f"{application.artist_name} has already been {application.application_status.lower()} and can no longer be changed.")
                return redirect('admin_users')

            # Use your helper function to process approval
            _approve_artist_application(application)
            _send_application_email(
                application,
                "Bicolikha Artist Application Approved",
                f"Your artist application for {application.artist_name} has been approved."
            )
            _log_audit(request, f"Approved artist application for {application.artist_name}")
            messages.success(request, f"Approved artist application for {application.artist_name}.")
            return redirect('admin_users')

        if 'reject_artist_application' in request.POST:
            # Security Check: Only allow if status is still Pending
            if application.application_status != 'Pending':
                messages.error(request, f"{application.artist_name} has already been {application.application_status.lower()} and can no longer be changed.")
                return redirect('admin_users')

            application.application_status = 'Rejected'
            application.date_reviewed = timezone.now()
            application.save(update_fields=['application_status', 'date_reviewed'])
            _send_application_email(
                application,
                "Bicolikha Artist Application Rejected",
                f"Your artist application for {application.artist_name} was not approved."
            )
            _log_audit(request, f"Rejected artist application for {application.artist_name}")
            messages.success(request, f"Rejected artist application for {application.artist_name}.")
            return redirect('admin_users')

    # --- GET FILTER PARAMETERS ---
    now = timezone.now()
    selected_month = int(request.GET.get('month', now.month))
    selected_year = int(request.GET.get('year', now.year))
    artist_application_status = request.GET.get('application_status', 'Pending')
    if artist_application_status not in ['Pending', 'Approved', 'Rejected']:
        artist_application_status = 'Pending'

    # --- 1. CALCULATE WEEKLY TRENDS FOR THE SELECTED MONTH ---
    # Find how many days are in the selected month
    _, num_days = calendar.monthrange(selected_year, selected_month)
    
    registration_trends = []
    trend_labels = []
    
    # Break the month into 4 or 5 weeks (7-day intervals)
    for i in range(0, num_days, 7):
        start_day = i + 1
        end_day = min(i + 7, num_days)
        
        start_date = timezone.make_aware(datetime(selected_year, selected_month, start_day))
        end_date = timezone.make_aware(datetime(selected_year, selected_month, end_day, 23, 59, 59))
        
        count = User.objects.filter(
            date_joined__range=(start_date, end_date), 
            is_staff=False
        ).count()
        
        registration_trends.append(count)
        trend_labels.append(f"Week {len(registration_trends)}")

    # --- 2. CALCULATE GENERAL STATS ---
    total_users_count = User.objects.filter(is_staff=False).count()
    active_users_count = User.objects.filter(is_active=True, is_staff=False).count()
    new_this_month_count = User.objects.filter(
        date_joined__year=selected_year,
        date_joined__month=selected_month,
        is_staff=False
    ).count()
    
    active_rate = round((active_users_count / total_users_count * 100), 1) if total_users_count > 0 else 0

    # --- 3. CHART DATA (Distribution) ---
    total_artists = Artist.objects.count()
    regular_customers = max(0, total_users_count - total_artists)

    # --- 4. PREPARE MONTH LIST FOR DROPDOWN ---
    months_list = []
    for m in range(1, 13):
        months_list.append({'num': m, 'name': calendar.month_name[m]})

    # --- 5. APPLICATIONS ---
    application_query = request.GET.copy()
    application_query.pop('application_status', None)
    application_querystring = application_query.urlencode()
    artist_application_counts = {
        status: ArtistApplication.objects.filter(application_status=status).count()
        for status in ['Pending', 'Approved', 'Rejected']
    }
    recent_artist_applications = ArtistApplication.objects.filter(
        application_status=artist_application_status
    ).select_related('user').prefetch_related('products', 'products__category').order_by('-date_submitted')[:8]
    _decorate_artist_applications(recent_artist_applications)

    context = {
        'total_users': total_users_count,
        'active_users': active_users_count,
        'new_this_month': new_this_month_count,
        'active_rate': active_rate,
        'total_artists': total_artists,
        'regular_customers': regular_customers,
        'registration_trends': registration_trends,
        'trend_labels': trend_labels,
        'recent_artist_applications': recent_artist_applications,
        'artist_application_status': artist_application_status,
        'artist_application_counts': artist_application_counts,
        'application_querystring': application_querystring,
        'months_list': months_list,
        'selected_month': selected_month,
        'selected_year': selected_year,
        'current_month_name': calendar.month_name[selected_month],
    }
    return render(request, 'admin/admin_users.html', context)

@user_passes_test(lambda u: u.is_staff, login_url='admin_login')
def admin_dashboard(request):
    # 1. Calculate Stats
    total_users = User.objects.filter(is_staff=False).count()
    total_orders = Order.objects.exclude(status='Cancelled').count()
    total_products = Artwork.objects.count()
    total_revenue = Order.objects.exclude(status='Cancelled').aggregate(Sum('total_amount'))['total_amount__sum'] or 0

    # 2. Performance Chart (Status Distribution)
    status_distribution = list(Order.objects.values('status').annotate(count=Count('order_id')))

    context = {
        'total_users': total_users,
        'total_orders': total_orders,
        'total_products': total_products,
        'total_revenue': total_revenue,
        'status_distribution': status_distribution,
    }
    return render(request, 'admin/admin_dashboard.html', context)

@user_passes_test(lambda u: u.is_staff, login_url='admin_login')
def admin_analytics(request):
    total_revenue = Order.objects.exclude(status='Cancelled').aggregate(Sum('total_amount'))['total_amount__sum'] or 0
    category_sales = list(Category.objects.annotate(total_sold=Sum('artwork__orderdetail__quantity')).values('category_name', 'total_sold'))
    status_counts = list(Order.objects.values('status').annotate(count=Count('order_id')))

    context = {
        'total_revenue': total_revenue,
        'total_users': User.objects.count(),
        'total_orders': Order.objects.count(),
        'category_sales': category_sales,
        'status_counts': status_counts,
    }
    return render(request, 'admin/admin_analytics.html', context)

@user_passes_test(lambda u: u.is_staff, login_url='admin_login')
def admin_manage_accounts(request):
    if request.method == 'POST':
        # --- DELETE USER ---
        if 'delete_user' in request.POST:
            user_to_delete = get_object_or_404(User, id=request.POST.get('user_id'))
            if not user_to_delete.is_superuser:
                deleted_label = user_to_delete.email or user_to_delete.username
                user_to_delete.delete()
                _log_audit(request, f"Deleted customer account {deleted_label}")
            return redirect('manage_accounts')
            
        # --- PROMOTE TO ARTIST ---
        elif 'promote_to_artist' in request.POST:
            # 1. Get the specific user being promoted
            target_user = get_object_or_404(User, id=request.POST.get('user_id'))
            
            # 2. Create the Artist record without changing the user's customer account.
            Artist.objects.create(
                artist_name=request.POST.get('artist_name'),
                artist_email=target_user.email,
                artist_phone_num=request.POST.get('contact'),
                artist_municipality=request.POST.get('municipality'),
                artist_brgy=request.POST.get('brgy'),
                artist_zipcode=request.POST.get('zipcode'),
                artist_description="Verified Artist"
            )
            _log_audit(request, f"Promoted {target_user.email or target_user.username} to artist")
            return redirect('manage_accounts')

    users = User.objects.filter(is_staff=False).order_by('-date_joined')
    for u in users:
        u.address_info = Address.objects.filter(user=u, address_type='Default').first()
        
    return render(request, 'admin/manage_accounts.html', {'users': users})

@user_passes_test(lambda u: u.is_staff, login_url='admin_login')
def admin_products(request):
    # 1. GET FILTER/SORT PARAMETERS
    sort_by = request.GET.get('sort', '-prod_id')
    search_query = request.GET.get('q', '')
    selected_cats = request.GET.getlist('cat')
    product_submission_status = request.GET.get('submission_status', 'Pending')
    if product_submission_status not in ['Pending', 'Approved', 'Rejected']:
        product_submission_status = 'Pending'

    # 2. HANDLE ACTIONS (POST)
    if request.method == 'POST':
        if 'add_popular_ad' in request.POST:
            form = PopularAdForm(request.POST, request.FILES)
            if form.is_valid():
                popular_ad = form.save()
                _log_audit(request, f"Added popular page ad {popular_ad.title or popular_ad.ad_id}")
                messages.success(request, "Popular page ad photo added.")
            else:
                messages.error(request, "Please choose a valid ad image before uploading.")
            return redirect('admin_products')

        if 'delete_popular_ad' in request.POST:
            popular_ad = get_object_or_404(PopularAd, ad_id=request.POST.get('ad_id'))
            ad_label = popular_ad.title or f"ad {popular_ad.ad_id}"
            popular_ad.delete()
            _log_audit(request, f"Removed popular page ad {ad_label}")
            messages.success(request, "Popular page ad photo removed.")
            return redirect('admin_products')

        if 'approve_stock_adjustment' in request.POST or 'reject_stock_adjustment' in request.POST:
            stock_request = get_object_or_404(
                ArtistStockAdjustmentRequest.objects.select_related('artist', 'product'),
                request_id=request.POST.get('stock_request_id')
            )

            try:
                if 'approve_stock_adjustment' in request.POST:
                    _approve_stock_adjustment_request(stock_request)
                    _log_audit(request, f"Approved {stock_request.adjustment_type.lower()} stock request for {stock_request.product.title}")
                    messages.success(request, f"Approved {stock_request.adjustment_type.lower()} stock request for {stock_request.product.title}.")
                else:
                    _reject_stock_adjustment_request(stock_request)
                    _log_audit(request, f"Rejected stock request for {stock_request.product.title}")
                    messages.success(request, f"Rejected stock request for {stock_request.product.title}.")
            except ValueError as exc:
                messages.error(request, str(exc))
            return redirect('admin_products')

        if 'approve_artist_application' in request.POST or 'reject_artist_application' in request.POST:
            application = get_object_or_404(
                ArtistApplication.objects.select_related('user'),
                application_id=request.POST.get('application_id')
            )

            if 'approve_artist_application' in request.POST:
                if application.application_status != 'Pending':
                    messages.error(request, f"This product submission has already been {application.application_status.lower()} and can no longer be changed.")
                    return redirect('admin_products')

                _approve_artist_application(application)
                _send_application_email(
                    application,
                    "Bicolikha Product Submission Approved",
                    f"Your submission for {application.artist_name} has been approved."
                )
                _log_audit(request, f"Approved product submission for {application.artist_name}")
                messages.success(request, f"Approved product submission for {application.artist_name}.")
                return redirect('admin_products')

            if application.application_status != 'Pending':
                messages.error(request, f"This product submission has already been {application.application_status.lower()} and can no longer be changed.")
                return redirect('admin_products')

            application.application_status = 'Rejected'
            application.date_reviewed = timezone.now()
            application.save(update_fields=['application_status', 'date_reviewed'])
            _send_application_email(
                application,
                "Bicolikha Product Submission Rejected",
                f"Your submission for {application.artist_name} was not approved."
            )
            _log_audit(request, f"Rejected product submission for {application.artist_name}")
            messages.success(request, f"Rejected product submission for {application.artist_name}.")
            return redirect('admin_products')
        
        # --- ACTION: ADD CATEGORY ---
        elif 'add_category' in request.POST:
            name = request.POST.get('category_name')
            desc = request.POST.get('category_desc')
            if name:
                Category.objects.create(category_name=name, category_desc=desc)
                _log_audit(request, f"Added category {name}")
        
        # --- ACTION: ADD PRODUCT ---
        elif 'add_product' in request.POST:
            form = ProductForm(request.POST, request.FILES)
            if form.is_valid():
                product = form.save()
                if product.stock_qty and product.stock_qty > 0:
                    SupplyInventory.objects.create(
                        product=product,
                        supplied_qty=product.stock_qty
                    )
                _log_audit(request, f"Added product {product.title}")
        
        # --- ACTION: UPDATE PRODUCT ---
        elif 'update_product' in request.POST:
            prod_id = request.POST.get('prod_id')
            prod = get_object_or_404(Artwork, prod_id=prod_id)
            previous_stock = prod.stock_qty or 0
            try:
                new_stock = int(request.POST.get('stock_qty') or 0)
            except (TypeError, ValueError):
                new_stock = previous_stock

            prod.title = request.POST.get('title')
            prod.price = request.POST.get('price')
            prod.stock_qty = new_stock
            prod.description = request.POST.get('description')
            prod.category_id = request.POST.get('category')
            prod.artist_id = request.POST.get('artist')
            if request.FILES.get('image'):
                prod.image = request.FILES.get('image')
            prod.save()

            supplied_delta = new_stock - previous_stock
            if supplied_delta > 0:
                SupplyInventory.objects.create(
                    product=prod,
                    supplied_qty=supplied_delta
                )
            elif supplied_delta < 0:
                _deduct_latest_supply_inventory(prod, abs(supplied_delta))
            _log_audit(request, f"Updated product {prod.title}")

        # --- ACTION: DELETE PRODUCT ---
        elif 'delete_product' in request.POST:
            prod_id = request.POST.get('prod_id')
            product = get_object_or_404(Artwork, prod_id=prod_id)
            product_title = product.title
            product.delete()
            _log_audit(request, f"Deleted product {product_title}")

        return redirect('admin_products')

    # 3. FETCH INVENTORY DATA (With Search, Filter, and Sort)
    products_query = Artwork.objects.all()
    
    if search_query:
        products_query = products_query.filter(Q(title__icontains=search_query))
    
    if selected_cats:
        products_query = products_query.filter(category_id__in=selected_cats)

    sort_mapping = {
        'title': 'title', '-title': '-title',
        'price': 'price', '-price': '-price',
        'stock': 'stock_qty', '-stock': '-stock_qty'
    }
    products_query = products_query.order_by(sort_mapping.get(sort_by, '-prod_id'))
    products_paginator = Paginator(products_query, 10)
    products_page = products_paginator.get_page(request.GET.get('page'))
    products = products_page.object_list
    pagination_query = request.GET.copy()
    pagination_query.pop('page', None)
    pagination_querystring = pagination_query.urlencode()
    submission_query = request.GET.copy()
    submission_query.pop('page', None)
    submission_query.pop('submission_page', None)
    submission_query.pop('submission_status', None)
    submission_querystring = submission_query.urlencode()
    submission_pagination_query = request.GET.copy()
    submission_pagination_query.pop('page', None)
    submission_pagination_query.pop('submission_page', None)
    submission_pagination_querystring = submission_pagination_query.urlencode()

    # 4. CALCULATE DASHBOARD ANALYTICS (For the Stat Cards)
    total_count = Artwork.objects.count()
    in_stock = Artwork.objects.filter(stock_qty__gt=0).count()
    low_stock = Artwork.objects.filter(stock_qty__lte=5, stock_qty__gt=0).count()
    
    # Total Value = Sum of (Price * Stock Quantity) for every item
    # We use F() expressions to do the math directly in the database
    total_value = Artwork.objects.aggregate(
        val=Sum(F('price') * F('stock_qty'))
    )['val'] or 0

    # 5. FETCH CHART DATA (Category Distribution)
    cat_distribution = list(Category.objects.annotate(
        count=Count('artwork')
    ).values('category_name', 'count'))

    product_submissions_query = ArtistApplication.objects.filter(
        application_status=product_submission_status
    ).select_related('user').prefetch_related('products', 'products__category').order_by('-date_submitted')
    product_submissions_paginator = Paginator(product_submissions_query, 6)
    product_submissions_page = product_submissions_paginator.get_page(request.GET.get('submission_page'))
    product_submissions = product_submissions_page.object_list
    _decorate_artist_applications(product_submissions)
    product_submission_counts = {
        status: ArtistApplication.objects.filter(
            application_status=status
        ).count()
        for status in ['Pending', 'Approved', 'Rejected']
    }
    pending_stock_adjustments = ArtistStockAdjustmentRequest.objects.filter(
        status='Pending'
    ).select_related('artist', 'product', 'product__category').order_by('-date_submitted')

    today = timezone.localdate()
    sales_days = [today - timedelta(days=offset) for offset in range(6, -1, -1)]
    sales_rows = Order.objects.exclude(status='Cancelled').filter(
        created_at__date__gte=sales_days[0],
        created_at__date__lte=today
    ).annotate(day=TruncDate('created_at')).values('day').annotate(total=Sum('total_amount')).order_by('day')
    sales_by_day = {row['day']: float(row['total'] or 0) for row in sales_rows}
    sales_chart_data = {
        'labels': [day.strftime('%a') for day in sales_days],
        'values': [sales_by_day.get(day, 0) for day in sales_days],
    }

    # 6. RENDER
    return render(request, 'admin/admin_products.html', {
        'products': products,
        'categories': Category.objects.all(),
        'artists': Artist.objects.all(),
        'p_form': ProductForm(),
        'popular_ad_form': PopularAdForm(),
        'popular_ads': PopularAd.objects.all(),
        'current_sort': sort_by,
        'search_query': search_query,
        'selected_cats': selected_cats,
        'products_page': products_page,
        'pagination_querystring': pagination_querystring,
        'submission_querystring': submission_querystring,
        'submission_pagination_querystring': submission_pagination_querystring,
        # Analytics Context
        'total_count': total_count,
        'in_stock': in_stock,
        'low_stock': low_stock,
        'total_value': total_value,
        'cat_distribution': cat_distribution,
        'product_submissions': product_submissions,
        'product_submissions_page': product_submissions_page,
        'product_submission_status': product_submission_status,
        'product_submission_counts': product_submission_counts,
        'pending_stock_adjustments': pending_stock_adjustments,
        'sales_chart_data': sales_chart_data
    })

@user_passes_test(lambda u: u.is_staff, login_url='admin_login')
def admin_orders(request):
    sort_by = request.GET.get('sort', 'date_desc')
    sort_map = {
        'date_desc': ['-created_at', '-order_id'],
        'date_asc': ['created_at', 'order_id'],
        'artist_asc': ['artist_sort', '-created_at'],
        'artist_desc': ['-artist_sort', '-created_at'],
        'price_desc': ['-total_amount', '-created_at'],
        'price_asc': ['total_amount', '-created_at'],
    }
    if sort_by not in sort_map:
        sort_by = 'date_desc'

    orders = (
        Order.objects
        .select_related('user', 'payment', 'shipment', 'shipment__address')
        .annotate(artist_sort=Min('orderdetail__product__artist__artist_name'))
        .order_by(*sort_map[sort_by])
    )
    
    if request.method == 'POST' and 'update_status' in request.POST:
        order = get_object_or_404(Order, order_id=request.POST.get('order_id'))
        new_status = request.POST.get('status')
        order.status = new_status

        order_items = OrderDetail.objects.filter(order=order).select_related('product', 'product__artist')
        artists = []
        seen_artist_ids = set()
        for item in order_items:
            artist = item.product.artist
            if artist and artist.artist_id not in seen_artist_ids:
                seen_artist_ids.add(artist.artist_id)
                artists.append(artist)

        for artist in artists:
            message_text = f"Admin updated Order #BK-{order.order_id} to {new_status}."
            Notification.objects.create(
                order=order,
                artist=artist,
                message_text=message_text,
                sender_role='System',
                status_update=new_status,
                is_read=False
            )
            _send_mock_artist_email(
                artist,
                f"Bicolikha Order #BK-{order.order_id}: {new_status}",
                message_text
            )

        # --- SYNC TO SHIPMENT TABLE ---
        if order.shipment:
            if new_status == 'Prepared':
                order.shipment.shipment_status = 'Prepared'
            elif new_status == 'Shipped':
                order.shipment.shipment_status = 'In Transit'
                order.shipment.shipment_date = timezone.now().date() # Sets the date
            elif new_status == 'Delivered':
                # Update Shipment
                if order.shipment:
                    order.shipment.shipment_status = 'Arrived'
                    order.shipment.save()
                
                # Update Payment (THE FIX)
                if order.payment:
                    order.payment.status = 'Paid'
                    order.payment.save()
            elif new_status == 'Cancelled':
                order.shipment.shipment_status = 'Cancelled'
            order.shipment.save()

        order.save()
        _log_audit(request, f"Updated order #BK-{order.order_id} status to {new_status}")
        return redirect('admin_orders')
    
    # Pre-fetch logic for display...
    for o in orders:
        o.items = OrderDetail.objects.filter(order=o).select_related('product', 'product__artist')
        o.customer_address = (
            o.shipment.address if o.shipment and o.shipment.address else
            Address.objects.filter(user=o.user, is_default=True).first() or
            Address.objects.filter(user=o.user).order_by('-address_id').first()
        )
        artist_names = []
        seen_artist_ids = set()
        for item in o.items:
            artist = item.product.artist
            if artist and artist.artist_id not in seen_artist_ids:
                seen_artist_ids.add(artist.artist_id)
                artist_names.append(artist.artist_name)
        o.artist_names = artist_names
        o.item_count = o.items.count()

    return render(request, 'admin/admin_orders.html', {
        'orders': orders,
        'current_sort': sort_by,
    })

@user_passes_test(lambda u: u.is_staff, login_url='admin_login')
def admin_reports(request):
    sales = Order.objects.exclude(status='Cancelled').aggregate(total_revenue=Sum('total_amount'), total_items=Sum('total_qty'))
    top_products = OrderDetail.objects.values('product__title').annotate(total_sold=Sum('quantity'), total_earned=Sum('subtotal')).order_by('-total_sold')[:5]
    audit_logs = AuditLog.objects.select_related('user').order_by('-timestamp')[:20]
    return render(request, 'admin/admin_reports.html', {
        'sales': sales,
        'top_products': top_products,
        'audit_logs': audit_logs,
        'report_date': timezone.now(),
        'active_artists': Artist.objects.count()
    })

@user_passes_test(lambda u: u.is_staff, login_url='admin_login')
def admin_manage_artists(request):
    if request.method == 'POST':
        artist = get_object_or_404(Artist, artist_id=request.POST.get('artist_id'))
        if 'unpromote_artist' in request.POST:
            artist_label = artist.artist_name
            artist.delete()
            _log_audit(request, f"Revoked artist privileges for {artist_label}")
        elif 'edit_artist' in request.POST:
            artist.artist_name = (request.POST.get('artist_name') or '').strip()
            artist.artist_email = (request.POST.get('artist_email') or '').strip().lower()
            artist.artist_phone_num = (request.POST.get('artist_phone_num') or '').strip()
            artist.artist_description = (request.POST.get('artist_description') or '').strip()
            artist.artist_municipality = (request.POST.get('artist_municipality') or '').strip()
            artist.artist_brgy = (request.POST.get('artist_brgy') or '').strip()
            artist.artist_zipcode = (request.POST.get('artist_zipcode') or '').strip()

            if request.FILES.get('artist_image'):
                artist.artist_image = _save_artist_profile_image(
                    artist.artist_email or artist.artist_id,
                    request.FILES.get('artist_image'),
                    artist.artist_name
                )

            artist.save()
            _log_audit(request, f"Updated artist profile for {artist.artist_name}")
            messages.success(request, f"Updated artist profile for {artist.artist_name}.")
        return redirect('manage_artists')
    return render(request, 'admin/manage_artists.html', {
        'artists': Artist.objects.order_by('artist_name')
    })

@user_passes_test(lambda u: u.is_staff, login_url='admin_login')
def admin_manage_admins(request):
    admins = User.objects.filter(is_staff=True).order_by('-last_login')
    return render(request, 'admin/manage_admins.html', {'admins': admins})

@user_passes_test(lambda u: u.is_staff, login_url='admin_login')
def admin_messages(request):
    # 1. Get all artists for the sidebar
    artists = Artist.objects.all().order_by('artist_name')
    artist_updates = Notification.objects.filter(sender_role='Artist').order_by('-timestamp')
    artist_updates.filter(is_read=False).update(is_read=True)
    # 2. Check if a specific artist is selected
    active_artist_id = request.GET.get('artist_id')
    active_artist = None
    messages_list = []
    if active_artist_id:
        active_artist = get_object_or_404(Artist, artist_id=active_artist_id)
        messages_list = Notification.objects.filter(artist=active_artist).order_by('timestamp')
        

    # 3. Handle sending a new message manually
    if request.method == 'POST':
        msg_text = request.POST.get('message')
        artist_id = request.POST.get('artist_id')
        if msg_text and artist_id:
            target_artist = get_object_or_404(Artist, artist_id=artist_id)
            related_order = Order.objects.filter(orderdetail__product__artist=target_artist).distinct().order_by('-order_id').first()
            if related_order:
                Notification.objects.create(
                    artist=target_artist,
                    order=related_order,
                    message_text=msg_text,
                    sender_role='Admin',
                )
            _send_mock_artist_email(
                target_artist,
                "Bicolikha Admin Message",
                msg_text
            )
            _log_audit(request, f"Sent management message to {target_artist.artist_name}")
            return redirect(f'/management/messages/?artist_id={artist_id}')

    return render(request, 'admin/admin_messages.html', {
        'artists': artists,
        'active_artist': active_artist,
        'messages_list': messages_list,
        'artist_updates': artist_updates
    })

# --- 3. PUBLIC STOREFRONT VIEWS ---

def catalog(request):
    if request.user.is_authenticated and request.user.is_staff: return redirect('admin_dashboard')
    categories = Category.objects.filter(artwork__isnull=False).distinct().order_by('category_name')
    current_sort = request.GET.get('sort', 'latest')
    stock_order = Case(
        When(stock_qty__gt=0, then=Value(0)),
        default=Value(1),
        output_field=IntegerField()
    )
    artworks = Artwork.objects.select_related('artist', 'category').annotate(stock_order=stock_order)

    sort_map = {
        'latest': ['stock_order', '-prod_id'],
        'title_asc': ['stock_order', 'title', '-prod_id'],
        'title_desc': ['stock_order', '-title', '-prod_id'],
        'artist_asc': ['stock_order', 'artist__artist_name', 'title'],
        'price_low': ['stock_order', 'price', 'title'],
        'price_high': ['stock_order', '-price', 'title'],
        'category_asc': ['stock_order', 'category__category_name', 'title'],
    }
    artworks = artworks.order_by(*sort_map.get(current_sort, sort_map['latest']))

    return render(request, 'products/catalog.html', {
        'artworks': artworks,
        'categories': categories,
        'current_sort': current_sort,
    })


def categories_overview(request):
    if request.user.is_authenticated and request.user.is_staff:
        return redirect('admin_dashboard')

    categories = Category.objects.filter(artwork__isnull=False).distinct().order_by('category_name')
    stock_order = Case(
        When(stock_qty__gt=0, then=Value(0)),
        default=Value(1),
        output_field=IntegerField()
    )
    category_data = [{
        'category': category,
        'products': Artwork.objects.filter(category=category).annotate(stock_order=stock_order).order_by('stock_order', '-prod_id')[:4]
    } for category in categories]

    return render(request, 'products/categories.html', {
        'category_data': category_data,
    })

def product_detail(request, prod_id):
    if request.user.is_authenticated and request.user.is_staff:
        return redirect('admin_dashboard')
    
    product = get_object_or_404(Artwork, prod_id=prod_id)
    # Fetch all reviews for this specific product
    reviews = Review.objects.filter(product=product).order_by('-date_created')
    liked_product_ids = []
    if request.user.is_authenticated:
        liked_product_ids = list(
            Like.objects.filter(user=request.user, product=product).values_list('product_id', flat=True)
        )
    
    return render(request, 'products/product_detail.html', {
        'product': product,
        'reviews': reviews,
        'liked_product_ids': liked_product_ids
    })

@login_required
def edit_review(request, review_id):
    review = get_object_or_404(Review, review_id=review_id, user=request.user)
    if request.method == 'POST':
        review.rating = request.POST.get('rating')
        review.description = request.POST.get('description')
        if request.FILES.get('review_image'):
            review.image = request.FILES.get('review_image')
        review.save()
    return redirect('product_detail', prod_id=review.product.prod_id)

@login_required
def delete_review(request, review_id):
    review = get_object_or_404(Review, review_id=review_id, user=request.user)
    prod_id = review.product.prod_id
    review.delete()
    return redirect('product_detail', prod_id=prod_id)

def artists(request):
    if request.user.is_authenticated and request.user.is_staff: return redirect('admin_dashboard')
    return render(request, 'products/artists.html', {'artists': Artist.objects.all()})

def about(request):
    return render(request, 'products/about.html')

def popular(request):
    selected_category = request.GET.get('category', '')
    categories = Category.objects.filter(artwork__isnull=False).distinct().order_by('category_name')

    trending = Artwork.objects.select_related('category').annotate(
        sold_count=Sum('orderdetail__quantity')
    ).order_by('-sold_count', '-prod_id')

    if selected_category:
        trending = trending.filter(category_id=selected_category)

    paginator = Paginator(trending, 12)
    page_obj = paginator.get_page(request.GET.get('page'))
    return render(request, 'products/popular.html', {
        'artworks': page_obj.object_list,
        'page_obj': page_obj,
        'categories': categories,
        'selected_category': selected_category,
        'popular_ads': PopularAd.objects.filter(is_active=True),
    })

def _build_order_timeline(order):
    timeline = []
    order_timestamp = getattr(order, 'created_at', None)

    if order_timestamp:
        timeline.append({
            'title': 'Order placed',
            'description': 'Your order has been received and is being prepared.',
            'timestamp': order_timestamp,
            'timestamp_format': 'm/d/Y h:i A',
            'is_current': order.status in ['Processing', 'To Pay', 'Pending']
        })

    if order.shipment and order.shipment.shipment_date:
        timeline.append({
            'title': 'Shipment update',
            'description': f"Shipment status: {order.shipment.shipment_status}.",
            'timestamp': order.shipment.shipment_date,
            'timestamp_format': 'm/d/Y',
            'is_current': order.status == 'Shipped'
        })

    latest_notification = Notification.objects.filter(order=order).order_by('-timestamp').first()
    if latest_notification:
        timeline.append({
            'title': 'Latest update',
            'description': latest_notification.message_text,
            'timestamp': latest_notification.timestamp,
            'timestamp_format': 'm/d/Y h:i A',
            'is_current': order.status not in ['Delivered', 'Cancelled']
        })

    if order.status == 'Delivered':
        delivered_timestamp = order.shipment.shipment_date if order.shipment and order.shipment.shipment_date else order_timestamp
        timeline.append({
            'title': 'Delivered',
            'description': 'Your order has been marked as delivered.',
            'timestamp': delivered_timestamp,
            'timestamp_format': 'm/d/Y' if order.shipment and order.shipment.shipment_date else 'm/d/Y h:i A',
            'is_current': True
        })

    if order.status == 'Cancelled':
        timeline.append({
            'title': 'Cancelled',
            'description': 'This order was cancelled.',
            'timestamp': order_timestamp,
            'timestamp_format': 'm/d/Y h:i A',
            'is_current': True
        })

    return timeline

def _get_artist_status_map(order):
    status_map = {}
    artist_updates = Notification.objects.filter(
        order=order,
        sender_role='System'
    ).select_related('artist').order_by('artist_id', '-timestamp')

    for notif in artist_updates:
        if notif.artist_id not in status_map:
            status_map[notif.artist_id] = notif

    return status_map

def _build_order_artist_groups(order, reviewed_products):
    artist_groups = []
    artist_status_map = _get_artist_status_map(order)
    grouped_items = {}

    for item in order.items:
        artist = item.product.artist
        if not artist:
            continue
        grouped_items.setdefault(artist.artist_id, {
            'artist': artist,
            'items': [],
        })
        grouped_items[artist.artist_id]['items'].append(item)

    total_artists = len(grouped_items)
    shipping_share = (order.delivery_fee / total_artists) if total_artists and order.delivery_fee else 0

    for artist_id, group in grouped_items.items():
        items = group['items']
        status_notif = artist_status_map.get(artist_id)
        current_artist_status = status_notif.status_update if status_notif else None

        if order.status == 'Delivered':
            display_status = 'Delivered'
        elif order.status == 'Cancelled':
            display_status = 'Cancelled'
        elif order.status == 'Shipped':
            display_status = 'Shipped'
        elif order.status == 'Prepared':
            display_status = 'Prepared'
        else:
            display_status = 'Processing'

        first_unrated_item = next(
            (item for item in items if item.product.prod_id not in reviewed_products),
            None
        )
        has_unrated_items = order.status == 'Delivered' and first_unrated_item is not None

        artist_groups.append({
            'artist': group['artist'],
            'items': items,
            'preview_items': items[:4],
            'item_count': sum(item.quantity or 0 for item in items),
            'subtotal': sum(item.subtotal or 0 for item in items),
            'shipping_fee': shipping_share,
            'status': display_status,
            'status_update': current_artist_status,
            'latest_update_at': status_notif.timestamp if status_notif else None,
            'first_unrated_item': first_unrated_item,
            'has_unrated_items': has_unrated_items,
        })

    return artist_groups

def _decorate_order(order, reviewed_products):
    order.items = list(OrderDetail.objects.filter(order=order).select_related('product', 'product__artist'))
    order.is_cancellable = order.status in ['Processing', 'To Pay', 'Pending']
    order.order_date = getattr(order, 'created_at', None)
    order.item_count = sum(item.quantity or 0 for item in order.items)
    order.preview_items = order.items[:4]
    order.extra_item_count = max(len(order.items) - len(order.preview_items), 0)
    order.first_item = order.items[0] if order.items else None
    order.first_unrated_item = next(
        (item for item in order.items if item.product.prod_id not in reviewed_products),
        None
    )
    order.has_unrated_items = order.status == 'Delivered' and any(
        item.product.prod_id not in reviewed_products for item in order.items
    )
    order.artist_groups = _build_order_artist_groups(order, reviewed_products)
    order.artist_group_count = len(order.artist_groups)
    order.timeline = _build_order_timeline(order)
    return order

@login_required
def profile_view(request):
    # SECURITY GATE: Admins should not be in the customer profile
    if request.user.is_authenticated and request.user.is_staff:
        return redirect('admin_dashboard')

    # 1. INITIALIZE BASIC DATA
    active_tab = request.GET.get('tab', 'account')
    status_tab = request.GET.get('status', 'all')
    
    # Primary address for Account Info display
    address = _get_primary_address(request.user)
    
    # Full list for the Address section
    all_addresses = [addr for addr in _get_user_addresses(request.user) if _address_is_complete(addr)]
    
    # Customer accounts no longer expose artist/seller functions. Artist records
    # remain as public product metadata and are managed from the admin portal.
    artist_obj = None
    is_artist = False
    if active_tab in ['artist_application', 'artist_products', 'messages']:
        return redirect('/profile/?tab=account')

    # Identify products already reviewed by this user
    reviewed_products = list(Review.objects.filter(user=request.user).values_list('product_id', flat=True))

    # Status mapping for UI Tabs
    status_map = {
        'to_pay': 'To Pay',
        'to_ship': 'Processing',
        'to_receive': 'Shipped',
        'completed': 'Delivered',
        'cancelled': 'Cancelled'
    }

    # 2. HANDLE FORM SUBMISSIONS (POST)
    if request.method == 'POST':
        
        # --- DELETE ADDRESS ---
        if 'delete_address' in request.POST:
            addr_id = request.POST.get('address_id')
            addr = get_object_or_404(Address, address_id=addr_id, user=request.user)
            if not addr.is_default:
                addr.delete()
            return redirect('/profile/?tab=account')
        
        # --- UPDATE PERSONAL INFO & PHOTO ---
        elif 'update_personal_info' in request.POST:
            phone_number = re.sub(r'\D', '', request.POST.get('phone_number') or '')
            if len(phone_number) != 11:
                messages.error(request, "Phone number must be exactly 11 digits.")
                return redirect('/profile/?tab=account')
            if User.objects.exclude(pk=request.user.pk).filter(phone_number=phone_number).exists():
                messages.error(request, "That phone number is already being used by another account.")
                return redirect('/profile/?tab=account')
            request.user.first_name = request.POST.get('fname')
            request.user.last_name = request.POST.get('lname')
            request.user.phone_number = phone_number
            request.user.save()
            if address:
                if request.FILES.get('profile_pix'):
                    address.profile_pix = request.FILES.get('profile_pix')
                address.save()
            return redirect('/profile/?tab=account')

        # --- ADD NEW ADDRESS ---
        elif 'add_new_address' in request.POST:
            try:
                _create_or_update_address_from_post(request, request.user)
            except ValueError as exc:
                messages.error(request, str(exc))
            return redirect('/profile/?tab=account')

        # --- EDIT EXISTING ADDRESS ---
        elif 'update_address' in request.POST:
            addr_id = request.POST.get('address_id')
            addr = get_object_or_404(Address, address_id=addr_id, user=request.user)
            try:
                _create_or_update_address_from_post(request, request.user, instance=addr)
            except ValueError as exc:
                messages.error(request, str(exc))
            return redirect('/profile/?tab=account')

        elif any(key in request.POST for key in [
            'submit_artist_application',
            'update_artist_stock',
            'submit_artist_product_application',
            'artist_update_status',
        ]):
            messages.error(request, "Artist functions are handled by admin.")
            return redirect('/profile/?tab=account')

    # 3. FETCH PURCHASES DATA
    orders_query = Order.objects.filter(user=request.user)
    if status_tab == 'to_ship':
        orders_query = orders_query.filter(status__in=['Processing', 'Prepared'])
    elif status_tab != 'all':
        orders_query = orders_query.filter(status=status_map.get(status_tab, 'Processing'))
    
    orders = orders_query.order_by('-order_id').select_related('payment', 'shipment', 'shipment__address')
    for o in orders:
        _decorate_order(o, reviewed_products)

    # 4. CUSTOMER NOTIFICATIONS (System Alerts)
    customer_notifications = Notification.objects.filter(
        order__user=request.user
    ).exclude(sender_role='Admin').order_by('-timestamp') # Show everything except Admin's private notes

    if active_tab == 'notifications':
        customer_notifications.filter(is_read=False).update(is_read=True)
    
    unread_count = customer_notifications.filter(is_read=False).count()

    # 6. RENDER
    return render(request, 'products/profile.html', {
        'address': address, 'all_addresses': all_addresses, 'orders': orders,
        'active_tab': active_tab, 'status_tab': status_tab, 'is_artist': is_artist,
        'artist_messages': [], 'reviewed_products': reviewed_products,
        'customer_notifications': customer_notifications, 'unread_count': unread_count,
        'unread_artist_count': 0,
    })

@login_required
def order_detail(request, order_id):
    if request.user.is_staff:
        return redirect('admin_dashboard')

    order = get_object_or_404(
        Order.objects.select_related('payment', 'shipment', 'shipment__address'),
        order_id=order_id,
        user=request.user
    )
    reviewed_products = list(Review.objects.filter(user=request.user).values_list('product_id', flat=True))
    liked_product_ids = list(Like.objects.filter(user=request.user).values_list('product_id', flat=True))
    _decorate_order(order, reviewed_products)

    subtotal = sum(item.subtotal or 0 for item in order.items)
    shipping_fee = order.delivery_fee or 0
    address = order.shipment.address if order.shipment and order.shipment.address else None
    latest_notification = Notification.objects.filter(order=order).order_by('-timestamp').first()

    return render(request, 'products/order_detail.html', {
        'order': order,
        'reviewed_products': reviewed_products,
        'liked_product_ids': liked_product_ids,
        'subtotal': subtotal,
        'shipping_fee': shipping_fee,
        'address': address,
        'latest_notification': latest_notification
    })

@login_required
def toggle_like(request, product_id):
    if request.user.is_staff:
        return redirect('admin_dashboard')

    product = get_object_or_404(Artwork, prod_id=product_id)
    next_url = request.POST.get('next') or request.GET.get('next') or reverse_lazy('liked_items')

    like = Like.objects.filter(user=request.user, product=product).first()
    if like:
        like.delete()
    else:
        Like.objects.create(user=request.user, product=product)

    return redirect(next_url)

@login_required
def liked_items(request):
    if request.user.is_staff:
        return redirect('admin_dashboard')

    liked_products = Artwork.objects.filter(
        like__user=request.user
    ).select_related('artist', 'category').distinct().order_by('-like__date_liked')

    liked_product_ids = list(liked_products.values_list('prod_id', flat=True))

    return render(request, 'products/liked_items.html', {
        'liked_products': liked_products,
        'liked_product_ids': liked_product_ids
    })

# --- 4. SHOPPING BAG & CHECKOUT ---

def _get_stock_error(product, quantity):
    quantity = max(int(quantity or 0), 1)

    if product.stock_qty is None:
        return None
    if product.stock_qty <= 0:
        return f"{product.title} is currently out of stock."
    if quantity > product.stock_qty:
        return f"Only {product.stock_qty} item(s) of {product.title} are available right now."

    return None

@login_required
def add_to_cart(request, product_id):
    # 1. SECURITY: Block admins from shopping
    if request.user.is_staff:
        return redirect('admin_dashboard')

    if request.method == 'POST':
        product = get_object_or_404(Artwork, prod_id=product_id)
        submit_type = request.POST.get('submit_type') # From the button name/value

        try:
            qty = max(int(request.POST.get('quantity', 1)), 1)
        except (TypeError, ValueError):
            qty = 1

        stock_error = _get_stock_error(product, qty)
        if stock_error:
            if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.POST.get('ajax') == 'true':
                return JsonResponse({'status': 'error', 'message': stock_error}, status=400)
            messages.error(request, stock_error)
            return redirect('product_detail', prod_id=product.prod_id)

        # --- OPTION A: BUY NOW (Does NOT touch the database) ---
        if submit_type == 'buy_now':
            # Redirect to checkout with product info in the URL
            return redirect(f'/checkout/?buy_now=true&prod_id={product_id}&qty={qty}')

        # --- OPTION B: ADD TO BAG (Saves to SQL) ---
        try:
            with transaction.atomic():
                user_cart, _ = Cart.objects.get_or_create(user=request.user)
                item, created = CartItem.objects.get_or_create(cart=user_cart, product=product)

                requested_quantity = qty if created else item.quantity + qty
                stock_error = _get_stock_error(product, requested_quantity)
                if stock_error:
                    raise ValueError(stock_error)

                item.quantity = requested_quantity
                item.save()

            # Handle AJAX for the flying bag animation
            if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.POST.get('ajax') == 'true':
                total_count = CartItem.objects.filter(cart=user_cart).count()
                return JsonResponse({
                    'status': 'success',
                    'message': f'Added {product.title} to bag!',
                    'cart_count': total_count
                })
            
            messages.success(request, f"Added {product.title} to your bag.")
            return redirect('product_detail', prod_id=product.prod_id)

        except Exception as e:
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({'status': 'error', 'message': str(e)}, status=400)
            messages.error(request, str(e))
            return redirect('product_detail', prod_id=product.prod_id)
            
    return redirect('catalog')

@login_required
def view_cart(request):
    if request.user.is_staff: return redirect('admin_dashboard')
    user_cart, _ = Cart.objects.get_or_create(user=request.user)
    items = CartItem.objects.filter(cart=user_cart).select_related('product', 'product__category')
    has_invalid_selected_items = False

    for item in items:
        if item.product.stock_qty is not None and item.product.stock_qty <= 0:
            item.stock_message = 'Out of stock'
        elif item.product.stock_qty is not None and item.quantity > item.product.stock_qty:
            item.stock_message = f'Only {item.product.stock_qty} in stock'
        else:
            item.stock_message = ''

        if item.is_selected and item.stock_message:
            has_invalid_selected_items = True

    total = sum(i.product.price * i.quantity for i in items if i.is_selected)
    return render(request, 'products/cart.html', {
        'cart_items': items,
        'grand_total': total,
        'has_invalid_selected_items': has_invalid_selected_items
    })

@login_required
def toggle_cart_item(request, item_id):
    item = get_object_or_404(CartItem, id=item_id, cart__user=request.user)
    item.is_selected = not item.is_selected; item.save()
    items = CartItem.objects.filter(cart=item.cart, is_selected=True)
    new_total = sum(i.product.price * i.quantity for i in items)
    return JsonResponse({'status': 'success', 'new_total': float(new_total)})

@login_required
def update_cart_quantity(request, item_id, action):
    item = get_object_or_404(CartItem, id=item_id, cart__user=request.user)
    if action == 'increment' and (item.product.stock_qty is None or item.quantity < item.product.stock_qty):
        item.quantity += 1
    elif action == 'decrement' and item.quantity > 1: item.quantity -= 1
    item.save(); return redirect('view_cart')

@login_required
def remove_from_cart(request, item_id):
    get_object_or_404(CartItem, id=item_id, cart__user=request.user).delete()
    return redirect('view_cart')

@login_required
def checkout_view(request):
    if request.user.is_staff: return redirect('admin_dashboard')

    if request.method == 'POST' and 'add_new_address' in request.POST:
        try:
            new_address = _create_or_update_address_from_post(request, request.user)
            messages.success(request, "New address saved. You can use it for this checkout now.")
            query_string = request.META.get('QUERY_STRING')
            redirect_url = f"{request.path}?{query_string}" if query_string else request.path
            redirect_url = f"{redirect_url}#addressSelectModal" if new_address else redirect_url
            return redirect(redirect_url)
        except ValueError as exc:
            messages.error(request, str(exc))
            query_string = request.META.get('QUERY_STRING')
            return redirect(f"{request.path}?{query_string}" if query_string else request.path)

    # 1. IDENTIFY MODE: Buy Now vs Standard Cart
    buy_now_mode = request.GET.get('buy_now') == 'true'
    artist_groups = {}
    
    if buy_now_mode:
        # VIRTUAL ORDER: Build data from URL, don't look at Cart table
        prod_id = request.GET.get('prod_id')
        qty = int(request.GET.get('qty', 1))
        product = get_object_or_404(Artwork, prod_id=prod_id)
        stock_error = _get_stock_error(product, qty)
        if stock_error:
            messages.error(request, stock_error)
            return redirect('product_detail', prod_id=product.prod_id)
        
        # We create a dictionary that mimics the CartItem structure so the template works
        virtual_item = {
            'product': product,
            'quantity': qty,
            'get_subtotal': product.price * qty
        }
        artist_groups[product.artist] = {'items': [virtual_item], 'sub': float(product.price * qty)}
        
        # Context for the final form
        buy_now_data = {'id': prod_id, 'qty': qty}
    else:
        # STANDARD: Fetch selected items from Cart table
        user_cart = get_object_or_404(Cart, user=request.user)
        selected_items = CartItem.objects.filter(cart=user_cart, is_selected=True).select_related('product', 'product__artist')
        
        if not selected_items.exists():
            messages.error(request, "Select at least one item from your bag before checking out.")
            return redirect('view_cart')

        invalid_items = []
        for item in selected_items:
            stock_error = _get_stock_error(item.product, item.quantity)
            if stock_error:
                invalid_items.append(stock_error)

        if invalid_items:
            messages.error(request, invalid_items[0])
            return redirect('view_cart')

        for i in selected_items:
            if i.product.artist not in artist_groups:
                artist_groups[i.product.artist] = {'items': [], 'sub': 0}
            artist_groups[i.product.artist]['items'].append(i)
            artist_groups[i.product.artist]['sub'] += float(i.product.price * i.quantity)
        
        buy_now_data = None

    # 2. SHARED DATA (Totals & Addresses)
    total_shipping = len(artist_groups) * 60.0
    artist_group_count = len(artist_groups)
    items_subtotal = sum(g['sub'] for g in artist_groups.values())
    grand_total = items_subtotal + total_shipping

    all_addresses = [addr for addr in _get_user_addresses(request.user) if _address_is_complete(addr)]
    selected_address = next((addr for addr in all_addresses if addr.is_default), None) or (all_addresses[0] if all_addresses else None)

    return render(request, 'products/checkout.html', {
        'artist_groups': artist_groups,
        'artist_group_count': artist_group_count,
        'total_shipping': total_shipping,
        'items_subtotal': items_subtotal,
        'grand_total': grand_total,
        'all_addresses': all_addresses,
        'selected_address': selected_address,
        'is_buy_now': buy_now_mode,
        'buy_now_id': buy_now_data['id'] if buy_now_data else None,
        'buy_now_qty': buy_now_data['qty'] if buy_now_data else None
    })

@login_required
def place_order(request):
    if request.method == 'POST':
        try:
            with transaction.atomic():
                # 1. Determine which items are being bought
                buy_now_id = request.POST.get('buy_now_id')
                buy_now_qty = int(request.POST.get('buy_now_qty', 0))
                
                order_items = [] # List of {'prod': Artwork, 'qty': int}

                if buy_now_id:
                    # MODE: Buy Now (Single Item)
                    product = get_object_or_404(Artwork, prod_id=buy_now_id)
                    stock_error = _get_stock_error(product, buy_now_qty)
                    if stock_error:
                        messages.error(request, stock_error)
                        return redirect('product_detail', prod_id=product.prod_id)
                    order_items.append({'prod': product, 'qty': buy_now_qty})
                else:
                    # MODE: Cart Purchase (Multiple Items)
                    user_cart = get_object_or_404(Cart, user=request.user)
                    cart_items = CartItem.objects.filter(cart=user_cart, is_selected=True).select_related('product', 'product__artist')
                    if not cart_items.exists():
                        messages.error(request, "Select at least one item from your bag before placing an order.")
                        return redirect('view_cart')
                    
                    for item in cart_items:
                        stock_error = _get_stock_error(item.product, item.quantity)
                        if stock_error:
                            messages.error(request, stock_error)
                            return redirect('view_cart')
                        order_items.append({'prod': item.product, 'qty': item.quantity})

                # 2. Get Shipping Address
                addr_id = request.POST.get('selected_address_id')
                if not addr_id:
                    raise ValueError("Please add and select a delivery address before placing your order.")

                user_address = get_object_or_404(Address, address_id=addr_id, user=request.user)
                if not _address_is_complete(user_address):
                    raise ValueError("Please complete your delivery address before placing your order.")

                # 3. Create Supporting Records (FIXED HERE)
                # First, Create the Shipment
                new_shipment = Shipment.objects.create(address=user_address, shipment_status='Preparing')
                
                # Second, Create the Payment based on the selected method
                payment_method = request.POST.get('payment_method_val', 'Cash on Delivery')
                payment_status = "Paid" if payment_method == "Mamaya Online Payment" else "Pending"

                new_payment = Payment.objects.create(
                    method=payment_method, 
                    status=payment_status
                )

                # 4. Calculate Final Totals
                subtotal = sum(item['prod'].price * item['qty'] for item in order_items)
                unique_artists = len(set(item['prod'].artist for item in order_items))
                shipping_fee = unique_artists * 60.0

                # 5. Save the Master Order
                order = Order.objects.create(
                    user=request.user, 
                    payment=new_payment, 
                    shipment=new_shipment, # This variable is now correctly defined above
                    total_qty=sum(item['qty'] for item in order_items),
                    delivery_fee=shipping_fee,
                    total_amount=float(subtotal) + shipping_fee,
                    status="Processing"
                )

                # 6. Save Details, Deduct Stock, and Notify Artists
                artist_order_items = {}
                for item in order_items:
                    OrderDetail.objects.create(
                        order=order, product=item['prod'], price=item['prod'].price,
                        quantity=item['qty'], subtotal=item['prod'].price * item['qty']
                    )
                    # Inventory Management
                    if item['prod'].stock_qty is not None:
                        item['prod'].stock_qty -= item['qty']
                        item['prod'].save()

                    artist_order_items.setdefault(item['prod'].artist, []).append(item)

                for artist, items in artist_order_items.items():
                    item_summaries = ', '.join(f"{entry['prod'].title} x{entry['qty']}" for entry in items)
                    Notification.objects.create(
                        order=order,
                        artist=artist,
                        message_text=f"New Order #BK-{order.order_id}: {item_summaries}.",
                        sender_role='Admin'
                    )

                if not buy_now_id:
                    cart_items.delete()

                return render(request, 'products/order_success.html', {'order': order})

        except Exception as e:
            print(f"CRITICAL ORDER ERROR: {e}")
            messages.error(request, str(e) if str(e) else "We couldn't place your order right now.")
            return redirect('checkout')
            
    return redirect('catalog')

@login_required
def cancel_order(request, order_id):
    order = get_object_or_404(Order, order_id=order_id, user=request.user)
    
    if order.status in ['Prepared', 'Shipped', 'Delivered']:
        messages.error(request, "Cancellation failed: admin has already prepared or shipped your order.")
        return redirect('/profile/?tab=purchases')

    # Standard cancellation logic
    if order.status in ['Processing', 'To Pay', 'Pending']:
        with transaction.atomic():
            for d in OrderDetail.objects.filter(order=order):
                if d.product.stock_qty is not None:
                    d.product.stock_qty += d.quantity
                    d.product.save()
            
            order.status = 'Cancelled'
            order.save()

            # --- NEW: DIFFERENT MESSAGE FOR ONLINE PAYMENT ---
            if order.payment and order.payment.method == "Mamaya Online Payment":
                messages.success(request, f"Order #BK-{order.order_id} cancelled. Your refund of ₱{order.total_amount} will be sent back to your Mamaya account within 6-24 hours.")
            else:
                messages.success(request, f"Order #BK-{order.order_id} has been successfully cancelled.")
            
    return redirect('/profile/?tab=purchases&status=cancelled')

@user_passes_test(lambda u: u.is_staff)
def notify_artist(request, order_id, artist_id):
    order = get_object_or_404(Order, order_id=order_id)
    artist = get_object_or_404(Artist, artist_id=artist_id)
    
    Notification.objects.create(
        order=order,
        artist=artist,
        message_text=f"New Order #BK-{order.order_id}. Please prepare the items.",
        sender_role='Admin'
    )
    _send_mock_artist_email(
        artist,
        f"Bicolikha Order #BK-{order.order_id}",
        f"New Order #BK-{order.order_id}. Please prepare the items."
    )
    messages.success(request, f"Artist {artist.artist_name} has been notified.")
    return redirect('admin_orders')

@user_passes_test(lambda u: u.is_staff, login_url='admin_login')
def artist_reply(request, notif_id, status):
    messages.error(request, "Artist replies are no longer supported. Admin controls order updates.")
    return redirect('admin_messages')

def artist_detail(request, artist_id):
    # 1. Get current artist
    artist = get_object_or_404(Artist, artist_id=artist_id)
    
    # 2. Find Next and Previous Artists (Circular loop)
    # Get all IDs in order
    all_ids = list(Artist.objects.values_list('artist_id', flat=True).order_by('artist_id'))
    curr_index = all_ids.index(artist_id)
    
    prev_id = all_ids[curr_index - 1] if curr_index > 0 else all_ids[-1]
    next_id = all_ids[curr_index + 1] if curr_index < len(all_ids) - 1 else all_ids[0]

    # 3. Get Artworks and Profile Picture
    sort_by = request.GET.get('sort', 'latest')
    selected_category = request.GET.get('category', '')

    artworks_query = Artwork.objects.filter(artist=artist).select_related('category').annotate(
        stock_order=Case(
            When(stock_qty__gt=0, then=Value(0)),
            default=Value(1),
            output_field=IntegerField()
        ),
        like_count=Count('like', distinct=True),
        sold_count=Sum('orderdetail__quantity')
    )

    if selected_category:
        artworks_query = artworks_query.filter(category_id=selected_category)

    sort_mapping = {
        'latest': '-prod_id',
        'top_sales': '-sold_count',
        'popularity': '-like_count',
        'category': 'category__category_name',
    }
    artworks = artworks_query.order_by('stock_order', sort_mapping.get(sort_by, '-prod_id'), '-prod_id')
    artworks_count = artworks.count()
    paginator = Paginator(artworks, 12)
    page_obj = paginator.get_page(request.GET.get('page'))
    artist_products_query = request.GET.copy()
    artist_products_query.pop('page', None)
    artist_products_querystring = artist_products_query.urlencode()
    artist_categories = Category.objects.filter(artwork__artist=artist).distinct().order_by('category_name')

    return render(request, 'products/artist_detail.html', {
        'artist': artist,
        'artworks': page_obj.object_list,
        'artworks_count': artworks_count,
        'page_obj': page_obj,
        'artist_products_querystring': artist_products_querystring,
        'artist_categories': artist_categories,
        'current_sort': sort_by,
        'selected_category': selected_category,
        'address': None,
        'prev_id': prev_id,
        'next_id': next_id
    })

def category_detail(request, cat_id):
    # 1. Get current category
    category = get_object_or_404(Category, category_id=cat_id)
    
    # 2. Circular Navigation Logic
    # Get all category IDs in order
    all_cat_ids = list(Category.objects.values_list('category_id', flat=True).order_by('category_id'))
    curr_index = all_cat_ids.index(cat_id)
    
    # Logic to loop back to the start/end
    prev_id = all_cat_ids[curr_index - 1] if curr_index > 0 else all_cat_ids[-1]
    next_id = all_cat_ids[curr_index + 1] if curr_index < len(all_cat_ids) - 1 else all_cat_ids[0]

    # 3. Fetch all products for this category
    artworks = Artwork.objects.filter(category=category).annotate(
        stock_order=Case(
            When(stock_qty__gt=0, then=Value(0)),
            default=Value(1),
            output_field=IntegerField()
        )
    ).order_by('stock_order', '-prod_id')
    paginator = Paginator(artworks, 12)
    page_obj = paginator.get_page(request.GET.get('page'))

    return render(request, 'products/category_detail.html', {
        'category': category,
        'artworks': page_obj.object_list,
        'page_obj': page_obj,
        'prev_id': prev_id,
        'next_id': next_id
    })

def search_results(request):
    # 1. Get Parameters
    query = (request.GET.get('q') or '').strip()
    selected_category = request.GET.get('category', '')
    sort_by = request.GET.get('sort', 'latest')

    # 2. Fetch categories for the dropdown (Mandatory for UI)
    search_categories = Category.objects.all().order_by('category_name')
    selected_category_obj = None
    if selected_category and selected_category.isdigit():
        selected_category_obj = search_categories.filter(category_id=selected_category).first()

    # 3. Base Querysets with Annotations (for popularity/sales)
    # This ensures we have the data needed to sort correctly
    artworks_query = Artwork.objects.select_related('artist', 'category').annotate(
        like_count=Count('like', distinct=True),
        sold_count=Sum('orderdetail__quantity')
    )
    artists_query = Artist.objects.all()

    # 4. STEP 1: Search Filtering (Keyword)
    if query:
        search_terms = query.split()
        artwork_filter = Q()
        artist_filter = Q()

        for term in search_terms:
            artwork_filter |= (Q(title__icontains=term) | Q(description__icontains=term) | Q(category__category_name__icontains=term))
            artist_filter |= (Q(artist_name__icontains=term) | Q(artist_municipality__icontains=term))
        
        artworks_query = artworks_query.filter(artwork_filter)
        artists_query = artists_query.filter(artist_filter)
    else:
        # If no query and no category, you might want to show nothing or all. 
        # Here we allow browsing by category even if query is empty.
        if not selected_category_obj:
            artworks_query = Artwork.objects.none()
            artists_query = Artist.objects.none()

    # 5. STEP 2: Category Filtering (Applies to the searched items)
    if selected_category_obj:
        artworks_query = artworks_query.filter(category=selected_category_obj)
        # Usually hide general artist matches when a specific category is selected
        if not query:
            artists_query = Artist.objects.none()

    # 6. STEP 3: Sorting (Applies to the filtered result)
    sort_mapping = {
        'latest': '-prod_id',
        'artist': 'artist__artist_name', # Sort products A-Z by Artist Name
        'popularity': '-like_count',
        'top_sales': '-sold_count',
    }
    
    # Execute query
    matched_artworks = artworks_query.order_by(sort_mapping.get(sort_by, '-prod_id'), '-prod_id').distinct()
    matched_artists = artists_query.distinct().order_by('artist_name')

    context = {
        'query': query,
        'artists': matched_artists,
        'artworks': matched_artworks,
        'results_count': matched_artworks.count() + matched_artists.count(),
        'search_categories': search_categories, # For the loop
        'selected_category': selected_category, # String ID for the "selected" check
        'selected_category_obj': selected_category_obj,
        'current_sort': sort_by,
        'has_search_filters': bool(query or selected_category_obj),
    }

    return render(request, 'products/search_results.html', context)


@login_required
def confirm_order_received(request, order_id):
    # Fetch the order belonging to this user
    order = get_object_or_404(Order, order_id=order_id, user=request.user)
    
    if order.status == 'Shipped':
        with transaction.atomic():
            # 1. Update Order Status
            order.status = 'Delivered'
            
            # 2. SYNC TO SHIPMENT TABLE
            if order.shipment:
                order.shipment.shipment_status = 'Arrived'
                order.shipment.save()
            
            # 3. SYNC TO PAYMENT TABLE (THE FIX)
            if order.payment:
                order.payment.status = 'Paid'
                order.payment.save()
            
            order.save()
            
    return redirect('/profile/?tab=purchases&status=completed')

@login_required
def submit_review(request):
    if request.method == 'POST':
        prod_id = request.POST.get('product_id')
        product = get_object_or_404(Artwork, prod_id=prod_id)
        
        Review.objects.create(
            user=request.user,
            product=product,
            rating=request.POST.get('rating'),
            description=request.POST.get('description'),
            image=request.FILES.get('review_image')
        )
        return redirect('/profile/?tab=purchases&status=completed')


import re

def forgot_password_request(request):
    if request.method == 'POST':
        email = request.POST.get('email', '').strip()
        # 1. Error Handling: Check if email exists
        if not User.objects.filter(email=email).exists():
            messages.error(request, "This email address is not registered in our system.")
        else:
            request.session['reset_email'] = email
            return redirect('forgot_password_verify')
            
    return render(request, 'registration/forgot_password_request.html')

def forgot_password_verify(request):
    if 'reset_email' not in request.session:
        return redirect('forgot_password_request')
        
    if request.method == 'POST':
        code = request.POST.get('code', '').strip()
        
        # 2. Error Handling: Check if input is numeric and 6 digits
        if not code.isdigit():
            messages.error(request, "Invalid input. Please enter numbers only.")
        elif len(code) != 6:
            messages.error(request, "Please enter the full 6-digit code.")
        else:
            request.session['code_verified'] = True
            return redirect('forgot_password_reset')
            
    return render(request, 'registration/forgot_password_verify.html', {
        'email': request.session['reset_email']
    })

def forgot_password_reset(request):
    if not request.session.get('code_verified'):
        return redirect('forgot_password_request')

    if request.method == 'POST':
        new_pw = request.POST.get('password')
        confirm_pw = request.POST.get('confirm_password')
        
        # 3. Error Handling: Password Strength Validation
        val_errors = []
        if len(new_pw) < 8:
            val_errors.append("Minimum 8 characters required.")
        if not re.search(r'[A-Z]', new_pw):
            val_errors.append("Must include at least one capital letter.")
        if not re.search(r'[0-9]', new_pw):
            val_errors.append("Must include at least one number.")
        if new_pw != confirm_pw:
            val_errors.append("Passwords do not match.")

        if val_errors:
            for error in val_errors:
                messages.error(request, error)
        else:
            # Success logic
            email = request.session.get('reset_email')
            user = User.objects.get(email=email)
            user.set_password(new_pw)
            user.save()
            
            del request.session['reset_email']
            del request.session['code_verified']
            
            messages.success(request, "Password updated! You can now log in.")
            return redirect('login')

    return render(request, 'registration/forgot_password_reset.html')
