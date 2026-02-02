from abc import ABC, abstractmethod
from typing import Optional, Dict, Any
from functools import lru_cache
import json
import os

from src.common.config.settings import get_settings
from src.common.config.logging_config import get_logger

logger = get_logger(__name__)


class SecretManager(ABC):
    @abstractmethod
    def get_secret(self, key: str, default: Optional[str] = None) -> Optional[str]:
        raise NotImplementedError("Subclasses must implement get_secret method")
    
    @abstractmethod
    def set_secret(self, key: str, value: str) -> bool:
        raise NotImplementedError("Subclasses must implement set_secret method")
    
    @abstractmethod
    def delete_secret(self, key: str) -> bool:
        raise NotImplementedError("Subclasses must implement delete_secret method")
    
    @abstractmethod
    def list_secrets(self, path: Optional[str] = None) -> list[str]:
        raise NotImplementedError("Subclasses must implement list_secrets method")
    
    def get_secret_dict(self, path: str) -> Dict[str, str]:
        return {}
    
    def health_check(self) -> bool:
        return True


class EnvironmentSecretManager(SecretManager):
    def __init__(self, prefix: str = "ROCM_CICD_"):
        self._prefix = prefix
    
    def get_secret(self, key: str, default: Optional[str] = None) -> Optional[str]:
        env_key = f"{self._prefix}{key.upper()}"
        return os.environ.get(env_key, default)
    
    def set_secret(self, key: str, value: str) -> bool:
        env_key = f"{self._prefix}{key.upper()}"
        os.environ[env_key] = value
        return True
    
    def delete_secret(self, key: str) -> bool:
        env_key = f"{self._prefix}{key.upper()}"
        if env_key in os.environ:
            del os.environ[env_key]
            return True
        return False
    
    def list_secrets(self, path: Optional[str] = None) -> list[str]:
        secrets = []
        for key in os.environ:
            if key.startswith(self._prefix):
                secret_name = key[len(self._prefix):]
                if path is None or secret_name.startswith(path.upper()):
                    secrets.append(secret_name)
        return secrets


class VaultSecretManager(SecretManager):
    def __init__(
        self,
        url: str,
        token: str,
        mount_path: str = "secret",
        namespace: Optional[str] = None,
    ):
        self._url = url
        self._token = token
        self._mount_path = mount_path
        self._namespace = namespace
        self._client = None
        self._initialize_client()
    
    def _initialize_client(self) -> None:
        try:
            import hvac
            self._client = hvac.Client(
                url=self._url,
                token=self._token,
                namespace=self._namespace,
            )
            if not self._client.is_authenticated():
                logger.error("Vault authentication failed")
                self._client = None
        except ImportError:
            logger.warning("hvac library not installed, Vault integration disabled")
            self._client = None
        except Exception as e:
            logger.error(f"Failed to initialize Vault client: {e}")
            self._client = None
    
    def get_secret(self, key: str, default: Optional[str] = None) -> Optional[str]:
        if self._client is None:
            return default
        
        try:
            path_parts = key.rsplit("/", 1)
            if len(path_parts) == 2:
                path, field = path_parts
            else:
                path = key
                field = "value"
            
            response = self._client.secrets.kv.v2.read_secret_version(
                path=path,
                mount_point=self._mount_path,
            )
            
            data = response.get("data", {}).get("data", {})
            return data.get(field, default)
        except Exception as e:
            logger.warning(f"Failed to get secret '{key}' from Vault: {e}")
            return default
    
    def set_secret(self, key: str, value: str) -> bool:
        if self._client is None:
            return False
        
        try:
            path_parts = key.rsplit("/", 1)
            if len(path_parts) == 2:
                path, field = path_parts
            else:
                path = key
                field = "value"
            
            try:
                existing = self._client.secrets.kv.v2.read_secret_version(
                    path=path,
                    mount_point=self._mount_path,
                )
                data = existing.get("data", {}).get("data", {})
            except Exception:
                data = {}
            
            data[field] = value
            
            self._client.secrets.kv.v2.create_or_update_secret(
                path=path,
                secret=data,
                mount_point=self._mount_path,
            )
            return True
        except Exception as e:
            logger.error(f"Failed to set secret '{key}' in Vault: {e}")
            return False
    
    def delete_secret(self, key: str) -> bool:
        if self._client is None:
            return False
        
        try:
            self._client.secrets.kv.v2.delete_metadata_and_all_versions(
                path=key,
                mount_point=self._mount_path,
            )
            return True
        except Exception as e:
            logger.error(f"Failed to delete secret '{key}' from Vault: {e}")
            return False
    
    def list_secrets(self, path: Optional[str] = None) -> list[str]:
        if self._client is None:
            return []
        
        try:
            response = self._client.secrets.kv.v2.list_secrets(
                path=path or "",
                mount_point=self._mount_path,
            )
            return response.get("data", {}).get("keys", [])
        except Exception as e:
            logger.warning(f"Failed to list secrets from Vault: {e}")
            return []
    
    def get_secret_dict(self, path: str) -> Dict[str, str]:
        if self._client is None:
            return {}
        
        try:
            response = self._client.secrets.kv.v2.read_secret_version(
                path=path,
                mount_point=self._mount_path,
            )
            return response.get("data", {}).get("data", {})
        except Exception as e:
            logger.warning(f"Failed to get secret dict from Vault at '{path}': {e}")
            return {}
    
    def health_check(self) -> bool:
        if self._client is None:
            return False
        try:
            return self._client.is_authenticated()
        except Exception:
            return False


class KubernetesSecretManager(SecretManager):
    def __init__(
        self,
        namespace: str = "default",
        config_path: Optional[str] = None,
    ):
        self._namespace = namespace
        self._config_path = config_path
        self._client = None
        self._initialize_client()
    
    def _initialize_client(self) -> None:
        try:
            from kubernetes import client, config
            
            if self._config_path:
                config.load_kube_config(config_file=self._config_path)
            else:
                try:
                    config.load_incluster_config()
                except config.ConfigException:
                    config.load_kube_config()
            
            self._client = client.CoreV1Api()
        except ImportError:
            logger.warning("kubernetes library not installed")
            self._client = None
        except Exception as e:
            logger.error(f"Failed to initialize Kubernetes client: {e}")
            self._client = None
    
    def get_secret(self, key: str, default: Optional[str] = None) -> Optional[str]:
        if self._client is None:
            return default
        
        try:
            parts = key.split("/")
            if len(parts) >= 2:
                secret_name = parts[0]
                data_key = "/".join(parts[1:])
            else:
                return default
            
            secret = self._client.read_namespaced_secret(
                name=secret_name,
                namespace=self._namespace,
            )
            
            if secret.data and data_key in secret.data:
                import base64
                return base64.b64decode(secret.data[data_key]).decode("utf-8")
            
            return default
        except Exception as e:
            logger.warning(f"Failed to get secret '{key}' from Kubernetes: {e}")
            return default
    
    def set_secret(self, key: str, value: str) -> bool:
        if self._client is None:
            return False
        
        try:
            from kubernetes import client
            import base64
            
            parts = key.split("/")
            if len(parts) >= 2:
                secret_name = parts[0]
                data_key = "/".join(parts[1:])
            else:
                return False
            
            encoded_value = base64.b64encode(value.encode("utf-8")).decode("utf-8")
            
            try:
                secret = self._client.read_namespaced_secret(
                    name=secret_name,
                    namespace=self._namespace,
                )
                if secret.data is None:
                    secret.data = {}
                secret.data[data_key] = encoded_value
                
                self._client.replace_namespaced_secret(
                    name=secret_name,
                    namespace=self._namespace,
                    body=secret,
                )
            except Exception:
                secret = client.V1Secret(
                    metadata=client.V1ObjectMeta(name=secret_name),
                    data={data_key: encoded_value},
                )
                self._client.create_namespaced_secret(
                    namespace=self._namespace,
                    body=secret,
                )
            
            return True
        except Exception as e:
            logger.error(f"Failed to set secret '{key}' in Kubernetes: {e}")
            return False
    
    def delete_secret(self, key: str) -> bool:
        if self._client is None:
            return False
        
        try:
            parts = key.split("/")
            secret_name = parts[0]
            
            self._client.delete_namespaced_secret(
                name=secret_name,
                namespace=self._namespace,
            )
            return True
        except Exception as e:
            logger.error(f"Failed to delete secret '{key}' from Kubernetes: {e}")
            return False
    
    def list_secrets(self, path: Optional[str] = None) -> list[str]:
        if self._client is None:
            return []
        
        try:
            secrets = self._client.list_namespaced_secret(
                namespace=self._namespace,
            )
            secret_names = [s.metadata.name for s in secrets.items]
            
            if path:
                secret_names = [n for n in secret_names if n.startswith(path)]
            
            return secret_names
        except Exception as e:
            logger.warning(f"Failed to list secrets from Kubernetes: {e}")
            return []
    
    def health_check(self) -> bool:
        if self._client is None:
            return False
        try:
            self._client.list_namespaced_secret(namespace=self._namespace, limit=1)
            return True
        except Exception:
            return False


class ChainedSecretManager(SecretManager):
    def __init__(self, managers: list[SecretManager]):
        self._managers = managers
    
    def get_secret(self, key: str, default: Optional[str] = None) -> Optional[str]:
        for manager in self._managers:
            value = manager.get_secret(key)
            if value is not None:
                return value
        return default
    
    def set_secret(self, key: str, value: str) -> bool:
        if self._managers:
            return self._managers[0].set_secret(key, value)
        return False
    
    def delete_secret(self, key: str) -> bool:
        success = False
        for manager in self._managers:
            if manager.delete_secret(key):
                success = True
        return success
    
    def list_secrets(self, path: Optional[str] = None) -> list[str]:
        all_secrets = set()
        for manager in self._managers:
            all_secrets.update(manager.list_secrets(path))
        return list(all_secrets)
    
    def health_check(self) -> bool:
        return any(m.health_check() for m in self._managers)


class SecretManagerFactory:
    @staticmethod
    def create(manager_type: str, **kwargs: Any) -> SecretManager:
        if manager_type == "environment":
            return EnvironmentSecretManager(
                prefix=kwargs.get("prefix", "ROCM_CICD_")
            )
        elif manager_type == "vault":
            return VaultSecretManager(
                url=kwargs.get("url", "http://localhost:8200"),
                token=kwargs.get("token", ""),
                mount_path=kwargs.get("mount_path", "secret"),
                namespace=kwargs.get("namespace"),
            )
        elif manager_type == "kubernetes":
            return KubernetesSecretManager(
                namespace=kwargs.get("namespace", "default"),
                config_path=kwargs.get("config_path"),
            )
        else:
            raise ValueError(f"Unknown secret manager type: {manager_type}")
    
    @staticmethod
    def create_from_settings() -> SecretManager:
        settings = get_settings()
        
        managers: list[SecretManager] = []
        
        managers.append(EnvironmentSecretManager())
        
        if settings.vault_enabled and settings.vault_token:
            vault_manager = VaultSecretManager(
                url=settings.vault_url,
                token=settings.vault_token.get_secret_value(),
                mount_path=settings.vault_mount_path,
            )
            if vault_manager.health_check():
                managers.insert(0, vault_manager)
        
        if len(managers) == 1:
            return managers[0]
        
        return ChainedSecretManager(managers)


@lru_cache()
def get_secret_manager() -> SecretManager:
    return SecretManagerFactory.create_from_settings()
