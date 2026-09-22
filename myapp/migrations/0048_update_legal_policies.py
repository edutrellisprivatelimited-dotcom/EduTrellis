from django.db import migrations, models


UPDATED_POLICIES = [
    {
        'key': 'privacy',
        'title': 'Privacy Policy',
        'content': (
            "EduTrellis (\"EduTrellis\", \"we\", \"us\", \"our\") is a sole proprietorship business, "
            "Udyam-registered as an MSME enterprise in Lucknow, Uttar Pradesh, India. This Privacy Policy "
            "explains what personal information we collect and how we use it across edutrellis.in, the "
            "EduTrellis Store, and the Vidhyora AI platform (together, the \"Services\"), and applies "
            "wherever this policy is linked.\n\n"
            "When you create an account, place an order, contact support, or sign up for a subscription, "
            "we collect information you give us directly — such as your name, phone number, email address, "
            "delivery address, payment/order history and any documents or messages you send us. We also "
            "collect basic technical data such as your IP address, device/browser type and usage logs, "
            "used for security, fraud prevention and keeping the Services working correctly.\n\n"
            "If you use Vidhyora AI or any other AI feature on our platform, we additionally collect and "
            "store the messages, files, images, audio or documents you submit, and the AI-generated "
            "responses, so your conversation history can be shown back to you and to help us investigate "
            "abuse or technical issues. To generate a response, your message content is sent to one or "
            "more third-party AI/large-language-model providers for processing; we choose and may change "
            "these providers without notice, and their own processing of your input is governed by their "
            "own terms in addition to this policy. Do not submit sensitive personal information (such as "
            "government ID numbers, financial account details, health information or passwords) in AI "
            "chat — treat it like any other online chat.\n\n"
            "We use this information to create and manage your account, process and deliver orders and "
            "subscriptions, respond to support requests, operate and improve the Services, prevent fraud "
            "and abuse, and comply with legal obligations. We do not sell your personal information to "
            "third parties. We share information only where necessary — with our payment gateway partner "
            "(Razorpay) to process payments, with delivery partners to fulfil physical orders, with the "
            "AI/API providers described above to generate AI responses, and with authorities where "
            "required by law.\n\n"
            "Payment details such as card, UPI or net-banking credentials are handled directly by our "
            "payment gateway partner (Razorpay) and are never stored on EduTrellis servers.\n\n"
            "We use cookies and similar technologies (such as session identifiers and CSRF tokens) "
            "required to keep you signed in and to keep the Services secure. We do not use these for "
            "third-party advertising.\n\n"
            "We retain account, order and conversation data for as long as your account is active and "
            "thereafter for as long as required for accounting, security or legal purposes. You can "
            "request a copy of the personal data we hold about you, ask us to correct it, or ask us to "
            "delete your account and associated data, by writing to support@edutrellis.in; we will "
            "respond within a reasonable time, subject to any record-keeping we are legally required to "
            "retain.\n\n"
            "Our Services are not directed at children under 18. If you believe a child has provided us "
            "with personal information, contact us and we will delete it.\n\n"
            "Grievance Officer: in accordance with the Information Technology Act, 2000 and rules made "
            "under it, complaints or concerns about this policy can be sent to our Grievance Officer, "
            "Vijay Tiwari (Founder & CEO), at ceo@edutrellis.in; we aim to acknowledge complaints within "
            "24 hours and resolve them within 15 days.\n\n"
            "We may update this policy from time to time; the latest version will always be available on "
            "this page. If you have questions about this policy, contact us at support@edutrellis.in."
        ),
    },
    {
        'key': 'terms',
        'title': 'Terms & Conditions',
        'content': (
            "These Terms & Conditions (\"Terms\") govern your access to and use of edutrellis.in, the "
            "EduTrellis Store, and the Vidhyora AI platform (together, the \"Services\"), operated by "
            "EduTrellis, a sole proprietorship business Udyam-registered as an MSME enterprise in Lucknow, "
            "Uttar Pradesh, India (\"EduTrellis\", \"we\", \"us\"). By creating an account, placing an "
            "order, subscribing to a plan, or otherwise using the Services, you agree to these Terms.\n\n"
            "EduTrellis provides (a) website design, development, management, SEO and digital-marketing "
            "services; (b) an e-commerce store selling physical and digital products (\"EduTrellis "
            "Store\"); and (c) Vidhyora AI, a subscription/usage-based platform that gives you access to "
            "one or more third-party AI/large-language-model providers through a common interface. The "
            "specific underlying AI provider(s) may change at any time without notice, as we continually "
            "evaluate quality, cost and reliability.\n\n"
            "You are responsible for maintaining the confidentiality of your account credentials and for "
            "all activity under your account. Notify us immediately at support@edutrellis.in if you "
            "suspect unauthorised use. You must be at least 18 years old, or using the Services under the "
            "supervision of a parent/guardian, to create an account.\n\n"
            "For website development, management, SEO and digital-marketing engagements, the specific "
            "scope, deliverables, timelines and fees are as agreed in writing (including over email/"
            "WhatsApp) with each client at the time of engagement. We make reasonable, professional "
            "efforts to deliver these services but do not guarantee specific search-engine rankings, "
            "traffic, leads, sales or revenue outcomes, since these depend on factors outside our "
            "control, including third-party platforms (Google, Meta, hosting providers) and market "
            "conditions.\n\n"
            "Product listings, prices and stock availability on the EduTrellis Store are updated "
            "regularly but may change without prior notice. We make reasonable efforts to display "
            "accurate specifications, images and pricing, and reserve the right to cancel and fully "
            "refund an order placed at an incorrect price due to a technical or listing error. Orders "
            "are confirmed once payment is received (or, for Cash on Delivery, once placed) and are "
            "subject to stock availability. We reserve the right to refuse or cancel an order at our "
            "discretion, including in cases of suspected fraud or abuse of offers, in which case any "
            "payment already made will be refunded in full. Wallet credit earned through promotional "
            "offers has no cash value, cannot be transferred or redeemed for cash, and can only be used "
            "towards future purchases on the Store.\n\n"
            "Access to Vidhyora AI and any API-based product is provided on a subscription or "
            "usage-based (credit/quota) basis as described at the time of purchase. Plans, quotas, "
            "fair-usage limits and pricing may change with reasonable notice for future billing cycles. "
            "Unless stated otherwise at checkout, fees already paid for a subscription period or consumed "
            "usage credits are non-refundable once the access has been activated or the usage has been "
            "consumed — see our Refund & Cancellation Policy for details. We may suspend or terminate "
            "access, without refund, for use that violates our Acceptable Use Policy, these Terms, or "
            "applicable law.\n\n"
            "AI-generated content (text, code, summaries, transcriptions or any other output) is produced "
            "by third-party AI models and may be inaccurate, incomplete or unsuitable for your purpose. "
            "You are solely responsible for reviewing and verifying any AI output before relying on it — "
            "see our Disclaimer page for details. You retain ownership of the input you submit and the "
            "output generated for you, subject to the underlying AI provider's own terms and any "
            "third-party rights in the input you submitted; you are responsible for ensuring you have the "
            "right to submit any content you provide.\n\n"
            "All content on our Services — including text, images, logos, software and the EduTrellis and "
            "Vidhyora AI names — is the property of EduTrellis or its licensors and may not be reproduced "
            "without permission, other than the AI input/output ownership described above.\n\n"
            "To the maximum extent permitted by law, the Services are provided \"as is\" and \"as "
            "available\", without warranties of any kind. EduTrellis is not liable for indirect, "
            "incidental or consequential damages, or for any loss arising from reliance on AI-generated "
            "content, third-party provider outages, or third-party services we integrate with. Our total "
            "liability for any claim relating to the Services is limited to the amount you paid us for "
            "the specific service giving rise to the claim in the preceding 3 months.\n\n"
            "These Terms are governed by the laws of India, and any disputes are subject to the exclusive "
            "jurisdiction of the courts in Lucknow, Uttar Pradesh. Grievance Officer: Vijay Tiwari "
            "(Founder & CEO), ceo@edutrellis.in, P-109, Prembagh, Shahpur, Chinhat, Lucknow, Uttar "
            "Pradesh 226028."
        ),
    },
    {
        'key': 'refund',
        'title': 'Refund & Cancellation Policy',
        'content': (
            "This Refund & Cancellation Policy explains how refunds and cancellations work across the "
            "EduTrellis Store, website-development/marketing engagements, and Vidhyora AI / API "
            "subscriptions.\n\n"
            "EduTrellis Store: if an order is cancelled before dispatch, or we are unable to fulfil it, "
            "any amount paid online (via Razorpay, UPI or card) is refunded in full to the original "
            "payment method, typically within 5–7 business days depending on your bank. If a physical "
            "item arrives damaged, defective, or different from what you ordered, contact us at "
            "support@edutrellis.in within 48 hours of delivery with your order number and photos; once "
            "verified, we offer a free replacement where stock allows, or a full refund to your original "
            "payment method or Store wallet credit, whichever you prefer. Digital products/services "
            "purchased on the Store are delivered instantly or within the timeframe stated at checkout "
            "and, once access has been granted or a digital licence key has been issued, are non-"
            "refundable except where the product is materially defective or not as described.\n\n"
            "Refunds for Cash on Delivery orders are issued as Store wallet credit or via bank transfer/"
            "UPI, since no online payment was collected at the time of purchase. Refunds are not offered "
            "for change-of-mind on items outside a reported delivery issue, or once a physical product "
            "has been used beyond simple inspection. Wallet credit issued as part of a refund or "
            "promotional offer is non-transferable and has no cash value.\n\n"
            "Vidhyora AI / API subscriptions and usage credits: fees for a subscription period are "
            "non-refundable once your access for that period has been activated, and purchased usage "
            "credits are non-refundable once consumed, except where required by law. If you cancel a "
            "recurring subscription, your access continues until the end of the period already paid "
            "for, and it will not renew for the next period — no partial refund is given for the unused "
            "portion of a period. If a technical fault on our side (not a third-party AI provider outage) "
            "prevents you from using a paid subscription for more than 48 continuous hours, contact "
            "support@edutrellis.in and we will extend your subscription or issue a pro-rata credit at our "
            "discretion.\n\n"
            "Website-development, management and marketing engagements: any advance/retainer paid is "
            "refundable, less the value of work already performed and any third-party costs already "
            "incurred (such as domain, hosting or ad-spend), if you cancel before the agreed deliverable "
            "is completed. Once a website or deliverable has been fully delivered and accepted, fees for "
            "that deliverable are non-refundable; ongoing monthly management/retainer fees already "
            "charged for a month already in progress are non-refundable for that month.\n\n"
            "For any refund, cancellation or billing query, email support@edutrellis.in with your order/"
            "subscription details — we usually respond within one business day."
        ),
    },
    {
        'key': 'shipping',
        'title': 'Shipping & Delivery',
        'content': (
            "Physical orders placed on the EduTrellis Store are packed and dispatched from our base in "
            "Lucknow, Uttar Pradesh, within 24 hours of being placed (excluding Sundays and public "
            "holidays), subject to stock availability. Once dispatched, you will receive a tracking "
            "update by email and, where a phone number is on file, by WhatsApp. Typical delivery times "
            "are 2–4 business days for major cities and 4–7 business days for other locations across "
            "India, depending on the courier partner and destination pincode; timelines can occasionally "
            "be affected by weather, regional restrictions or courier delays outside our control.\n\n"
            "We offer both prepaid (Razorpay — UPI, cards, net banking) and Cash on Delivery options at "
            "checkout for physical products, subject to availability for your pincode. Delivery charges, "
            "when applicable, are shown at checkout before you confirm your order. Please ensure your "
            "delivery address and phone number are accurate and reachable — orders returned due to an "
            "incorrect address or repeated failed delivery attempts may be subject to re-shipping "
            "charges.\n\n"
            "Digital products, Vidhyora AI plans, and API access do not involve physical shipping. Access "
            "is typically activated instantly, or within a few hours, after successful payment; any "
            "exceptions are stated at checkout. For website-development and marketing engagements, "
            "delivery timelines (e.g. first draft, go-live date) are agreed with you in writing at the "
            "start of the engagement and may vary based on the scope of work and how quickly you provide "
            "inputs (content, approvals, access).\n\n"
            "For any shipping, delivery or access-activation question, write to support@edutrellis.in "
            "with your order number."
        ),
    },
    {
        'key': 'disclaimer',
        'title': 'Disclaimer',
        'content': (
            "The information, tools and content available through edutrellis.in, the EduTrellis Store "
            "and Vidhyora AI are provided in good faith for general and business use, but EduTrellis "
            "makes no representation or warranty of any kind, express or implied, regarding their "
            "accuracy, completeness, reliability or suitability for any particular purpose. Your use of, "
            "and reliance on, any information or output from our Services is strictly at your own "
            "risk.\n\n"
            "Vidhyora AI and any other AI feature we offer use one or more third-party AI/large-language-"
            "model providers, which may change at any time without notice. AI-generated responses — "
            "including text, code, summaries, transcriptions, translations and any other output — can be "
            "incorrect, incomplete, outdated or misleading, and should not be treated as professional, "
            "legal, medical, financial or other expert advice. Always independently verify any important "
            "information before relying or acting on it. EduTrellis is not affiliated with, endorsed by, "
            "or a representative of OpenAI, ChatGPT, Google, Anthropic, Meta, or any other AI model "
            "provider, unless explicitly stated in writing; any resemblance in naming or interface to a "
            "third-party product does not imply such affiliation.\n\n"
            "For website development, SEO and digital-marketing services, any figures, timelines or "
            "outcomes discussed (such as rankings, traffic, leads or sales) are estimates based on "
            "experience, not guarantees, and actual results depend on factors outside our control, "
            "including search-engine and advertising-platform algorithm changes, market competition, and "
            "your own business execution.\n\n"
            "Our Services may link to, or integrate with, third-party websites, payment gateways, AI "
            "providers, or delivery partners that we do not control. We are not responsible for the "
            "content, accuracy, availability, or practices of these third parties, and using them is "
            "subject to their own terms and policies.\n\n"
            "Nothing on our Services constitutes legal, financial, tax, medical or other professional "
            "advice. Consult an appropriately qualified professional for advice specific to your "
            "situation.\n\n"
            "This Disclaimer should be read together with our Terms & Conditions, which contain the "
            "applicable limitation of liability. If you have questions about this Disclaimer, contact us "
            "at support@edutrellis.in."
        ),
    },
    {
        'key': 'acceptable_use',
        'title': 'Acceptable Use Policy (AI & API Services)',
        'content': (
            "This Acceptable Use Policy applies to Vidhyora AI and any other AI or API-based product "
            "offered by EduTrellis (together, the \"AI Services\"). It exists to keep the AI Services "
            "safe, lawful and available for everyone, and sets out what you may not use them for.\n\n"
            "You agree not to use the AI Services to generate, request, upload or distribute content "
            "that: is illegal, or that facilitates illegal activity, under Indian law or the law of your "
            "location; infringes someone else's intellectual property, privacy, or other rights; is "
            "defamatory, harassing, hateful, or sexually explicit involving minors; impersonates a real "
            "person or organisation without consent; contains malware, or is intended to gain "
            "unauthorised access to any system; or generates spam, disinformation, or content intended to "
            "deceive or manipulate at scale.\n\n"
            "You also agree not to: attempt to bypass usage limits, quotas or subscription tiers; scrape, "
            "systematically extract, or resell access to the AI Services or the underlying AI models "
            "without our prior written consent; reverse-engineer, decompile or attempt to extract the "
            "underlying AI model, prompts or system instructions; use automated means (bots, scripts) to "
            "interact with the AI Services beyond normal individual use; or share your account/API "
            "credentials with others to circumvent per-account limits.\n\n"
            "Subscription and plan quotas are intended for genuine individual or business use as "
            "described at the time of purchase. We may apply reasonable rate limits to protect the "
            "Services for all users, and may throttle, suspend or ask you to upgrade your plan if your "
            "usage pattern is inconsistent with normal individual/business use, even if you are within a "
            "stated numeric quota.\n\n"
            "Because the AI Services rely on third-party AI/large-language-model providers, your use "
            "must also comply with those providers' own acceptable-use policies, to the extent "
            "applicable; we may need to restrict certain requests or outputs to stay compliant with a "
            "provider's policies, independent of anything stated elsewhere.\n\n"
            "Violating this policy may result in a warning, temporary suspension, or permanent "
            "termination of your account and access to the AI Services, without refund, at our "
            "discretion, depending on severity. If you encounter content or behaviour on the AI Services "
            "that you believe violates this policy, report it to support@edutrellis.in."
        ),
    },
]


def update_policies(apps, schema_editor):
    PolicyPage = apps.get_model('myapp', 'PolicyPage')
    for data in UPDATED_POLICIES:
        PolicyPage.objects.update_or_create(
            key=data['key'],
            defaults={'title': data['title'], 'content': data['content']},
        )

    AboutUsContent = apps.get_model('myapp', 'AboutUsContent')
    AboutUsContent.objects.filter(
        paragraph1__icontains='EduTrellis Private Limited',
    ).update(
        paragraph1=(
            "EduTrellis has been working since 2020 — building and selling websites, "
            "and running the technical services around them: hosting, SEO, digital marketing and Google "
            "Business, for clients across India from our base in Lucknow."
        )
    )


def noop_reverse(apps, schema_editor):
    # Content edits aren't reversible to their exact prior text; the seed
    # migration (0010) still holds the original copy if ever needed.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('myapp', '0047_refresh_vidhyora_branding'),
    ]

    operations = [
        migrations.AlterField(
            model_name='policypage',
            name='key',
            field=models.CharField(
                choices=[
                    ('privacy', 'Privacy Policy'),
                    ('terms', 'Terms & Conditions'),
                    ('refund', 'Refund & Cancellation Policy'),
                    ('shipping', 'Shipping & Delivery'),
                    ('disclaimer', 'Disclaimer'),
                    ('acceptable_use', 'Acceptable Use Policy (AI & API Services)'),
                ],
                max_length=20,
                unique=True,
            ),
        ),
        migrations.RunPython(update_policies, noop_reverse),
    ]
