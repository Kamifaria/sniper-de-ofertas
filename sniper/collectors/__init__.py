from .amazon import AmazonCollector
from .base import Collector, CollectorError
from .kabum import KabumCollector
from .mercadolivre import MercadoLivreCollector
from .shopify import ShopifyCollector
from .vtex import VtexCollector

__all__ = ["AmazonCollector", "Collector", "CollectorError", "KabumCollector", "MercadoLivreCollector",
           "ShopifyCollector", "VtexCollector"]
