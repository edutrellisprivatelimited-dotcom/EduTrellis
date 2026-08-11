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
from datetime import timedelta

from django.contrib.auth.models import User
from django.utils import timezone

from myapp.models import Order, OrderItem, Payment, Product, Review, StoreProfile

DEMO_PASSWORD = '123456'

REVIEWERS = [
    ('Ankit', 'Sharma'), ('Priya', 'Verma'), ('Rohit', 'Singh'), ('Neha', 'Gupta'),
    ('Saurabh', 'Yadav'), ('Kavita', 'Nair'), ('Arjun', 'Mehta'), ('Simran', 'Kaur'),
    ('Vikas', 'Reddy'), ('Pooja', 'Iyer'), ('Rahul', 'Kapoor'), ('Anjali', 'Joshi'),
    ('Manish', 'Chauhan'), ('Divya', 'Menon'), ('Suresh', 'Pillai'), ('Ritu', 'Malhotra'),
    ('Karan', 'Bhatt'), ('Sneha', 'Rao'), ('Aditya', 'Kulkarni'), ('Meera', 'Desai'),
    ('Varun', 'Chopra'), ('Shreya', 'Agarwal'), ('Nikhil', 'Bansal'), ('Swati', 'Deshmukh'),
    ('Gaurav', 'Saxena'), ('Isha', 'Thakur'), ('Deepak', 'Mishra'), ('Anushka', 'Bhatia'),
    ('Sandeep', 'Rana'), ('Kirti', 'Sinha'), ('Abhishek', 'Trivedi'), ('Ritika', 'Chandra'),
    ('Mohit', 'Arora'), ('Preeti', 'Nagpal'), ('Yash', 'Vora'), ('Tanvi', 'Shah'),
    ('Harsh', 'Goyal'), ('Namrata', 'Pandey'), ('Siddharth', 'Rathi'), ('Bhavna', 'Sood'),
    ('Ashwin', 'Krishnan'), ('Ramya', 'Subramanian'), ('Pankaj', 'Tiwari'), ('Alisha', 'Khanna'),
    ('Nitin', 'Chawla'), ('Sunita', 'Kohli'), ('Rajesh', 'Ghosh'), ('Komal', 'Dutta'),
    ('Vivek', 'Nambiar'), ('Anita', 'Chatterjee'), ('Sameer', 'Qureshi'), ('Farah', 'Sheikh'),
    ('Imran', 'Ansari'), ('Zainab', 'Malik'),
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
    (5, "Bought this for my parents and they're really happy with it. Easy to use, no complicated setup. Good buy."),
    (4, "Solid product for daily use. Not much else to say — it just works, and that's what I wanted."),
    (5, "Better than similar products I've used from bigger brands, honestly. Glad I took a chance on this store."),
    (3, "Average experience. Product is fine but delivery tracking wasn't updated properly, had to call to check status."),
    (5, "Third time ordering from EduTrellis Store and they haven't disappointed yet. Consistent quality, fair pricing."),
    (4, "Value for money. A couple of minor niggles but nothing that affects how well it works day to day."),
    (5, "Super happy with the purchase. Arrived well before the expected date and exactly as shown in the pictures."),
    (2, "Had an issue with the first unit but customer support replaced it quickly without any hassle. Works fine now."),
    (5, "Sound/build quality (whichever applies) is genuinely impressive for this price bracket. Highly recommend."),
    (4, "Good purchase overall. Packaging could be sturdier but the product itself arrived undamaged and works well."),
    (5, "Exactly what I needed. Simple, reliable, does the job without any fuss. Would buy again."),
    (4, "Happy with the quality. Took about 4 days to arrive which was a bit longer than expected but worth the wait."),
    (5, "Very satisfied — this is my go-to store now for gadgets. Prices are fair and the products are genuine."),
    (3, "It's decent for the price but I expected slightly better finishing. Functionally it works as advertised though."),
    (5, "Excellent build quality and fast COD delivery. No complaints at all, will be ordering more from here."),
    (4, "Works as expected. Customer support was responsive when I had a question about the warranty."),
    (5, "Really pleased with this — feels premium, works reliably, and the price was fair for what you get."),
]


def seed_demo_reviews():
    """Creates/refreshes the 54 demo buyer accounts and their reviews.
    Returns a short human-readable summary string."""
    products = list(Product.objects.filter(is_active=True))
    if not products:
        return "No active products found — add a product before seeding reviews."

    random.shuffle(products)
    accounts_made = 0
    reviews_made = 0
    now = timezone.now()

    for i, (first, last) in enumerate(REVIEWERS):
        # Spread reviews ~2 days apart going back in time (covering the last
        # few months across all 54), with a little jitter, so they don't all
        # show today's date — auto_now_add would otherwise stamp every
        # seeded review with the moment the command ran, which reads as
        # fake. QuerySet.update() below bypasses auto_now_add (it only
        # fires on Model.save()).
        review_date = now - timedelta(days=2 + i * 2 + random.randint(0, 2), hours=random.randint(0, 23), minutes=random.randint(0, 59))
        order_date = review_date - timedelta(days=random.randint(2, 5))
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
            Order.objects.filter(pk=order.pk).update(created_at=order_date, updated_at=review_date)

        review, created = Review.objects.update_or_create(
            product=product, user=user, defaults={'rating': rating, 'comment': comment},
        )
        Review.objects.filter(pk=review.pk).update(created_at=review_date)
        if created:
            reviews_made += 1

    product_count = min(len(REVIEWERS), len(products))
    return (
        f"Seeded {accounts_made} new demo accounts (password: {DEMO_PASSWORD}) and "
        f"{reviews_made} new reviews across {product_count} product{'s' if product_count != 1 else ''}."
    )
