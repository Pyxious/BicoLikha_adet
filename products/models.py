import os

from django.db import models
from django.conf import settings
from django.utils.text import slugify

# --- 1. CATEGORY & ARTIST ---

class Category(models.Model):
    category_id = models.AutoField(primary_key=True, db_column='CATEGORY_ID')
    category_name = models.CharField(max_length=100, db_column='CATEGORY_NAME', null=True)
    category_desc = models.TextField(db_column='CATEGORY_DESC', null=True, blank=True)


    class Meta:
        db_table = 'category'
    def __str__(self): return self.category_name or "Unnamed Category"

class Artist(models.Model):
    artist_id = models.AutoField(primary_key=True, db_column='ARTIST_ID')
    artist_name = models.CharField(max_length=255, db_column='ARTIST_NAME', null=True)
    artist_email = models.EmailField(db_column='ARTIST_EMAIL', null=True, blank=True)
    artist_phone_num = models.CharField(max_length=20, db_column='ARTIST_PHONE_NUM', null=True)
    artist_description = models.TextField(db_column='ARTIST_DESCRIPTION', null=True)
    artist_municipality = models.CharField(max_length=100, db_column='ARTIST_MUNICIPALITY', null=True)
    artist_brgy = models.CharField(max_length=100, db_column='ARTIST_BRGY', null=True)
    artist_zipcode = models.CharField(max_length=10, db_column='ARTIST_ZIPCODE', null=True)
    artist_image = models.CharField(max_length=255, db_column='ARTIST_IMAGE', null=True) # Matches SQL varchar
   
    

    class Meta:
        db_table = 'artist'

    @property
    def artist_image_url(self):
        return f'{settings.MEDIA_URL}{self.artist_image}' if self.artist_image else ''

    def __str__(self): return self.artist_name or "Unknown Artist"

# --- 2. USER EXTENSIONS (Address & Profile Logic) ---

class Address(models.Model):
    address_id = models.AutoField(primary_key=True, db_column='ADDRESS_ID')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, db_column='USER_ID', null=True)
    address_type = models.CharField(max_length=50, db_column='ADDRESS_TYPE', null=True)
    phone_num = models.CharField(max_length=20, db_column='ADDRESS_PHONE_NUM', null=True)
    house_num = models.CharField(max_length=20, db_column='ADDRESS_HOUSE_NUM', null=True)
    street = models.CharField(max_length=100, db_column='ADDRESS_STREET', null=True)
    municipality = models.CharField(max_length=100, db_column='ADDRESS_MUNICIPALITY', null=True)
    brgy = models.CharField(max_length=100, db_column='ADDRESS_BRGY', null=True)
    zipcode = models.CharField(max_length=10, db_column='CUST_ZIPCODE', null=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, db_column='LATITUDE', null=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, db_column='LONGITUDE', null=True)
    profile_pix = models.ImageField(upload_to='profile_pics/', db_column='PROFILE_PIX', null=True, blank=True)
    is_default = models.BooleanField(default=False)

    class Meta:
        db_table = 'address'

# --- 3. PRODUCTS & CART ---


def artwork_image_upload_to(instance, filename):
    _, ext = os.path.splitext(filename)
    category_name = (instance.category.category_name if instance.category else '') or 'uncategorized'
    category_slug = slugify(category_name) or 'uncategorized'
    title_slug = slugify(instance.title or os.path.splitext(filename)[0]) or 'artwork'

    return f'artwork_pics/{category_slug}/{title_slug}{ext.lower()}'

class Artwork(models.Model):
    prod_id = models.AutoField(primary_key=True, db_column='PROD_ID')
    artist = models.ForeignKey(Artist, on_delete=models.CASCADE, db_column='ARTIST_ID', null=True)
    category = models.ForeignKey(Category, on_delete=models.CASCADE, db_column='CATEGORY_ID', null=True)
    title = models.CharField(max_length=255, db_column='PROD_NAME', null=True)
    description = models.TextField(db_column='PROD_DESCRIPTION', null=True)
    price = models.DecimalField(max_digits=10, decimal_places=2, db_column='PROD_PRICE', null=True)
    stock_qty = models.IntegerField(db_column='PROD_STOCK_QTY', null=True)
    image = models.ImageField(upload_to=artwork_image_upload_to, db_column='PROD_IMAGE', null=True, blank=True)
    

    class Meta:
        db_table = 'product'
    def __str__(self): return self.title or "Untitled"

class PopularAd(models.Model):
    ad_id = models.AutoField(primary_key=True, db_column='AD_ID')
    title = models.CharField(max_length=255, db_column='AD_TITLE', null=True, blank=True)
    image = models.ImageField(upload_to='popular_ads/', db_column='AD_IMAGE')
    is_active = models.BooleanField(default=True, db_column='IS_ACTIVE')
    display_order = models.PositiveIntegerField(default=0, db_column='DISPLAY_ORDER')
    created_at = models.DateTimeField(auto_now_add=True, db_column='CREATED_AT')

    class Meta:
        db_table = 'popular_ads'
        ordering = ['display_order', '-created_at']

    def __str__(self):
        return self.title or f"Popular ad {self.ad_id}"

    def delete(self, *args, **kwargs):
        image = self.image
        super().delete(*args, **kwargs)
        if image:
            image.delete(save=False)

class SupplyInventory(models.Model):
    supply_id = models.AutoField(primary_key=True, db_column='SUPPLY_ID')
    product = models.ForeignKey(Artwork, on_delete=models.CASCADE, db_column='PROD_ID')
    supplied_date = models.DateTimeField(auto_now_add=True, db_column='SUPPLIED_DATE')
    supplied_qty = models.IntegerField(db_column='SUPPLIED_QTY')

    class Meta:
        db_table = 'supply_inventory'

class ArtistApplication(models.Model):
    application_id = models.AutoField(primary_key=True, db_column='APPLICATION_ID')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, db_column='USER_ID', null=True, blank=True)
    applicant_name = models.CharField(max_length=255, db_column='APPLICANT_NAME', null=True, blank=True)
    applicant_email = models.EmailField(db_column='APPLICANT_EMAIL', null=True, blank=True)
    applicant_phone = models.CharField(max_length=20, db_column='APPLICANT_PHONE', null=True, blank=True)
    artist_name = models.CharField(max_length=255, db_column='ARTIST_NAME')
    artist_image = models.CharField(max_length=255, db_column='ARTIST_IMAGE', null=True, blank=True)
    artist_description = models.TextField(db_column='ARTIST_DESCRIPTION', null=True, blank=True)
    artist_municipality = models.CharField(max_length=100, db_column='ARTIST_MUNICIPALITY', null=True, blank=True)
    artist_brgy = models.CharField(max_length=100, db_column='ARTIST_BRGY', null=True, blank=True)
    artist_zipcode = models.CharField(max_length=10, db_column='ARTIST_ZIPCODE', null=True, blank=True)
    application_status = models.CharField(max_length=50, db_column='APPLICATION_STATUS', default='Pending')
    date_submitted = models.DateTimeField(auto_now_add=True, db_column='DATE_SUBMITTED')
    date_reviewed = models.DateTimeField(null=True, blank=True, db_column='DATE_REVIEWED')

    class Meta:
        db_table = 'artist_application'

    @property
    def artist_image_url(self):
        return f'{settings.MEDIA_URL}{self.artist_image}' if self.artist_image else ''

    @property
    def applicant_display_name(self):
        if self.applicant_name:
            return self.applicant_name
        if self.user:
            return self.user.get_full_name() or self.user.username
        return 'Guest applicant'

    @property
    def applicant_display_email(self):
        if self.applicant_email:
            return self.applicant_email
        if self.user:
            return self.user.email
        return ''

class ArtistApplicationProduct(models.Model):
    application_product_id = models.AutoField(primary_key=True, db_column='APPLICATION_PRODUCT_ID')
    application = models.ForeignKey(ArtistApplication, on_delete=models.CASCADE, db_column='APPLICATION_ID', related_name='products')
    category = models.ForeignKey(Category, on_delete=models.CASCADE, db_column='CATEGORY_ID')
    product_name = models.CharField(max_length=255, db_column='PROD_NAME')
    product_description = models.TextField(db_column='PROD_DESCRIPTION', null=True, blank=True)
    product_price = models.DecimalField(max_digits=10, decimal_places=2, db_column='PROD_PRICE')
    product_stock_qty = models.IntegerField(db_column='PROD_STOCK_QTY', default=0)
    product_image = models.CharField(max_length=255, db_column='PROD_IMAGE', null=True, blank=True)

    class Meta:
        db_table = 'artist_application_products'


class Cart(models.Model):
    cart_id = models.AutoField(primary_key=True, db_column='CART_ID')
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, db_column='USER_ID', null=True)
    total_items = models.IntegerField(db_column='TOTAL_ITEMS', default=0)
    date_created = models.DateTimeField(auto_now_add=True, db_column='DATE_CREATED')

    class Meta:
        db_table = 'cart'

class CartItem(models.Model):
    id = models.AutoField(primary_key=True) # From the previous fix
    cart = models.ForeignKey(Cart, on_delete=models.CASCADE, db_column='CART_ID')
    product = models.ForeignKey(Artwork, on_delete=models.CASCADE, db_column='PRODUCT_ID')
    quantity = models.IntegerField(db_column='QUANTITY', default=1)
    is_selected = models.BooleanField(default=True) # This matches the SQL we just added
    
    class Meta: 
        db_table = 'cart_items'
        unique_together = (('cart', 'product'),)

    @property
    def get_subtotal(self):
        return self.product.price * self.quantity

# --- 4. ORDERS & PAYMENTS ---

class Payment(models.Model):
    payment_id = models.AutoField(primary_key=True, db_column='PAYMENT_ID')
    method = models.CharField(max_length=50, db_column='PAYMENT_METHOD', null=True)
    status = models.CharField(max_length=50, db_column='PAYMENT_STATUS', null=True)
    timestamp = models.DateTimeField(auto_now_add=True, db_column='PAYMENT_TIMESTAMP')

    class Meta:
        db_table = 'payment'

class Shipment(models.Model):
    shipment_id = models.AutoField(primary_key=True, db_column='SHIPMENT_ID')
    address = models.ForeignKey(Address, on_delete=models.SET_NULL, null=True, db_column='ADDRESS_ID')
    shipment_date = models.DateField(null=True, blank=True, db_column='SHIPMENT_DATE')
    shipment_company = models.CharField(max_length=100, null=True, blank=True, db_column='SHIPMENT_COMPANY', default="Bicol Express Courier")
    shipment_status = models.CharField(max_length=50, db_column='SHIPMENT_STATUS', default='Pending')

    class Meta:
        db_table = 'shipment'

class Order(models.Model):
    order_id = models.AutoField(primary_key=True, db_column='ORDER_ID')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, db_column='USER_ID', null=True)
    payment = models.OneToOneField(Payment, on_delete=models.SET_NULL, null=True, db_column='PAYMENT_ID')
    # UPDATED: Link to the Shipment model instead of just an Integer
    shipment = models.OneToOneField(Shipment, on_delete=models.SET_NULL, null=True, db_column='SHIPMENT_ID')
    created_at = models.DateTimeField(db_column='ORDER_CREATED_AT', auto_now_add=True)
    total_qty = models.IntegerField(db_column='ORDER_TOTAL_QUANTITY', null=True)
    delivery_fee = models.DecimalField(max_digits=10, decimal_places=2, db_column='ORDER_DELIVERY_FEE', null=True)
    total_amount = models.DecimalField(max_digits=10, decimal_places=2, db_column='ORDER_TOTAL_AMOUNT', null=True)
    status = models.CharField(max_length=50, db_column='ORDER_STATUS', null=True)

    class Meta:
        db_table = 'orders'

class OrderDetail(models.Model):
    # ADD THIS LINE:
    id = models.AutoField(primary_key=True) 
    
    order = models.ForeignKey(Order, on_delete=models.CASCADE, db_column='ORDER_ID')
    product = models.ForeignKey(Artwork, on_delete=models.CASCADE, db_column='PROD_ID')
    price = models.DecimalField(max_digits=10, decimal_places=2, db_column='PRICE', null=True)
    quantity = models.IntegerField(db_column='QUANTITY', null=True)
    subtotal = models.DecimalField(max_digits=10, decimal_places=2, db_column='SUBTOTAL', null=True)
    item_status = models.CharField(max_length=50, db_column='ITEM_STATUS', default='Pending')

    class Meta: 
        db_table = 'order_details'
        unique_together = (('order', 'product'),)
        
    # Helper for templates
    @property
    def get_subtotal(self):
        return self.price * self.quantity
    
class Notification(models.Model):
    # This must match your SQL table 'notifications'
    order = models.ForeignKey('Order', on_delete=models.CASCADE)
    artist = models.ForeignKey('Artist', on_delete=models.CASCADE)
    message_text = models.TextField()
    sender_role = models.CharField(max_length=50) # 'Admin' or 'Artist'
    status_update = models.CharField(max_length=50, null=True, blank=True)
    is_read = models.BooleanField(default=False)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'notifications'

# --- 5. SOCIAL & REVIEWS ---

class Review(models.Model):
    review_id = models.AutoField(primary_key=True, db_column='REVIEW_ID')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, db_column='USER_ID')
    product = models.ForeignKey(Artwork, on_delete=models.CASCADE, db_column='PRODUCT_ID')
    rating = models.IntegerField(db_column='REVIEW_RATING')
    description = models.TextField(db_column='REVIEW_DESCRIPTION', null=True, blank=True)
    image = models.ImageField(upload_to='reviews/', db_column='REVIEW_IMAGE', null=True, blank=True)
    date_created = models.DateTimeField(auto_now_add=True, db_column='DATE_CREATED')

    class Meta:
        db_table = 'review'

class Like(models.Model):
    like_id = models.AutoField(primary_key=True, db_column='LIKE_ID')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, db_column='USER_ID', null=True)
    product = models.ForeignKey(Artwork, on_delete=models.CASCADE, db_column='PRODUCT_ID', null=True)
    date_liked = models.DateTimeField(auto_now_add=True, db_column='DATE_LIKED')

    class Meta:
        db_table = 'likes'


class AuditLog(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    action = models.TextField()
    ip_address = models.GenericIPAddressField(null=True)
    timestamp = models.DateTimeField(auto_now_add=True)
    class Meta: 
        db_table = 'audit_logs'
