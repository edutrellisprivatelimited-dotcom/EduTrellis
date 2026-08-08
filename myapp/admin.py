from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import User

from .models import ContactLead, StoreProfile, Cart, CartItem, Category, Order, OrderItem


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'order', 'is_active', 'created_at')
    list_editable = ('order', 'is_active')
    search_fields = ('name', 'slug')
    prepopulated_fields = {'slug': ('name',)}


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
