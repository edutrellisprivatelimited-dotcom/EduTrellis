"""Seeds demo buyer accounts + reviews so the storefront doesn't launch with
zero social proof. Each seeded reviewer gets a real Delivered order for the
product they "review", so they pass the same purchase-verification gate
(_user_can_review in views.py) as a genuine customer — these show up marked
"Verified purchase" exactly like real reviews. Safe to re-run: accounts and
reviews are upserted, never duplicated.

Used by both `python manage.py seed_reviews` and the dashboard's
"Seed demo reviews" button (dashboard_seed_reviews in views.py).
"""
import random

from django.contrib.auth.models import User

from myapp.models import Order, OrderItem, Payment, Product, Review, StoreProfile

DEMO_PASSWORD = '123456'

REVIEWERS = [
    ('Ankit', 'Sharma'),
    ('Priya', 'Verma'),
    ('Rohit', 'Singh'),
    ('Neha', 'Gupta'),
    ('Saurabh', 'Yadav'),
    ('Kavita', 'Nair'),
    ('Arjun', 'Mehta'),
    ('Simran', 'Kaur'),
    ('Vikas', 'Reddy'),
    ('Pooja', 'Iyer'),
]

REVIEW_TEMPLATES = [
    (5, "Genuinely happy with this purchase. Build quality feels premium and it works exactly as described. Delivery was quick too."),
    (5, "Was a bit skeptical ordering from a smaller store but this exceeded expectations. Packaging was solid, no damage, works perfectly."),
    (4, "Good product overall. Does what it says. Only reason I'm not giving 5 stars is the box was a little worn, but the item itself is fine."),
    (5, "Using it daily for almost 2 weeks now, zero issues. Battery backup is better than I expected. Would recommend."),
    (4, "Decent quality for the price. Setup was easy. Wish the manual had a bit more detail but figured it out quickly."),
    (5, "Ordered COD, got it in 3 days, well packed. Product matches the photos and description exactly. Very satisfied."),
    (3, "It's okay, does the job but nothing extraordinary. Expected slightly better finishing for this price point."),
    (5, "Excellent! My second order from this store and both times the quality has been consistent. Support replied quickly when I had a question."),
    (4, "Works well, comfortable to use daily. Shipping took a couple of days longer than expected but the product itself is solid."),
    (5, "Really impressed. Feels durable, performs well, and arrived earlier than the estimated delivery date."),
]


def seed_demo_reviews():
    """Creates/refreshes the 10 demo buyer accounts and their reviews.
    Returns a short human-readable summary string."""
    products = list(Product.objects.filter(is_active=True))
    if not products:
        return "No active products found — add a product before seeding reviews."

    random.shuffle(products)
    accounts_made = 0
    reviews_made = 0

    for i, (first, last) in enumerate(REVIEWERS):
        email = f"{first.lower()}.{last.lower()}.demo@example.com"
        user, made = User.objects.get_or_create(
            username=email, defaults={'email': email, 'first_name': first, 'last_name': last},
        )
        if made:
            user.set_password(DEMO_PASSWORD)
            user.save()
            accounts_made += 1

        profile, _ = StoreProfile.objects.get_or_create(
            user=user, defaults={'phone': f'9{random.randint(100000000, 999999999)}'},
        )

        product = products[i % len(products)]
        rating, comment = REVIEW_TEMPLATES[i % len(REVIEW_TEMPLATES)]

        has_delivered_order = OrderItem.objects.filter(
            order__user=user, order__status=Order.STATUS_DELIVERED, product_id=product.slug,
        ).exists()
        if not has_delivered_order:
            order = Order.objects.create(
                user=user, status=Order.STATUS_DELIVERED,
                subtotal=product.price, total=product.price,
                recipient_name=f"{first} {last}", recipient_phone=profile.phone,
                address_line1='Demo delivery address', city='Lucknow', state='Uttar Pradesh', pincode='226001',
            )
            OrderItem.objects.create(
                order=order, product_id=product.slug, product_name=product.name,
                price=product.price, quantity=1,
            )
            Payment.objects.create(order=order, method=Payment.METHOD_COD, status=Payment.STATUS_PAID, amount=product.price)

        _review, created = Review.objects.update_or_create(
            product=product, user=user, defaults={'rating': rating, 'comment': comment},
        )
        if created:
            reviews_made += 1

    product_count = min(len(REVIEWERS), len(products))
    return (
        f"Seeded {accounts_made} new demo accounts (password: {DEMO_PASSWORD}) and "
        f"{reviews_made} new reviews across {product_count} product{'s' if product_count != 1 else ''}."
    )
