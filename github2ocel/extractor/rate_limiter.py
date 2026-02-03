import time
import logging
import re
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, Callable
from dataclasses import dataclass
from threading import Lock, RLock
from functools import wraps
import requests # Importamos para typing

logger = logging.getLogger(__name__)

@dataclass
class RateLimitStatus:
    remaining: int
    limit: int
    reset_at: datetime
    used: int
    resource: str

    def __str__(self):
        reset_str = self.reset_at.strftime("%H:%M:%S")
        return f"{self.resource}: {self.remaining}/{self.limit} (resets at {reset_str})"

    def time_until_reset(self) -> float:
        now = datetime.now(timezone.utc)
        delta = (self.reset_at - now).total_seconds()
        return max(0, delta)

    def is_exhausted(self, buffer: int) -> bool:
        return self.remaining <= buffer

class RateLimiter:
    _instance = None
    _creation_lock = Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._creation_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._initialized = True
        self._state_lock = RLock()
        self._status: Dict[str, RateLimitStatus] = {}
        self._last_known_limits: Dict[str, int] = {} 

        # Configuración
        self.max_wait_time = 600
        self.min_sleep_between_requests = 0.1
        
        # Buffer fijo base, pero ahora usaremos dinámico
        self._base_safety_buffer = 100 

        self.stats = {
            'total_requests': 0,
            'total_waits': 0,
            'total_wait_time': 0.0,
            'rate_limit_hits': 0
        }
        logger.info("RateLimiter initialized (Battle Hardened v3.0)")

    def _get_dynamic_buffer(self, limit: int) -> int:
        """
        Calcula un buffer seguro: 
        - 10% del límite para recursos pequeños (ej. Search: 30 -> 3)
        - Tope de 100 para recursos grandes (ej. Core: 5000 -> 100)
        """
        if limit <= 0: return 5
        return min(self._base_safety_buffer, int(limit * 0.10))

    def update_from_response(self, response: requests.Response, resource: str = 'core'):
        """Actualiza el estado basado en headers reales."""
        # 1. Corrección: Contamos el request siempre, tenga headers o no
        with self._state_lock:
            self.stats['total_requests'] += 1

        headers = response.headers
        # Case-insensitive access
        remaining = headers.get('x-ratelimit-remaining')
        limit = headers.get('x-ratelimit-limit')
        reset = headers.get('x-ratelimit-reset')
        used = headers.get('x-ratelimit-used')

        if remaining and limit and reset:
            try:
                with self._state_lock:
                    limit_int = int(limit)
                    self._last_known_limits[resource] = limit_int

                    status = RateLimitStatus(
                        remaining=int(remaining),
                        limit=limit_int,
                        reset_at=datetime.fromtimestamp(int(reset), tz=timezone.utc),
                        used=int(used) if used else limit_int - int(remaining),
                        resource=resource
                    )
                    self._status[resource] = status
                    
                    # Log si estamos peligrosamente bajos (usando buffer dinámico)
                    buffer = self._get_dynamic_buffer(limit_int)
                    if status.remaining < buffer:
                        logger.warning(f"📉 Rate limit low for {resource}: {status.remaining}/{status.limit}")

            except (ValueError, TypeError) as e:
                logger.warning(f"Failed to parse rate limit headers: {e}")

    def update_from_graphql_error(self, error: Dict[str, Any], resource: str = 'graphql'):
        message = error.get('message', '')
        reset_time = self._parse_reset_time_from_message(message)

        if reset_time:
            with self._state_lock:
                known_limit = self._last_known_limits.get(resource, 5000)
                
                status = RateLimitStatus(
                    remaining=0,
                    limit=known_limit,
                    reset_at=reset_time,
                    used=known_limit,
                    resource=resource
                )
                self._status[resource] = status
                self.stats['rate_limit_hits'] += 1
                logger.error(f"🚫 Rate limit hit (GraphQL): {status}")

    def _parse_reset_time_from_message(self, message: str) -> Optional[datetime]:
        # ISO 8601
        iso_match = re.search(r'(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)', message)
        if iso_match:
            try:
                return datetime.fromisoformat(iso_match.group(1).replace('Z', '+00:00'))
            except ValueError: pass

        # 4. Corrección: Regex más estricto para evitar falsos positivos
        # Busca "reset", "resets", "time" antes de los 10 dígitos
        ts_match = re.search(r'(?:reset|resets?|time).*?(\d{10})', message, re.IGNORECASE)
        if ts_match:
            try:
                return datetime.fromtimestamp(int(ts_match.group(1)), tz=timezone.utc)
            except (ValueError, OSError): pass
        
        return None

    def calculate_sleep_time(self, resource: str = 'core') -> float:
        with self._state_lock:
            if resource not in self._status:
                return self.min_sleep_between_requests
            
            status = self._status[resource]
            buffer = self._get_dynamic_buffer(status.limit)
            
            if status.remaining > buffer:
                return self.min_sleep_between_requests
            
            return status.time_until_reset() + 1.0

    def wait_if_needed(self, resource: str = 'core'):
        """
        Bloquea el hilo si no hay cuota.
        Implementa decremento preventivo para concurrencia.
        """
        while True:
            should_wait = False
            sleep_seconds = 0.0

            with self._state_lock:
                if resource in self._status:
                    status = self._status[resource]
                    buffer = self._get_dynamic_buffer(status.limit)

                    if status.is_exhausted(buffer):
                        should_wait = True
                        sleep_seconds = self.calculate_sleep_time(resource=resource)
                    else:
                        # Decremento preventivo ("Reserva de ticket")
                        status.remaining = max(0, status.remaining - 1)
                        break 
                else:
                    # Primera petición, dejamos pasar
                    break

            if should_wait:
                if sleep_seconds > self.max_wait_time:
                    raise RateLimitException(f"Wait time {sleep_seconds}s exceeds max {self.max_wait_time}s")

                logger.warning(f"⏳ Throttling {resource}. Sleeping {sleep_seconds:.2f}s...")
                
                with self._state_lock:
                    self.stats['total_waits'] += 1
                    self.stats['total_wait_time'] += sleep_seconds

                time.sleep(sleep_seconds)

                # 2. Corrección: Reset "Sonda" (Pesimista)
                # No asumimos que tenemos 5000 requests. 
                # Ponemos 1 para dejar pasar UNA petición que traiga los headers frescos.
                with self._state_lock:
                    if resource in self._status:
                        old = self._status[resource]
                        self._status[resource] = RateLimitStatus(
                            remaining=1,   # PROBE MODE: Solo 1 intento permitido
                            limit=old.limit,
                            reset_at=old.reset_at, # Mantenemos fecha antigua hasta confirmar
                            used=old.limit,
                            resource=resource
                        )
                        logger.info(f"🔄 Reset triggered. Probing {resource} with 1 request...")
            else:
                time.sleep(self.min_sleep_between_requests)
                break

class RateLimitException(Exception):
    pass

# --- API Pública ---

_global_limiter = None
def get_rate_limiter() -> RateLimiter:
    global _global_limiter
    if _global_limiter is None:
        _global_limiter = RateLimiter()
    return _global_limiter

# --- Decorador (Bonus) ---
def rate_limited(resource: str = 'core'):
    """
    Decorador para funciones que hacen llamadas a la API.
    Maneja la espera AUTOMÁTICAMENTE antes de ejecutar la función.
    
    Uso:
        @rate_limited("search")
        def search_repos(query): ...
    """
    def decorator(func: Callable):
        @wraps(func)
        def wrapper(*args, **kwargs):
            limiter = get_rate_limiter()
            # Espera proactiva
            limiter.wait_if_needed(resource)
            
            # Ejecución
            result = func(*args, **kwargs)
            
            # Intento de actualización reactiva si el resultado es un Response
            # Esto es "best effort", ya que la función podría devolver JSON o Strings
            if isinstance(result, requests.Response):
                limiter.update_from_response(result, resource)
            
            return result
        return wrapper
    return decorator