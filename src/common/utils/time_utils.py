from datetime import datetime, timedelta, timezone
from typing import Optional, Union
import time


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def calculate_duration(
    start_time: datetime,
    end_time: Optional[datetime] = None,
) -> timedelta:
    if end_time is None:
        end_time = utc_now()
    
    if start_time.tzinfo is None:
        start_time = start_time.replace(tzinfo=timezone.utc)
    if end_time.tzinfo is None:
        end_time = end_time.replace(tzinfo=timezone.utc)
    
    return end_time - start_time


def format_duration(
    duration: Union[timedelta, float, int],
    precision: int = 2,
) -> str:
    if isinstance(duration, timedelta):
        total_seconds = duration.total_seconds()
    else:
        total_seconds = float(duration)
    
    if total_seconds < 0:
        return "0s"
    
    days = int(total_seconds // 86400)
    remaining = total_seconds % 86400
    
    hours = int(remaining // 3600)
    remaining = remaining % 3600
    
    minutes = int(remaining // 60)
    seconds = remaining % 60
    
    parts = []
    
    if days > 0:
        parts.append(f"{days}d")
    if hours > 0:
        parts.append(f"{hours}h")
    if minutes > 0:
        parts.append(f"{minutes}m")
    
    if seconds > 0 or not parts:
        if seconds == int(seconds):
            parts.append(f"{int(seconds)}s")
        else:
            parts.append(f"{seconds:.{precision}f}s")
    
    return " ".join(parts)


def is_timeout(
    start_time: datetime,
    timeout_seconds: Union[int, float],
    current_time: Optional[datetime] = None,
) -> bool:
    if current_time is None:
        current_time = utc_now()
    
    if start_time.tzinfo is None:
        start_time = start_time.replace(tzinfo=timezone.utc)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)
    
    elapsed = (current_time - start_time).total_seconds()
    
    return elapsed >= timeout_seconds


def parse_iso_datetime(
    datetime_string: str,
) -> datetime:
    formats = [
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
    ]
    
    for fmt in formats:
        try:
            dt = datetime.strptime(datetime_string.replace("Z", "+0000"), fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    
    raise ValueError(f"Unable to parse datetime string: {datetime_string}")


def to_iso_format(
    dt: datetime,
    include_microseconds: bool = True,
) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    
    if include_microseconds:
        return dt.isoformat()
    else:
        return dt.strftime("%Y-%m-%dT%H:%M:%S%z")


def get_timestamp() -> float:
    return time.time()


def timestamp_to_datetime(
    timestamp: float,
) -> datetime:
    return datetime.fromtimestamp(timestamp, tz=timezone.utc)


def datetime_to_timestamp(
    dt: datetime,
) -> float:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def add_duration(
    base_time: datetime,
    seconds: float = 0,
    minutes: float = 0,
    hours: float = 0,
    days: float = 0,
) -> datetime:
    total_seconds = seconds + (minutes * 60) + (hours * 3600) + (days * 86400)
    return base_time + timedelta(seconds=total_seconds)


def subtract_duration(
    base_time: datetime,
    seconds: float = 0,
    minutes: float = 0,
    hours: float = 0,
    days: float = 0,
) -> datetime:
    total_seconds = seconds + (minutes * 60) + (hours * 3600) + (days * 86400)
    return base_time - timedelta(seconds=total_seconds)


def time_until(
    target_time: datetime,
    from_time: Optional[datetime] = None,
) -> timedelta:
    if from_time is None:
        from_time = utc_now()
    
    if target_time.tzinfo is None:
        target_time = target_time.replace(tzinfo=timezone.utc)
    if from_time.tzinfo is None:
        from_time = from_time.replace(tzinfo=timezone.utc)
    
    return target_time - from_time


def time_since(
    past_time: datetime,
    from_time: Optional[datetime] = None,
) -> timedelta:
    if from_time is None:
        from_time = utc_now()
    
    if past_time.tzinfo is None:
        past_time = past_time.replace(tzinfo=timezone.utc)
    if from_time.tzinfo is None:
        from_time = from_time.replace(tzinfo=timezone.utc)
    
    return from_time - past_time


def is_within_range(
    dt: datetime,
    start: datetime,
    end: datetime,
) -> bool:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    
    return start <= dt <= end


def get_age_seconds(
    dt: datetime,
    reference_time: Optional[datetime] = None,
) -> float:
    if reference_time is None:
        reference_time = utc_now()
    
    duration = calculate_duration(dt, reference_time)
    return duration.total_seconds()


def format_relative_time(
    dt: datetime,
    reference_time: Optional[datetime] = None,
) -> str:
    if reference_time is None:
        reference_time = utc_now()
    
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    if reference_time.tzinfo is None:
        reference_time = reference_time.replace(tzinfo=timezone.utc)
    
    diff = reference_time - dt
    seconds = diff.total_seconds()
    
    if seconds < 0:
        return "in the future"
    
    if seconds < 60:
        return "just now"
    elif seconds < 3600:
        minutes = int(seconds / 60)
        return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
    elif seconds < 86400:
        hours = int(seconds / 3600)
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    elif seconds < 604800:
        days = int(seconds / 86400)
        return f"{days} day{'s' if days != 1 else ''} ago"
    else:
        weeks = int(seconds / 604800)
        return f"{weeks} week{'s' if weeks != 1 else ''} ago"


class Timer:
    def __init__(self):
        self._start_time: Optional[float] = None
        self._end_time: Optional[float] = None
        self._paused_time: float = 0.0
        self._pause_start: Optional[float] = None
    
    def start(self) -> "Timer":
        self._start_time = time.perf_counter()
        self._end_time = None
        self._paused_time = 0.0
        self._pause_start = None
        return self
    
    def stop(self) -> float:
        if self._start_time is None:
            raise RuntimeError("Timer was never started")
        
        if self._pause_start is not None:
            self.resume()
        
        self._end_time = time.perf_counter()
        return self.elapsed
    
    def pause(self) -> None:
        if self._pause_start is None:
            self._pause_start = time.perf_counter()
    
    def resume(self) -> None:
        if self._pause_start is not None:
            self._paused_time += time.perf_counter() - self._pause_start
            self._pause_start = None
    
    @property
    def elapsed(self) -> float:
        if self._start_time is None:
            return 0.0
        
        end = self._end_time or time.perf_counter()
        pause_time = self._paused_time
        
        if self._pause_start is not None:
            pause_time += time.perf_counter() - self._pause_start
        
        return end - self._start_time - pause_time
    
    @property
    def elapsed_formatted(self) -> str:
        return format_duration(self.elapsed)
    
    def __enter__(self) -> "Timer":
        return self.start()
    
    def __exit__(self, *args) -> None:
        self.stop()
