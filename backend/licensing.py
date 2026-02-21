"""
Session AI - Subscription Manager
Sistema de suscripciones basado en email (modelo híbrido)
"""
import os
import uuid
import json
import threading
from datetime import datetime, timedelta
from dotenv import load_dotenv
from backend.database import SessionLocal, User, Session as DBSession

# Load environment variables
load_dotenv()

# Get Supabase credentials from environment
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")


class SubscriptionManager:
    """
    Gestiona suscripciones de usuarios.
    - Usa email como identificador principal
    - Soporta migración de PC automática
    - Verifica expiración automáticamente
    """
    
    def __init__(self):
        from supabase import create_client
        self.client = create_client(SUPABASE_URL, SUPABASE_KEY)
        self.hardware_id = self._get_hardware_id()
        self._last_cloud_check = None
        self._cached_subscription = None

    def _get_hardware_id(self) -> str:
        """
        Genera un ID único y persistente para esta máquina.
        Se guarda en archivo local para consistencia.
        """
        data_dir = os.environ.get('DATA_DIR', os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data'))
        hw_id_file = os.path.join(data_dir, '.hardware_id')
        
        try:
            # Leer ID existente
            if os.path.exists(hw_id_file):
                with open(hw_id_file, 'r') as f:
                    stored_id = f.read().strip()
                    if stored_id:
                        print(f"[SUBSCRIPTION] Using stored hardware_id: {stored_id}")
                        return stored_id
            
            # Generar nuevo ID
            base_id = str(uuid.getnode())
            unique_suffix = str(uuid.uuid4())[:8]
            new_id = f"{base_id}-{unique_suffix}"
            
            os.makedirs(data_dir, exist_ok=True)
            with open(hw_id_file, 'w') as f:
                f.write(new_id)
            
            print(f"[SUBSCRIPTION] Generated new hardware_id: {new_id}")
            return new_id
            
        except Exception as e:
            print(f"[SUBSCRIPTION] Error handling hardware_id: {e}")
            return str(uuid.getnode())

    def sync_subscription_from_cloud(self, db_session) -> dict:
        """
        Sincroniza el estado de la suscripción desde Supabase.
        Se llama al iniciar la app para detectar cambios (expiración, etc.)
        """
        try:
            print(f"[SUBSCRIPTION] Syncing from cloud for hardware: {self.hardware_id}")
            
            # Llamar RPC que busca por hardware_id
            response = self.client.rpc('check_subscription_by_hardware', {
                'p_hardware_id': self.hardware_id
            }).execute()
            
            raw_data = response.data
            print(f"[SUBSCRIPTION] Cloud response: {raw_data}")
            
            # Parsear respuesta
            if isinstance(raw_data, str):
                data = json.loads(raw_data)
            elif isinstance(raw_data, dict):
                data = raw_data
            else:
                data = None
            
            if not data:
                print("[SUBSCRIPTION] No data from cloud")
                return {"synced": False, "reason": "No cloud response"}
            
            # Guardar en cache
            self._cached_subscription = data
            
            # Actualizar DB local
            user = db_session.query(User).first()
            if not user:
                return {"synced": False, "reason": "No local user"}
            
            old_tier = user.license_tier or "FREE"
            new_tier = data.get('tier', 'FREE')
            
            # Detectar cambio de tier
            if old_tier != new_tier:
                print(f"[SUBSCRIPTION] Tier changed! {old_tier} -> {new_tier}")
                user.license_tier = new_tier
                user.last_license_check = datetime.now()
                
                # Guardar email vinculado
                if data.get('email'):
                    user.email = data.get('email')  
                
                db_session.commit()
                
                return {
                    "synced": True,
                    "changed": True,
                    "old_tier": old_tier,
                    "new_tier": new_tier,
                    "days_remaining": data.get('days_remaining'),
                    "expires_at": data.get('expires_at'),
                    "expired": data.get('expired', False),
                    "message": data.get('message')
                }
            else:
                user.last_license_check = datetime.now()
                db_session.commit()
                return {
                    "synced": True,
                    "changed": False,
                    "tier": new_tier,
                    "days_remaining": data.get('days_remaining'),
                    "expires_at": data.get('expires_at')
                }
            
        except Exception as e:
            # Check for connection errors (e.g., [Errno 11001] getaddrinfo failed)
            error_str = str(e)
            if "getaddrinfo failed" in error_str or "ConnectError" in error_str:
                 print(f"[SUBSCRIPTION] Offline mode: Could not sync with cloud ({error_str})")
                 return {"synced": False, "reason": "Offline mode"}
            
            print(f"[SUBSCRIPTION] Cloud sync error: {e}")
            import traceback
            traceback.print_exc()
            return {"synced": False, "reason": str(e)}


    def _run_background_sync(self):
        """Helper to run cloud sync in a separate thread with its own DB session."""
        db = SessionLocal()
        try:
            result = self.sync_subscription_from_cloud(db)
            
            # Logic for auto-retry when offline
            if result.get("reason") == "Offline mode":
                print("[SUBSCRIPTION] Offline. Retrying check in 60 seconds...")
                # Schedule retry without blocking
                threading.Timer(60.0, self._run_background_sync).start()
                
        except Exception as e:
            print(f"[SUBSCRIPTION] Background sync failed: {e}")
        finally:
            db.close()

    def get_subscription_status(self, db_session, force_cloud_check: bool = False) -> dict:
        """
        Obtiene el estado actual de la suscripción.
        Retorna inmediatamente datos locales.
        Si es necesario (primer inicio o force), inicia sincronización en background.
        """
        # 1. Recuperar estado local inmediatamente
        user = db_session.query(User).first()
        local_tier = user.license_tier if user else "FREE"
        local_email = user.email if user else None
        
        result = {
            "tier": local_tier,
            "email": local_email,
            "hardware_id": self.hardware_id
        }
        
        if self._cached_subscription:
             result.update({
                "days_remaining": self._cached_subscription.get('days_remaining'),
                "expires_at": self._cached_subscription.get('expires_at'),
                "name": self._cached_subscription.get('name'),
                "expired": self._cached_subscription.get('expired', False)
             })

        # 2. Determinar si necesitamos sincronizar
        if force_cloud_check:
            # Sincronización síncrona/inmediata requerida
            self._last_cloud_check = datetime.now()
            sync_res = self.sync_subscription_from_cloud(db_session)
            if sync_res.get("synced"):
                 # Actualizar el resultado in-situ con lo que acaba de guardar en cache
                 result["tier"] = sync_res.get("tier", sync_res.get("new_tier", result["tier"]))
                 if self._cached_subscription:
                     result.update({
                        "days_remaining": self._cached_subscription.get('days_remaining'),
                        "expires_at": self._cached_subscription.get('expires_at'),
                        "name": self._cached_subscription.get('name'),
                        "expired": self._cached_subscription.get('expired', False)
                     })
        elif self._last_cloud_check is None:
            # Primera vez: asíncrono background sync
            self._last_cloud_check = datetime.now()
            
            thread = threading.Thread(
                target=self._run_background_sync
            )
            thread.daemon = True 
            thread.start()
            
            # Indicar estado de verificación si es la primera vez
            if result.get("tier") == "FREE" and not self._cached_subscription:
                 result["status_display"] = "Verificando..."

        return result

    def link_email(self, email: str, db_session) -> dict:
        """
        Vincula un email de suscripción a este PC.
        Permite migración automática si el email está en otro PC.
        """
        try:
            print(f"[SUBSCRIPTION] Linking email: {email} to hardware: {self.hardware_id}")
            
            # Llamar RPC para verificar y vincular
            response = self.client.rpc('verify_subscription', {
                'p_email': email.lower().strip(),
                'p_hardware_id': self.hardware_id
            }).execute()
            
            raw_data = response.data
            print(f"[SUBSCRIPTION] Link response: {raw_data}")
            
            # Parsear respuesta
            if isinstance(raw_data, str):
                data = json.loads(raw_data)
            elif isinstance(raw_data, dict):
                data = raw_data
            else:
                return {"success": False, "message": "Respuesta inválida del servidor"}
            
            if not data.get('valid'):
                return {"success": False, "message": data.get('message', 'Email no encontrado')}
            
            # Actualizar DB local
            user = db_session.query(User).first()
            if user:
                user.license_tier = data.get('tier', 'FREE')
                user.email = email.lower().strip()  # Guardar email
                user.hardware_id = self.hardware_id
                user.last_license_check = datetime.now()
                db_session.commit()
            
            # Actualizar cache
            self._cached_subscription = data
            self._last_cloud_check = datetime.now()
            
            return {
                "success": True,
                "tier": data.get('tier'),
                "days_remaining": data.get('days_remaining'),
                "expires_at": data.get('expires_at'),
                "name": data.get('name'),
                "message": data.get('message', 'Email vinculado correctamente')
            }
            
        except Exception as e:
            print(f"[SUBSCRIPTION] Link error: {e}")
            import traceback
            traceback.print_exc()
            return {"success": False, "message": f"Error de conexión: {str(e)}"}

    def check_usage_limits(self, db_session) -> dict:
        """
        Verifica si se excedieron los límites de uso según el tier.
        - FREE: 50 sesiones/mes
        - PRO: 100 sesiones/mes
        """
        # Usamos get_subscription_status que ahora es rápido (local)
        status = self.get_subscription_status(db_session)
        tier = status['tier']
        
        # Contar sesiones este mes
        now = datetime.now()
        start_of_month = datetime(now.year, now.month, 1)
        
        count = db_session.query(DBSession).filter(
            DBSession.created_at >= start_of_month
        ).count()
        
        # Límites según tier
        limit = 100 if tier == 'PRO' else 50
        
        if count >= limit:
            tier_name = "PRO" if tier == 'PRO' else "gratuito"
            return {
                "allowed": False, 
                "reason": f"Límite mensual {tier_name} alcanzado ({count}/{limit}). Actualiza tu plan para continuar."
            }
        
        return {"allowed": True, "count": count, "limit": limit}

    def get_days_until_expiry(self) -> int | None:
        """Retorna los días restantes hasta que expire la suscripción PRO."""
        if self._cached_subscription:
            return self._cached_subscription.get('days_remaining')
        return None

    def is_expiring_soon(self, threshold_days: int = 5) -> bool:
        """Retorna True si la suscripción expira en los próximos N días."""
        days = self.get_days_until_expiry()
        if days is not None and days <= threshold_days:
            return True
        return False


# === RETROCOMPATIBILIDAD ===
# Mantener LicenseManager como alias para no romper código existente
class LicenseManager(SubscriptionManager):
    """Alias para retrocompatibilidad con código existente."""
    
    def get_license_status(self, db_session, force_cloud_check: bool = False):
        """Wrapper para mantener compatibilidad."""
        return self.get_subscription_status(db_session, force_cloud_check)
    
    def activate_license(self, license_key: str, db_session):
        """
        Ahora acepta email en lugar de license_key.
        Mantiene compatibilidad con la interfaz anterior.
        """
        # Detectar si es email o license_key antiguo
        if '@' in license_key:
            # Es un email -> usar nuevo sistema
            return self.link_email(license_key, db_session)
        else:
            # Es license_key antiguo -> intentar verificar con sistema viejo
            # (para migración gradual)
            try:
                response = self.client.rpc('verify_license', {
                    'p_key': license_key,
                    'p_hardware_id': self.hardware_id
                }).execute()
                
                raw_data = response.data
                if isinstance(raw_data, str):
                    data = json.loads(raw_data)
                else:
                    data = raw_data or {}
                
                if data.get('valid'):
                    user = db_session.query(User).first()
                    if user:
                        user.license_tier = data.get('tier', 'FREE')
                        user.email = license_key
                        user.hardware_id = self.hardware_id
                        user.last_license_check = datetime.now()
                        db_session.commit()
                    return {"success": True, "tier": data.get('tier'), "message": data.get('message')}
                else:
                    return {"success": False, "message": data.get('message', 'Licencia inválida')}
                    
            except Exception as e:
                return {"success": False, "message": f"Error: {str(e)}"}


# Singleton Lazy
_license_manager_instance = None
_license_manager_lock = threading.Lock()

def get_license_manager():
    global _license_manager_instance
    if _license_manager_instance is None:
        with _license_manager_lock:
            if _license_manager_instance is None:
                _license_manager_instance = LicenseManager()
    return _license_manager_instance
