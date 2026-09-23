from .base import Collector, CollectorError
from .demo import DemoCollector
from .mercadolivre import MercadoLivreCollector

__all__ = ["Collector", "CollectorError", "DemoCollector", "MercadoLivreCollector"]
