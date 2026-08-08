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


class Product(models.Model):
    """A storefront product. Replaces the old hardcoded PRODUCTS array in
    estore.html with an admin-managed catalogue backed by the database."""
    category          = models.ForeignKey(Category, on_delete=models.CASCADE, related_name='products')
    slug              = models.SlugField(max_length=40, unique=True, help_text="Used as the product ID in the cart/orders — keep it stable once orders exist.")
    brand             = models.CharField(max_length=80)
    name              = models.CharField(max_length=200)
    short_description = models.CharField(max_length=300, help_text="Shown on the product card.")
    description       = models.TextField(blank=True, help_text="Longer description shown when a shopper opens the product detail view.")
    specs             = models.TextField(blank=True, help_text="One spec per line, formatted as 'Label: Value' — shown on the product detail view.")
    price             = models.DecimalField(max_digits=10, decimal_places=2)
    mrp               = models.DecimalField(max_digits=10, decimal_places=2)
    image             = models.ImageField(upload_to='products/', blank=True, null=True, help_text="Cover image. Falls back to the icon + gradient tile below when left blank. Add more angles under 'Product images' below (up to 5 total).")
    video             = models.FileField(upload_to='products/videos/', blank=True, null=True, help_text="Optional MP4 product video, shown as a slide in the detail page gallery.")
    icon              = models.CharField(max_length=60, default='fa-box', help_text="Font Awesome icon class shown when no image is set, e.g. 'fa-headphones'.")
    gradient          = models.CharField(max_length=200, default='linear-gradient(135deg,#e8001e,#c0001a)', help_text="CSS background used behind the icon when no image is set.")
    flag              = models.CharField(max_length=40, blank=True, help_text="Small badge on the card, e.g. 'Bestseller'.")
    stock_status      = models.CharField(max_length=40, default='In stock', help_text="e.g. 'In stock', 'Only 4 left'.")
    tags              = models.CharField(max_length=200, blank=True, help_text="Comma-separated, e.g. 'ANC, 40h battery, IPX5'.")
    rating            = models.DecimalField(max_digits=2, decimal_places=1, default=4.5)
    reviews_count     = models.PositiveIntegerField(default=0)
    is_active         = models.BooleanField(default=True)
    order             = models.PositiveIntegerField(default=0)
    created_at        = models.DateTimeField(auto_now_add=True)
    updated_at        = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['order', 'name']
        verbose_name = 'Store Product'
        verbose_name_plural = 'Store Products'

    def __str__(self):
        return self.name

    @property
    def tag_list(self):
        return [t.strip() for t in self.tags.split(',') if t.strip()]

    @property
    def spec_list(self):
        items = []
        for line in self.specs.splitlines():
            label, sep, value = line.partition(':')
            if not label.strip():
                continue
            items.append((label.strip(), value.strip() if sep else ''))
        return items

    @property
    def discount_pct(self):
        if not self.mrp:
            return 0
        return round((1 - float(self.price) / float(self.mrp)) * 100)

class ProductImage(models.Model):
    """One extra gallery photo for a Product's detail-page slider. Capped at
    5 per product by the admin form (ProductImageFormSet)."""
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='images')
    image   = models.ImageField(upload_to='products/gallery/')
    order   = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['order', 'id']
        verbose_name = 'Product Image'
        verbose_name_plural = 'Product Images'

    def __str__(self):
        return f"Image for {self.product.name}"


class ProductColor(models.Model):
    """A selectable colour variant shown as a swatch on the product detail
    page. Purely presentational — it doesn't split stock or pricing."""
    product   = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='colors')
    name      = models.CharField(max_length=60, help_text="e.g. 'Midnight Black'.")
    hex_code  = models.CharField(max_length=7, default='#1c2333', help_text="e.g. #1c2333 — used for the swatch colour.")
    image     = models.ImageField(upload_to='products/colors/', blank=True, null=True, help_text="Optional — the gallery switches to this image when the shopper picks this colour.")
    order     = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['order', 'id']
        verbose_name = 'Product Color'
        verbose_name_plural = 'Product Colors'

    def __str__(self):
        return f"{self.name} ({self.product.name})"


class AboutUsContent(models.Model):
    """Singleton content block backing the storefront's About Us section."""
    photo          = models.ImageField(upload_to='about/', blank=True, null=True)
    badge_title    = models.CharField(max_length=120, default='Working since 2020')
    badge_subtitle = models.CharField(max_length=200, default='Websites & technical services · store launched 2026')

    founder_name     = models.CharField(max_length=120, default='Vijay Tiwari')
    founder_title    = models.CharField(max_length=120, default='Founder & CEO')
    founder_email    = models.EmailField(default='ceo@edutrellis.in')
    founder_linkedin = models.URLField(blank=True, default='https://www.linkedin.com/in/vijaytiwariii/')
    founder_photo    = models.ImageField(upload_to='about/', blank=True, null=True)

    stat1_value = models.CharField(max_length=20, default='2020')
    stat1_label = models.CharField(max_length=40, default='Founded')
    stat2_value = models.CharField(max_length=20, default='1200+')
    stat2_label = models.CharField(max_length=40, default='Clients')
    stat3_value = models.CharField(max_length=20, default='500+')
    stat3_label = models.CharField(max_length=40, default='Projects')
    stat4_value = models.CharField(max_length=20, default='98%')
    stat4_label = models.CharField(max_length=40, default='Satisfaction')

    heading    = models.CharField(max_length=200, default='A gadget store run by a tech company')
    paragraph1 = models.TextField(default=(
        "EduTrellis Private Limited has been working since 2020 — building and selling websites, "
        "and running the technical services around them: hosting, SEO, digital marketing and Google "
        "Business, for clients across India from our base in Lucknow."
    ))
    paragraph2 = models.TextField(default=(
        "Along the way we bought a lot of gear for our own team and for clients, and got tired of spec "
        "sheets that didn't match reality. So this year we launched the store. Everything listed here is "
        "stock we keep, unbox and test before it ships, sold at a fixed price."
    ))

    list_heading   = models.CharField(max_length=150, default='What you get with every order')
    bullet_points  = models.TextField(default=(
        "Sealed, genuine units, tested before dispatch\n"
        "Specs listed honestly — real battery and charging numbers\n"
        "Dispatch within 24 hours, tracking sent on WhatsApp\n"
        "GST invoice on request for business purchases\n"
        "A human who actually answers your messages"
    ), help_text="One point per line.")

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'About Us Content'
        verbose_name_plural = 'About Us Content'

    def __str__(self):
        return 'About Us content'

    @property
    def bullet_list(self):
        return [b.strip() for b in self.bullet_points.splitlines() if b.strip()]

    @classmethod
    def get_solo(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class PolicyPage(models.Model):
    """Admin-editable legal/policy pages linked from the storefront footer."""
    PRIVACY  = 'privacy'
    TERMS    = 'terms'
    REFUND   = 'refund'
    SHIPPING = 'shipping'
    KEY_CHOICES = [
        (PRIVACY, 'Privacy Policy'),
        (TERMS, 'Terms & Conditions'),
        (REFUND, 'Refund Policy'),
        (SHIPPING, 'Shipping & Delivery'),
    ]
    key        = models.CharField(max_length=20, choices=KEY_CHOICES, unique=True)
    title      = models.CharField(max_length=150)
    content    = models.TextField(help_text="Plain text — a blank line starts a new paragraph.")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['key']
        verbose_name = 'Policy Page'
        verbose_name_plural = 'Policy Pages'

    def __str__(self):
        return self.title

    @property
    def paragraphs(self):
        return [p.strip() for p in self.content.split('\n\n') if p.strip()]


class PaymentSettings(models.Model):
    """Singleton Razorpay configuration, managed from the store dashboard."""
    razorpay_key_id     = models.CharField(max_length=100, blank=True)
    razorpay_key_secret = models.CharField(max_length=100, blank=True)
    is_razorpay_enabled = models.BooleanField(default=False)
    is_test_mode        = models.BooleanField(default=True)
    cod_enabled         = models.BooleanField(default=True)
    updated_at          = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Payment Settings'
        verbose_name_plural = 'Payment Settings'

    def __str__(self):
        return 'Payment settings'

    @classmethod
    def get_solo(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    @property
    def razorpay_ready(self):
        return bool(self.is_razorpay_enabled and self.razorpay_key_id and self.razorpay_key_secret)


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


# Product id (matches Product.slug) whose first delivered order
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


class Payment(models.Model):
    """A payment attempt/record for an Order — either Cash on Delivery or a
    Razorpay transaction. One Order can have multiple Payment rows if a
    Razorpay attempt fails and the shopper retries."""
    METHOD_COD      = 'cod'
    METHOD_RAZORPAY = 'razorpay'
    METHOD_CHOICES = [
        (METHOD_COD, 'Cash on Delivery'),
        (METHOD_RAZORPAY, 'Razorpay'),
    ]

    STATUS_PENDING     = 'pending'
    STATUS_PAID        = 'paid'
    STATUS_FAILED      = 'failed'
    STATUS_REFUNDED    = 'refunded'
    STATUS_COD_PENDING = 'cod_pending'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_PAID, 'Paid'),
        (STATUS_FAILED, 'Failed'),
        (STATUS_REFUNDED, 'Refunded'),
        (STATUS_COD_PENDING, 'COD — pay on delivery'),
    ]

    order                = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='payments')
    method               = models.CharField(max_length=20, choices=METHOD_CHOICES, default=METHOD_COD)
    status               = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    amount               = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    razorpay_order_id    = models.CharField(max_length=80, blank=True)
    razorpay_payment_id  = models.CharField(max_length=80, blank=True)
    razorpay_signature   = models.CharField(max_length=200, blank=True)
    created_at           = models.DateTimeField(auto_now_add=True)
    updated_at           = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Payment'
        verbose_name_plural = 'Payments'

    def __str__(self):
        return f"Payment for Order #{self.order_id} — {self.get_method_display()} ({self.get_status_display()})"
