from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import User

from .models import (
    ContactLead, StoreProfile, Cart, CartItem, Category, Order, OrderItem,
    Product, ProductImage, ProductColor, AboutUsContent, PolicyPage, PaymentSettings, Payment,
    DropboxSettings, Review, EmailVerification, PWASettings,
)


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'order', 'is_active', 'created_at')
    list_editable = ('order', 'is_active')
    search_fields = ('name', 'slug')
    prepopulated_fields = {'slug': ('name',)}


class ProductImageInline(admin.TabularInline):
    model = ProductImage
    extra = 1
    max_num = 5


class ProductColorInline(admin.TabularInline):
    model = ProductColor
    extra = 1


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('name', 'brand', 'category', 'price', 'mrp', 'stock_status', 'is_active', 'order')
    list_editable = ('price', 'mrp', 'is_active', 'order')
    list_filter = ('category', 'is_active', 'brand')
    search_fields = ('name', 'brand', 'slug', 'tags')
    prepopulated_fields = {'slug': ('name',)}
    inlines = [ProductImageInline, ProductColorInline]


@admin.register(AboutUsContent)
class AboutUsContentAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'founder_name', 'updated_at')

    def has_add_permission(self, request):
        return not AboutUsContent.objects.exists()


@admin.register(PolicyPage)
class PolicyPageAdmin(admin.ModelAdmin):
    list_display = ('title', 'key', 'updated_at')

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(PaymentSettings)
class PaymentSettingsAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'is_razorpay_enabled', 'is_test_mode', 'cod_enabled', 'updated_at')

    def has_add_permission(self, request):
        return not PaymentSettings.objects.exists()


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ('id', 'order', 'method', 'status', 'amount', 'created_at')
    list_filter = ('method', 'status')


@admin.register(DropboxSettings)
class DropboxSettingsAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'is_configured', 'updated_at')

    def has_add_permission(self, request):
        return not DropboxSettings.objects.exists()
    search_fields = ('order__id', 'order__user__username', 'razorpay_order_id', 'razorpay_payment_id')


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ('product', 'user', 'rating', 'created_at')
    list_filter = ('rating', 'created_at')
    search_fields = ('product__name', 'user__username', 'user__email', 'comment')


@admin.register(PWASettings)
class PWASettingsAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'is_enabled', 'app_name', 'updated_at')

    def has_add_permission(self, request):
        return not PWASettings.objects.exists()


@admin.register(EmailVerification)
class EmailVerificationAdmin(admin.ModelAdmin):
    list_display = ('user', 'attempts', 'created_at', 'expires_at')
    search_fields = ('user__username', 'user__email')


@admin.register(ContactLead)
class ContactLeadAdmin(admin.ModelAdmin):
    list_display = ('name', 'phone', 'email', 'service', 'created_at')
    list_filter = ('service', 'created_at')
    search_fields = ('name', 'phone', 'email', 'message')
    ordering = ('-created_at',)


class CartItemInline(admin.TabularInline):
    model = CartItem
    extra = 0
    readonly_fields = ('product_id', 'product_name', 'price', 'quantity', 'added_at')
    can_delete = False


@admin.register(Cart)
class CartAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'session_key', 'item_count', 'updated_at')
    search_fields = ('user__username', 'user__email', 'session_key')
    inlines = [CartItemInline]

    def item_count(self, obj):
        return obj.items.count()
    item_count.short_description = 'Items'


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    readonly_fields = ('product_id', 'product_name', 'price', 'quantity')
    can_delete = False


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'status', 'total', 'wallet_credit_applied', 'created_at')
    list_filter = ('status', 'wallet_credit_applied')
    search_fields = ('user__username', 'user__email')
    inlines = [OrderItemInline]

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        obj.maybe_credit_wallet()


class StoreProfileInline(admin.StackedInline):
    model = StoreProfile
    can_delete = False
    verbose_name_plural = 'Store Profile'


class StoreUserAdmin(UserAdmin):
    inlines = [StoreProfileInline]
    list_display = UserAdmin.list_display + ('store_phone',)

    def store_phone(self, obj):
        return getattr(obj.store_profile, 'phone', '')
    store_phone.short_description = 'Phone'


admin.site.unregister(User)
admin.site.register(User, StoreUserAdmin)
