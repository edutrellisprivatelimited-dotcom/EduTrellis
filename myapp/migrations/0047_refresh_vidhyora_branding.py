from django.db import migrations, models


VIDHYORA_PLAN_SLUGS = (
    'vidhyora-ai-1-month',
    'vidhyora-ai-6-months',
    'vidhyora-ai-1-year',
)

FEATURES = (
    "Vidhyora AI gives you premium access to three purpose-built models in one workspace:\n\n"
    "• Vidhyora Nova — advanced general AI\n"
    "• Vidhyora Prime — powerful reasoning and multimodal AI\n"
    "• Vidhyora Flux — fast, efficient multimodal AI\n\n"
    "Create unlimited images, upload files and images, and enjoy unlimited premium chat. "
    "Generate files, search the web with cited results, connect GitHub, inspect and edit repositories, "
    "and get support when you need it. Developer features include free API access, tools to create your "
    "own AI model experience, and options to resell what you build. More premium features are added regularly."
)


def refresh_vidhyora_products(apps, schema_editor):
    Product = apps.get_model('myapp', 'Product')

    # Retire the superseded listing without deleting its historical reviews
    # or order references; it is no longer visible in the storefront.
    Product.objects.filter(slug='edutrellis-ai-monthly').update(is_active=False)

    for product in Product.objects.filter(slug__in=VIDHYORA_PLAN_SLUGS):
        duration = product.name.split('—', 1)[-1].strip() if '—' in product.name else 'Premium'
        product.brand = 'Vidhyora AI'
        product.short_description = (
            f'{duration} of Vidhyora AI with unlimited premium chat, unlimited image creation and uploads.'
        )
        product.description = FEATURES
        product.specs = (
            f"Plan duration: {duration}\n"
            "Models: Vidhyora Nova, Vidhyora Prime and Vidhyora Flux\n"
            "Chat: Unlimited premium chat\n"
            "Images: Unlimited image creation and image uploads\n"
            "Files: Upload, analyse and generate files\n"
            "Development: GitHub connection and repository editing\n"
            "Research: Web search with results and citations\n"
            "API: Free API access\n"
            "Business: Create your own AI model experience and resell it\n"
            "Support: Customer support included\n"
            "Platform: https://www.vidhyora.online/\n"
            "Delivery: Digital subscription activation after payment confirmation"
        )
        product.tags = (
            'Vidhyora AI, Vidhyora Nova, Vidhyora Prime, Vidhyora Flux, multimodal AI, '
            'unlimited AI chat, image generation, file upload, GitHub, web search, API'
        )
        product.save(update_fields=['brand', 'short_description', 'description', 'specs', 'tags'])

    for product in Product.objects.filter(category__slug='ai'):
        changed = []
        for field in ('short_description', 'description', 'specs', 'tags'):
            value = getattr(product, field) or ''
            updated = value.replace('ChatGPT and other supported AI models', 'Vidhyora AI models')
            updated = updated.replace('ChatGPT and other supported models', 'Vidhyora AI models')
            updated = updated.replace('ChatGPT', 'Vidhyora AI')
            if updated != value:
                setattr(product, field, updated)
                changed.append(field)
        if changed:
            product.save(update_fields=changed)


class Migration(migrations.Migration):

    dependencies = [
        ('myapp', '0046_pwasettings_share_branding'),
    ]

    operations = [
        migrations.AlterField(
            model_name='storeprofile',
            name='ai_free_messages_used',
            field=models.PositiveIntegerField(default=0, help_text='Free-tier Vidhyora AI messages sent so far (resets on each new subscription purchase).'),
        ),
        migrations.AlterField(
            model_name='storeprofile',
            name='ai_subscription_until',
            field=models.DateTimeField(blank=True, help_text='Vidhyora AI access is unlimited until this time. Blank/past = free tier.', null=True),
        ),
        migrations.RunPython(refresh_vidhyora_products, migrations.RunPython.noop),
    ]
