import time
import logging
from functools import wraps

logger = logging.getLogger('synapse.ai.engine')

def measure_hybrid_search(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        start_time = time.perf_counter()
        
        result = func(*args, **kwargs)
        
        end_time = time.perf_counter()
        execution_time_ms = (end_time - start_time) * 1000
        
        movies = result[0] if isinstance(result, tuple) else result
        query = args[1] if len(args) > 1 else kwargs.get('query', 'Unknown')
        
        logger.info(
            f"RRF Hybrid Search | Query: '{query}' | "
            f"Results: {len(movies)} | Latency: {execution_time_ms:.2f} ms"
        )
        
        return result
    return wrapper