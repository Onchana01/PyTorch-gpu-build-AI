from pathlib import Path
from typing import Optional, List, Union, BinaryIO
import shutil
import tempfile
import os
import stat
from contextlib import contextmanager

from src.common.config.logging_config import get_logger


logger = get_logger(__name__)


def safe_read_file(
    file_path: Union[str, Path],
    encoding: str = "utf-8",
    default: Optional[str] = None,
) -> Optional[str]:
    file_path = Path(file_path)
    
    try:
        if not file_path.exists():
            logger.debug(f"File does not exist: {file_path}")
            return default
        
        if not file_path.is_file():
            logger.warning(f"Path is not a file: {file_path}")
            return default
        
        with open(file_path, "r", encoding=encoding) as f:
            return f.read()
    except PermissionError:
        logger.error(f"Permission denied reading file: {file_path}")
        return default
    except UnicodeDecodeError:
        logger.error(f"Failed to decode file with encoding {encoding}: {file_path}")
        return default
    except Exception as e:
        logger.error(f"Unexpected error reading file {file_path}: {e}")
        return default


def safe_read_binary(
    file_path: Union[str, Path],
    default: Optional[bytes] = None,
) -> Optional[bytes]:
    file_path = Path(file_path)
    
    try:
        if not file_path.exists():
            return default
        
        with open(file_path, "rb") as f:
            return f.read()
    except Exception as e:
        logger.error(f"Error reading binary file {file_path}: {e}")
        return default


def safe_write_file(
    file_path: Union[str, Path],
    content: Union[str, bytes],
    encoding: str = "utf-8",
    create_dirs: bool = True,
    atomic: bool = True,
) -> bool:
    file_path = Path(file_path)
    
    try:
        if create_dirs:
            file_path.parent.mkdir(parents=True, exist_ok=True)
        
        if atomic:
            temp_fd, temp_path = tempfile.mkstemp(
                dir=file_path.parent,
                prefix=f".{file_path.name}.",
                suffix=".tmp"
            )
            
            try:
                if isinstance(content, str):
                    with os.fdopen(temp_fd, "w", encoding=encoding) as f:
                        f.write(content)
                else:
                    with os.fdopen(temp_fd, "wb") as f:
                        f.write(content)
                
                shutil.move(temp_path, file_path)
                return True
            except Exception:
                os.unlink(temp_path)
                raise
        else:
            mode = "wb" if isinstance(content, bytes) else "w"
            kwargs = {} if isinstance(content, bytes) else {"encoding": encoding}
            
            with open(file_path, mode, **kwargs) as f:
                f.write(content)
            
            return True
    except PermissionError:
        logger.error(f"Permission denied writing to file: {file_path}")
        return False
    except Exception as e:
        logger.error(f"Error writing to file {file_path}: {e}")
        return False


def create_temp_dir(
    prefix: str = "rocm_cicd_",
    base_dir: Optional[Union[str, Path]] = None,
) -> Path:
    if base_dir:
        base_dir = Path(base_dir)
        base_dir.mkdir(parents=True, exist_ok=True)
    
    temp_dir = tempfile.mkdtemp(prefix=prefix, dir=base_dir)
    
    logger.debug(f"Created temporary directory: {temp_dir}")
    
    return Path(temp_dir)


def cleanup_temp_files(
    directory: Union[str, Path],
    ignore_errors: bool = True,
) -> bool:
    directory = Path(directory)
    
    if not directory.exists():
        return True
    
    try:
        def remove_readonly(func, path, exc_info):
            os.chmod(path, stat.S_IWRITE)
            func(path)
        
        shutil.rmtree(directory, onerror=remove_readonly if ignore_errors else None)
        logger.debug(f"Cleaned up temporary directory: {directory}")
        return True
    except Exception as e:
        if not ignore_errors:
            logger.error(f"Error cleaning up directory {directory}: {e}")
            return False
        logger.warning(f"Partial cleanup of directory {directory}: {e}")
        return False


def ensure_directory(
    directory: Union[str, Path],
    mode: int = 0o755,
) -> Path:
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True, mode=mode)
    return directory


def get_file_size(
    file_path: Union[str, Path],
) -> int:
    file_path = Path(file_path)
    
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")
    
    return file_path.stat().st_size


def copy_file(
    source: Union[str, Path],
    destination: Union[str, Path],
    create_dirs: bool = True,
    preserve_metadata: bool = True,
) -> bool:
    source = Path(source)
    destination = Path(destination)
    
    try:
        if not source.exists():
            logger.error(f"Source file does not exist: {source}")
            return False
        
        if create_dirs:
            destination.parent.mkdir(parents=True, exist_ok=True)
        
        if preserve_metadata:
            shutil.copy2(source, destination)
        else:
            shutil.copy(source, destination)
        
        return True
    except Exception as e:
        logger.error(f"Error copying file from {source} to {destination}: {e}")
        return False


def move_file(
    source: Union[str, Path],
    destination: Union[str, Path],
    create_dirs: bool = True,
) -> bool:
    source = Path(source)
    destination = Path(destination)
    
    try:
        if not source.exists():
            logger.error(f"Source file does not exist: {source}")
            return False
        
        if create_dirs:
            destination.parent.mkdir(parents=True, exist_ok=True)
        
        shutil.move(source, destination)
        return True
    except Exception as e:
        logger.error(f"Error moving file from {source} to {destination}: {e}")
        return False


def list_files(
    directory: Union[str, Path],
    pattern: str = "*",
    recursive: bool = False,
) -> List[Path]:
    directory = Path(directory)
    
    if not directory.is_dir():
        return []
    
    if recursive:
        return list(directory.rglob(pattern))
    else:
        return list(directory.glob(pattern))


def get_directory_size(
    directory: Union[str, Path],
) -> int:
    directory = Path(directory)
    
    if not directory.is_dir():
        return 0
    
    total_size = 0
    for file_path in directory.rglob("*"):
        if file_path.is_file():
            total_size += file_path.stat().st_size
    
    return total_size


@contextmanager
def temp_directory(
    prefix: str = "rocm_cicd_",
    cleanup: bool = True,
):
    temp_dir = create_temp_dir(prefix=prefix)
    
    try:
        yield temp_dir
    finally:
        if cleanup:
            cleanup_temp_files(temp_dir, ignore_errors=True)


@contextmanager
def temp_file(
    prefix: str = "rocm_cicd_",
    suffix: str = "",
    mode: str = "w",
    encoding: Optional[str] = "utf-8",
    delete: bool = True,
):
    fd, path = tempfile.mkstemp(prefix=prefix, suffix=suffix)
    file_path = Path(path)
    
    try:
        if "b" in mode:
            with os.fdopen(fd, mode) as f:
                yield f, file_path
        else:
            with os.fdopen(fd, mode, encoding=encoding) as f:
                yield f, file_path
    finally:
        if delete and file_path.exists():
            file_path.unlink()


def find_files_by_extension(
    directory: Union[str, Path],
    extensions: List[str],
    recursive: bool = True,
) -> List[Path]:
    directory = Path(directory)
    
    if not directory.is_dir():
        return []
    
    normalized_extensions = [
        ext if ext.startswith(".") else f".{ext}" 
        for ext in extensions
    ]
    
    result: List[Path] = []
    
    iterator = directory.rglob("*") if recursive else directory.glob("*")
    
    for file_path in iterator:
        if file_path.is_file() and file_path.suffix.lower() in normalized_extensions:
            result.append(file_path)
    
    return result


def safe_delete_file(
    file_path: Union[str, Path],
    ignore_errors: bool = True,
) -> bool:
    file_path = Path(file_path)
    
    try:
        if file_path.exists():
            file_path.unlink()
        return True
    except Exception as e:
        if not ignore_errors:
            logger.error(f"Error deleting file {file_path}: {e}")
            return False
        logger.warning(f"Could not delete file {file_path}: {e}")
        return False
