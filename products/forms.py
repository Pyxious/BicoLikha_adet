import re

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm

from .models import Artwork, Category, Artist, Address, PopularAd

User = get_user_model()

# --- CUSTOM SIGNUP FORM ---

class CustomerAuthenticationForm(AuthenticationForm):
    error_messages = {
        'invalid_login': "We couldn't sign you in with that email or phone number and password.",
        'inactive': "This account is currently inactive.",
    }

    def confirm_login_allowed(self, user):
        if user.is_staff:
            raise forms.ValidationError(
                self.error_messages['invalid_login'],
                code='invalid_login',
            )
        super().confirm_login_allowed(user)

class AdminAuthenticationForm(AuthenticationForm):
    error_messages = {
        'invalid_login': "That admin email and password combination wasn't recognized.",
        'inactive': "This account is currently inactive.",
    }

    def confirm_login_allowed(self, user):
        if not user.is_staff:
            raise forms.ValidationError(
                "Access Denied: You do not have administrative privileges.",
                code='invalid_login',
            )
        super().confirm_login_allowed(user)
        
class BicolikhaSignupForm(forms.ModelForm):
    first_name = forms.CharField(max_length=30, required=True, widget=forms.TextInput(attrs={'class': 'bicol-input'}))
    last_name = forms.CharField(max_length=30, required=True, widget=forms.TextInput(attrs={'class': 'bicol-input'}))
    phone_number = forms.CharField(max_length=15, required=True, widget=forms.TextInput(attrs={'class': 'bicol-input', 'placeholder': '09xxxxxxxxx'}))
    password = forms.CharField(widget=forms.PasswordInput(attrs={'class': 'bicol-input'}))
    email = forms.EmailField(widget=forms.EmailInput(attrs={'class': 'bicol-input'}))
    agree_policy = forms.BooleanField(required=True)

    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'email', 'phone_number', 'password']

    def clean_email(self):
        email = (self.cleaned_data.get('email') or '').strip().lower()

        if User.objects.filter(email__iexact=email).exists() or User.objects.filter(username__iexact=email).exists():
            raise forms.ValidationError("This email address is already registered.")

        return email

    def clean_phone_number(self):
        phone = re.sub(r'\D', '', self.cleaned_data.get('phone_number') or '')

        if len(phone) != 11:
            raise forms.ValidationError("Phone number must be exactly 11 digits.")

        if Address.objects.filter(phone_num=phone).exists():
            raise forms.ValidationError("This phone number is already registered.")
        if User.objects.filter(phone_number=phone).exists():
            raise forms.ValidationError("This phone number is already registered.")

        return phone

    def clean_password(self):
        password = self.cleaned_data.get('password') or ''

        if len(password) < 8:
            raise forms.ValidationError("Password must be at least 8 characters long.")
        if not re.search(r'[A-Z]', password):
            raise forms.ValidationError("Password must include at least 1 uppercase letter.")
        if not re.search(r'\d', password):
            raise forms.ValidationError("Password must include at least 1 number.")

        return password

# --- ADMIN FORMS ---
class CategoryForm(forms.ModelForm):
    class Meta:
        model = Category
        fields = ['category_name', 'category_desc']

class ProductForm(forms.ModelForm):
    class Meta:
        model = Artwork
        fields = ['title', 'description', 'price', 'category', 'artist', 'stock_qty', 'image']
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'price': forms.NumberInput(attrs={'class': 'form-control'}),
            'category': forms.Select(attrs={'class': 'form-select'}),
            'artist': forms.Select(attrs={'class': 'form-select'}),
            'stock_qty': forms.NumberInput(attrs={'class': 'form-control'}),
            'image': forms.FileInput(attrs={'class': 'form-control'}),
        }

class PopularAdForm(forms.ModelForm):
    class Meta:
        model = PopularAd
        fields = ['title', 'image', 'display_order', 'is_active']
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Optional ad title'}),
            'image': forms.FileInput(attrs={'class': 'form-control', 'accept': 'image/*'}),
            'display_order': forms.NumberInput(attrs={'class': 'form-control', 'min': 0}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }
