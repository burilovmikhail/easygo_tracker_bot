import time
import random
import structlog
logger = structlog.get_logger()


def retry(attempts=10, initial_delay=1, backoff_factor=2, max_delay=300, jitter=True, pass_attempt=False):
    def decorator(func):
        def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(attempts):
                if pass_attempt:
                    kwargs["attempt"] = attempt + 1

                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    delay = min(initial_delay *
                                (backoff_factor ** attempt), max_delay)
                    if jitter:
                        delay *= random.uniform(0.8, 1.2)
                    logger.exception(
                        f"Attempt {attempt + 1} failed with error: {e}. Retrying in {delay} seconds...")
                    time.sleep(delay)
            logger.info(f"Failed after {attempts} attempts.")
            raise last_exception
        return wrapper
    return decorator
