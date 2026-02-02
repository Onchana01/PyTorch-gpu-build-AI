from typing import Callable, TypeVar, Optional, Type, Tuple, Any
from functools import wraps
import time
import random
import asyncio
from dataclasses import dataclass, field

from src.common.exceptions.base_exceptions import RetryableException, CICDBaseException
from src.common.config.logging_config import get_logger


logger = get_logger(__name__)

T = TypeVar("T")
F = TypeVar("F", bound=Callable[..., Any])


@dataclass
class RetryConfig:
    max_retries: int = 3
    initial_delay: float = 1.0
    max_delay: float = 60.0
    exponential_base: float = 2.0
    jitter: bool = True
    jitter_factor: float = 0.1
    retryable_exceptions: Tuple[Type[Exception], ...] = field(
        default_factory=lambda: (RetryableException, ConnectionError, TimeoutError)
    )
    on_retry: Optional[Callable[[Exception, int], None]] = None


def calculate_delay(
    attempt: int,
    config: RetryConfig,
) -> float:
    delay = config.initial_delay * (config.exponential_base ** attempt)
    delay = min(delay, config.max_delay)
    
    if config.jitter:
        jitter_range = delay * config.jitter_factor
        delay = delay + random.uniform(-jitter_range, jitter_range)
    
    return max(0.0, delay)


def should_retry(
    exception: Exception,
    attempt: int,
    config: RetryConfig,
) -> bool:
    if attempt >= config.max_retries:
        return False
    
    if isinstance(exception, RetryableException):
        return exception.should_retry()
    
    return isinstance(exception, config.retryable_exceptions)


def retry(
    max_retries: int = 3,
    initial_delay: float = 1.0,
    max_delay: float = 60.0,
    exponential_base: float = 2.0,
    jitter: bool = True,
    retryable_exceptions: Optional[Tuple[Type[Exception], ...]] = None,
    on_retry: Optional[Callable[[Exception, int], None]] = None,
) -> Callable[[F], F]:
    if retryable_exceptions is None:
        retryable_exceptions = (RetryableException, ConnectionError, TimeoutError)
    
    config = RetryConfig(
        max_retries=max_retries,
        initial_delay=initial_delay,
        max_delay=max_delay,
        exponential_base=exponential_base,
        jitter=jitter,
        retryable_exceptions=retryable_exceptions,
        on_retry=on_retry,
    )
    
    def decorator(func: F) -> F:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exception: Optional[Exception] = None
            
            for attempt in range(config.max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    
                    if not should_retry(e, attempt, config):
                        raise
                    
                    if isinstance(e, RetryableException):
                        e.increment_retry()
                    
                    delay = calculate_delay(attempt, config)
                    
                    logger.warning(
                        f"Retry attempt {attempt + 1}/{config.max_retries} for {func.__name__} "
                        f"after {delay:.2f}s delay. Error: {str(e)}"
                    )
                    
                    if config.on_retry:
                        config.on_retry(e, attempt)
                    
                    time.sleep(delay)
            
            if last_exception:
                raise last_exception
            raise RuntimeError("Unexpected retry loop exit")
        
        return wrapper  # type: ignore
    
    return decorator


def async_retry(
    max_retries: int = 3,
    initial_delay: float = 1.0,
    max_delay: float = 60.0,
    exponential_base: float = 2.0,
    jitter: bool = True,
    retryable_exceptions: Optional[Tuple[Type[Exception], ...]] = None,
    on_retry: Optional[Callable[[Exception, int], None]] = None,
) -> Callable[[F], F]:
    if retryable_exceptions is None:
        retryable_exceptions = (RetryableException, ConnectionError, TimeoutError)
    
    config = RetryConfig(
        max_retries=max_retries,
        initial_delay=initial_delay,
        max_delay=max_delay,
        exponential_base=exponential_base,
        jitter=jitter,
        retryable_exceptions=retryable_exceptions,
        on_retry=on_retry,
    )
    
    def decorator(func: F) -> F:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exception: Optional[Exception] = None
            
            for attempt in range(config.max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    
                    if not should_retry(e, attempt, config):
                        raise
                    
                    if isinstance(e, RetryableException):
                        e.increment_retry()
                    
                    delay = calculate_delay(attempt, config)
                    
                    logger.warning(
                        f"Async retry attempt {attempt + 1}/{config.max_retries} for {func.__name__} "
                        f"after {delay:.2f}s delay. Error: {str(e)}"
                    )
                    
                    if config.on_retry:
                        config.on_retry(e, attempt)
                    
                    await asyncio.sleep(delay)
            
            if last_exception:
                raise last_exception
            raise RuntimeError("Unexpected retry loop exit")
        
        return wrapper  # type: ignore
    
    return decorator


class RetryContext:
    def __init__(self, config: RetryConfig):
        self.config = config
        self.attempt = 0
        self.last_exception: Optional[Exception] = None
    
    def should_continue(self) -> bool:
        return self.attempt <= self.config.max_retries
    
    def record_failure(self, exception: Exception) -> bool:
        self.last_exception = exception
        
        if not should_retry(exception, self.attempt, self.config):
            return False
        
        if isinstance(exception, RetryableException):
            exception.increment_retry()
        
        return True
    
    def get_delay(self) -> float:
        return calculate_delay(self.attempt, self.config)
    
    def increment(self) -> None:
        self.attempt += 1


def with_retry(
    func: Callable[..., T],
    config: Optional[RetryConfig] = None,
    *args: Any,
    **kwargs: Any,
) -> T:
    if config is None:
        config = RetryConfig()
    
    context = RetryContext(config)
    
    while context.should_continue():
        try:
            return func(*args, **kwargs)
        except Exception as e:
            if not context.record_failure(e):
                raise
            
            delay = context.get_delay()
            
            logger.warning(
                f"Retry attempt {context.attempt + 1}/{config.max_retries} "
                f"after {delay:.2f}s delay. Error: {str(e)}"
            )
            
            if config.on_retry:
                config.on_retry(e, context.attempt)
            
            time.sleep(delay)
            context.increment()
    
    if context.last_exception:
        raise context.last_exception
    raise RuntimeError("Unexpected retry loop exit")


async def async_with_retry(
    func: Callable[..., Any],
    config: Optional[RetryConfig] = None,
    *args: Any,
    **kwargs: Any,
) -> Any:
    if config is None:
        config = RetryConfig()
    
    context = RetryContext(config)
    
    while context.should_continue():
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            if not context.record_failure(e):
                raise
            
            delay = context.get_delay()
            
            logger.warning(
                f"Async retry attempt {context.attempt + 1}/{config.max_retries} "
                f"after {delay:.2f}s delay. Error: {str(e)}"
            )
            
            if config.on_retry:
                config.on_retry(e, context.attempt)
            
            await asyncio.sleep(delay)
            context.increment()
    
    if context.last_exception:
        raise context.last_exception
    raise RuntimeError("Unexpected retry loop exit")
