from django.contrib.sitemaps import Sitemap
from django.urls import reverse

from myapp.models import Product

DOMAIN = 'edutrellis.in'


class StaticViewSitemap(Sitemap):
    protocol = 'https'
    changefreq = 'weekly'

    priorities = {
        'home': 1.0,
        'home2': 0.9,
        'estore': 0.9,
    }

    def get_urls(self, page=1, site=None, protocol=None):
        protocol = self.protocol
        return [
            {
                'item': item,
                'location': 'https://{}{}'.format(DOMAIN, reverse(item)),
                'lastmod': None,
                'changefreq': self.changefreq,
                'priority': str(self.priorities[item]),
                'alternates': [],
                'x_default': None,
            }
            for item in self.items()
        ]

    def items(self):
        return ['home', 'home2', 'estore']

    def location(self, item):
        return reverse(item)


class ProductSitemap(Sitemap):
    protocol = 'https'
    changefreq = 'weekly'
    priority = 0.7

    def get_urls(self, page=1, site=None, protocol=None):
        protocol = self.protocol
        return [
            {
                'item': item,
                'location': 'https://{}{}'.format(DOMAIN, self.location(item)),
                'lastmod': self.lastmod(item),
                'changefreq': self.changefreq,
                'priority': str(self.priority),
                'alternates': [],
                'x_default': None,
            }
            for item in self.paginator.page(page).object_list
        ]

    def items(self):
        return Product.objects.filter(is_active=True)

    def location(self, product):
        return reverse('product_detail', kwargs={'slug': product.slug})

    def lastmod(self, product):
        return product.updated_at
