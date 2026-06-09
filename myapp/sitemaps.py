from django.contrib.sitemaps import Sitemap
from django.urls import reverse


class StaticViewSitemap(Sitemap):
    protocol = 'https'
    priority = 1.0
    changefreq = 'weekly'

    def get_urls(self, page=1, site=None, protocol=None):
        protocol = self.protocol
        domain = 'www.edutrellis.in'
        return [
            {
                'item': item,
                'location': 'https://{}{}'.format(domain, reverse(item)),
                'lastmod': None,
                'changefreq': self.changefreq,
                'priority': str(self.priority),
                'alternates': [],
                'x_default': None,
            }
            for item in self.items()
        ]

    def items(self):
        return ['home', 'contact_lead']

    def location(self, item):
        return reverse(item)
