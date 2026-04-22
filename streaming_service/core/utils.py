import time
import os
import logging
from functools import wraps
from dotenv import load_dotenv
from .models import SearchAnalytics

load_dotenv() 
logger = logging.getLogger('synapse.ai.engine')

COST_PER_1K_TOKENS = float(os.getenv('COST_PER_1K_TOKENS', '0.0001'))

def measure_hybrid_search(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        search_query = kwargs.get('query', args[0] if args else 'Unknown')
        current_user = kwargs.get('user', None)
        
        start_time = time.perf_counter()
        
        result = func(*args, **kwargs)
        
        end_time = time.perf_counter()
        execution_time_ms = (end_time - start_time) * 1000
        
        movies = result[0] if isinstance(result, tuple) else result
        movies_count = len(movies) if movies else 0
        
        estimated_tokens = int(len(search_query.split()) * 1.3)
        cost = (estimated_tokens / 1000.0) * COST_PER_1K_TOKENS
        
        try:
            SearchAnalytics.objects.create(
                user=current_user if current_user and current_user.is_authenticated else None,
                query=search_query,
                latency_ms=execution_time_ms,
                tokens_used=estimated_tokens,
                estimated_cost_usd=cost,
                results_count=movies_count
            )
        except Exception as e:
            logger.error(f"Error viewing SearchAnalytics: {e}")
        
        logger.info(
            f"RRF Hybrid Search | Query: '{search_query}' | "
            f"Results: {len(movies)} | Latency: {execution_time_ms:.2f} ms | Cost: ${cost:.6f}"
        )
        
        return result
    return wrapper