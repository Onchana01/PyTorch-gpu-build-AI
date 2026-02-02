import hashlib
from typing import Any, Union, Optional, List
import json
from pathlib import Path


def compute_hash(
    data: Union[str, bytes],
    algorithm: str = "sha256",
) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    
    hash_obj = hashlib.new(algorithm)
    hash_obj.update(data)
    
    return hash_obj.hexdigest()


def compute_signature(
    *components: Any,
    algorithm: str = "sha256",
    separator: str = "|",
) -> str:
    normalized_parts: List[str] = []
    
    for component in components:
        if component is None:
            normalized_parts.append("null")
        elif isinstance(component, (dict, list)):
            normalized_parts.append(json.dumps(component, sort_keys=True, default=str))
        elif isinstance(component, bytes):
            normalized_parts.append(component.hex())
        else:
            normalized_parts.append(str(component))
    
    combined = separator.join(normalized_parts)
    
    return compute_hash(combined, algorithm)


def hash_dict(
    data: dict,
    algorithm: str = "sha256",
    exclude_keys: Optional[List[str]] = None,
) -> str:
    if exclude_keys:
        filtered_data = {k: v for k, v in data.items() if k not in exclude_keys}
    else:
        filtered_data = data
    
    normalized = json.dumps(filtered_data, sort_keys=True, default=str)
    
    return compute_hash(normalized, algorithm)


def hash_file(
    file_path: Union[str, Path],
    algorithm: str = "sha256",
    chunk_size: int = 8192,
) -> str:
    file_path = Path(file_path)
    
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")
    
    hash_obj = hashlib.new(algorithm)
    
    with open(file_path, "rb") as f:
        while chunk := f.read(chunk_size):
            hash_obj.update(chunk)
    
    return hash_obj.hexdigest()


def compute_checksum(
    file_path: Union[str, Path],
    algorithm: str = "md5",
) -> str:
    return hash_file(file_path, algorithm)


def compute_directory_hash(
    directory_path: Union[str, Path],
    algorithm: str = "sha256",
    include_patterns: Optional[List[str]] = None,
    exclude_patterns: Optional[List[str]] = None,
) -> str:
    directory_path = Path(directory_path)
    
    if not directory_path.is_dir():
        raise NotADirectoryError(f"Not a directory: {directory_path}")
    
    file_hashes: List[str] = []
    
    for file_path in sorted(directory_path.rglob("*")):
        if not file_path.is_file():
            continue
        
        relative_path = str(file_path.relative_to(directory_path))
        
        if include_patterns:
            if not any(file_path.match(pattern) for pattern in include_patterns):
                continue
        
        if exclude_patterns:
            if any(file_path.match(pattern) for pattern in exclude_patterns):
                continue
        
        file_hash = hash_file(file_path, algorithm)
        file_hashes.append(f"{relative_path}:{file_hash}")
    
    combined = "\n".join(file_hashes)
    
    return compute_hash(combined, algorithm)


def normalize_error_message(
    error_message: str,
) -> str:
    import re
    
    normalized = error_message.strip()
    
    normalized = re.sub(r"\b\d+\b", "<NUM>", normalized)
    
    normalized = re.sub(
        r"0x[0-9a-fA-F]+",
        "<ADDR>",
        normalized
    )
    
    path_pattern = r"(?:/[^/\s]+)+(?:\.[a-zA-Z0-9]+)?|(?:[A-Za-z]:\\[^\s]+)"
    normalized = re.sub(path_pattern, "<PATH>", normalized)
    
    normalized = re.sub(
        r"\b[a-f0-9]{32,64}\b",
        "<HASH>",
        normalized
    )
    
    return normalized


def compute_error_signature(
    error_message: str,
    error_type: Optional[str] = None,
    component: Optional[str] = None,
    algorithm: str = "sha256",
) -> str:
    normalized_message = normalize_error_message(error_message)
    
    components = [normalized_message]
    
    if error_type:
        components.insert(0, error_type)
    
    if component:
        components.insert(0, component)
    
    return compute_signature(*components, algorithm=algorithm)


def verify_checksum(
    file_path: Union[str, Path],
    expected_checksum: str,
    algorithm: str = "sha256",
) -> bool:
    actual_checksum = compute_checksum(file_path, algorithm)
    return actual_checksum.lower() == expected_checksum.lower()


def compute_content_hash(
    content: Union[str, bytes, dict, list],
    algorithm: str = "sha256",
) -> str:
    if isinstance(content, (dict, list)):
        serialized = json.dumps(content, sort_keys=True, default=str)
        return compute_hash(serialized, algorithm)
    elif isinstance(content, str):
        return compute_hash(content, algorithm)
    else:
        return compute_hash(content, algorithm)


class IncrementalHasher:
    def __init__(self, algorithm: str = "sha256"):
        self._hash_obj = hashlib.new(algorithm)
        self._algorithm = algorithm
    
    def update(self, data: Union[str, bytes]) -> None:
        if isinstance(data, str):
            data = data.encode("utf-8")
        self._hash_obj.update(data)
    
    def update_file(self, file_path: Union[str, Path], chunk_size: int = 8192) -> None:
        with open(file_path, "rb") as f:
            while chunk := f.read(chunk_size):
                self._hash_obj.update(chunk)
    
    def hexdigest(self) -> str:
        return self._hash_obj.hexdigest()
    
    def digest(self) -> bytes:
        return self._hash_obj.digest()
    
    def copy(self) -> "IncrementalHasher":
        new_hasher = IncrementalHasher(self._algorithm)
        new_hasher._hash_obj = self._hash_obj.copy()
        return new_hasher
