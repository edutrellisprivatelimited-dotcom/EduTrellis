from django.contrib.auth.models import User
from django.db import models


class ContactLead(models.Model):
    """Persists every contact / lead-form submission.

    Saving to the database happens *before* the email is attempted, so
    no inquiry is ever lost even if SMTP is unavailable.
    """
    name       = models.CharField(max_length=120)
    phone      = models.CharField(max_length=20)
    email      = models.EmailField()
    service    = models.CharField(max_length=200, blank=True)
    message    = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name      = 'Contact Lead'
        verbose_name_plural = 'Contact Leads'

    def __str__(self):
        return f"{self.name} — {self.phone} ({self.created_at:%d %b %Y %H:%M})"


class StoreProfile(models.Model):
    """Extra store-specific fields for a Django auth User (E-Store signups)."""
    user           = models.OneToOneField(User, on_delete=models.CASCADE, related_name='store_profile')
    phone          = models.CharField(max_length=20, blank=True)
    avatar         = models.ImageField(upload_to='avatars/', blank=True, null=True)
    wallet_balance = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    class Meta:
        verbose_name = 'Store Customer Profile'
        verbose_name_plural = 'Store Customer Profiles'

    def __str__(self):
        return f"{self.user.get_full_name() or self.user.username} ({self.phone})"


class Category(models.Model):
    """A storefront category shown on the homepage's 'Shop by Category' rail
    and used as a filter tab on the shop grid. Replaces the old hardcoded
    icon-based categories with an admin-managed list backed by an image."""
    name        = models.CharField(max_length=80)
    slug        = models.SlugField(max_length=80, unique=True, help_text="Used to match product filter tags, e.g. 'audio'.")
    description = models.CharField(max_length=200, blank=True)
    image       = models.ImageField(upload_to='categories/', blank=True, null=True)
    order       = models.PositiveIntegerField(default=0)
    is_active   = models.BooleanField(default=True)
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['order', 'name']
        verbose_name = 'Store Category'
        verbose_name_plural = 'Store Categories'

    def __str__(self):
        return self.name


class Cart(models.Model):
    """A shopping cart tied to a logged-in store user or an anonymous session."""
    user        = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True, related_name='carts')
    session_key = models.CharField(max_length=40, blank=True, db_index=True)
    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Store Cart'
        verbose_name_plural = 'Store Carts'

    def __str__(self):
        owner = self.user.username if self.user else f"session:{self.session_key[:8]}"
        return f"Cart #{self.pk} — {owner}"


class CartItem(models.Model):
    """A single product line inside a Cart. Product data is snapshotted here
    since the storefront catalogue lives in the template, not the database."""
    cart         = models.ForeignKey(Cart, on_delete=models.CASCADE, related_name='items')
    product_id   = models.CharField(max_length=40)
    product_name = models.CharField(max_length=200)
    price        = models.DecimalField(max_digits=10, decimal_places=2)
    quantity     = models.PositiveIntegerField(default=1)
    added_at     = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('cart', 'product_id')
        verbose_name = 'Cart Item'
        verbose_name_plural = 'Cart Items'

    def __str__(self):
        return f"{self.product_name} x{self.quantity}"

    @property
    def subtotal(self):
        return self.price * self.quantity


# Product id (matches PRODUCTS in estore.html) whose first delivered order
# triggers the ₹100 wallet-credit welcome offer.
WALLET_OFFER_PRODUCT_ID = 'aud-metal'
WALLET_OFFER_CREDIT = 100


class Order(models.Model):
    """A placed order, created from the cart at checkout. Product data is
    snapshotted onto OrderItem the same way CartItem snapshots it, since the
    catalogue lives in the template, not the database."""
    STATUS_PLACED     = 'placed'
    STATUS_PROCESSING = 'processing'
    STATUS_SHIPPED    = 'shipped'
    STATUS_DELIVERED  = 'delivered'
    STATUS_CANCELLED  = 'cancelled'
    STATUS_CHOICES = [
        (STATUS_PLACED, 'Placed'),
        (STATUS_PROCESSING, 'Processing'),
        (STATUS_SHIPPED, 'Shipped'),
        (STATUS_DELIVERED, 'Delivered'),
        (STATUS_CANCELLED, 'Cancelled'),
    ]

    user                   = models.ForeignKey(User, on_delete=models.CASCADE, related_name='orders')
    status                 = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PLACED)
    subtotal               = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    wallet_discount        = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    shipping_fee           = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total                  = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    wallet_credit_applied  = models.BooleanField(default=False)
    created_at             = models.DateTimeField(auto_now_add=True)
    updated_at             = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Store Order'
        verbose_name_plural = 'Store Orders'

    def __str__(self):
        return f"Order #{self.pk} — {self.user.username} ({self.get_status_display()})"

    def maybe_credit_wallet(self):
        """Credits the ₹100 welcome offer once this order is Delivered, if
        it's the customer's first order and contains the Metal Bluetooth
        Speaker. Idempotent via wallet_credit_applied."""
        if self.wallet_credit_applied or self.status != self.STATUS_DELIVERED:
            return
        is_first_order = not Order.objects.filter(user=self.user).exclude(pk=self.pk).exists()
        has_offer_product = self.items.filter(product_id=WALLET_OFFER_PRODUCT_ID).exists()
        if is_first_order and has_offer_product:
            profile, _ = StoreProfile.objects.get_or_create(user=self.user)
            profile.wallet_balance += WALLET_OFFER_CREDIT
            profile.save(update_fields=['wallet_balance'])
        self.wallet_credit_applied = True
        self.save(update_fields=['wallet_credit_applied'])


class OrderItem(models.Model):
    order        = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items')
    product_id   = models.CharField(max_length=40)
    product_name = models.CharField(max_length=200)
    price        = models.DecimalField(max_digits=10, decimal_places=2)
    quantity     = models.PositiveIntegerField(default=1)

    class Meta:
        verbose_name = 'Order Item'
        verbose_name_plural = 'Order Items'

    def __str__(self):
        return f"{self.product_name} x{self.quantity}"

    @property
    def subtotal(self):
        return self.price * self.quantity
