from enum import Enum, IntEnum
from typing import Final


class BuildStatus(str, Enum):
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    SUCCESS = "success"
    FAILURE = "failure"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"
    SKIPPED = "skipped"


class FailureCategory(str, Enum):
    CONFIGURATION = "configuration"
    CONFIGURATION_ERROR = "configuration_error"
    COMPILATION = "compilation"
    COMPILATION_ERROR = "compilation_error"
    LINKING = "linking"
    LINKER_ERROR = "linker_error"
    RUNTIME = "runtime"
    RUNTIME_ERROR = "runtime_error"
    TEST = "test"
    TEST_FAILURE = "test_failure"
    ENVIRONMENT = "environment"
    INFRASTRUCTURE = "infrastructure"
    GPU_ERROR = "gpu_error"
    DEPENDENCY_ERROR = "dependency_error"
    TIMEOUT = "timeout"
    UNKNOWN = "unknown"


class SeverityLevel(str, Enum):
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"
    FATAL = "fatal"


class Priority(IntEnum):
    LOW = 10
    NORMAL = 100
    HIGH = 500
    CRITICAL = 1000


class ROCmVersion(str, Enum):
    ROCM_5_6 = "5.6"
    ROCM_5_7 = "5.7"
    ROCM_6_0 = "6.0"
    ROCM_6_1 = "6.1"
    ROCM_6_2 = "6.2"


class GPUArchitecture(str, Enum):
    GFX900 = "gfx900"
    GFX906 = "gfx906"
    GFX908 = "gfx908"
    GFX90A = "gfx90a"
    GFX1030 = "gfx1030"
    GFX1100 = "gfx1100"
    GFX1101 = "gfx1101"


class BuildType(str, Enum):
    DEBUG = "debug"
    RELEASE = "release"
    RELEASE_WITH_DEBUG = "release-with-debug-info"


class TestStatus(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    ERROR = "error"
    XFAIL = "xfail"
    XPASS = "xpass"


class NotificationChannel(str, Enum):
    GITHUB_PR = "github_pr"
    GITHUB_STATUS = "github_status"
    EMAIL = "email"
    SLACK = "slack"
    TEAMS = "teams"
    WEBHOOK = "webhook"


class FixType(str, Enum):
    DEPENDENCY_INSTALL = "dependency_install"
    CONFIG_CHANGE = "config_change"
    CODE_PATCH = "code_patch"
    ENVIRONMENT_MODIFICATION = "environment_modification"
    DRIVER_UPDATE = "driver_update"
    VERSION_PIN = "version_pin"


class CompilerType(str, Enum):
    GCC = "gcc"
    CLANG = "clang"
    HIPCC = "hipcc"
    NVCC = "nvcc"


class LogFormat(str, Enum):
    CMAKE = "cmake"
    COMPILER = "compiler"
    LINKER = "linker"
    PYTHON_TRACEBACK = "python_traceback"
    ROCM_DIAGNOSTIC = "rocm_diagnostic"
    GENERIC = "generic"


DEFAULT_TIMEOUT_SECONDS: Final[int] = 3600
BUILD_TIMEOUT_SECONDS: Final[int] = 7200
TEST_TIMEOUT_SECONDS: Final[int] = 1800
ANALYSIS_TIMEOUT_SECONDS: Final[int] = 300

MAX_RETRY_ATTEMPTS: Final[int] = 3
RETRY_DELAY_SECONDS: Final[int] = 30

ARTIFACT_RETENTION_DAYS_RELEASE: Final[int] = 90
ARTIFACT_RETENTION_DAYS_PR: Final[int] = 7

CACHE_TTL_SECONDS: Final[int] = 3600
PATTERN_CACHE_SIZE: Final[int] = 1000

GPU_MEMORY_THRESHOLD_PERCENT: Final[float] = 90.0
CPU_MEMORY_THRESHOLD_PERCENT: Final[float] = 85.0
DISK_SPACE_THRESHOLD_GB: Final[float] = 10.0

BUILD_SUCCESS_RATE_THRESHOLD: Final[float] = 0.70
QUEUE_WAIT_TIME_THRESHOLD_MINUTES: Final[int] = 30

JWT_ALGORITHM: Final[str] = "HS256"
JWT_EXPIRATION_HOURS: Final[int] = 24
API_RATE_LIMIT_PER_MINUTE: Final[int] = 100

SUPPORTED_PYTHON_VERSIONS: Final[tuple] = ("3.8", "3.9", "3.10", "3.11", "3.12")
