import os
import base64
import hashlib
import bcrypt
import secrets
import secrets
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.fernet import Fernet

def _pre_hash(password: str) -> str:
    """Pre-hashes password with SHA256 to bypass bcrypt 72-char limit."""
    digest = hashlib.sha256(password.encode()).digest()
    return base64.b64encode(digest).decode()

def get_password_hash(password: str) -> str:
    """Hashes a password using bcrypt."""
    pre_hashed = _pre_hash(password).encode('utf-8')
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(pre_hashed, salt).decode('utf-8')

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verifies a password against a bcrypt hash."""
    try:
        pre_hashed = _pre_hash(plain_password).encode('utf-8')
        return bcrypt.checkpw(pre_hashed, hashed_password.encode('utf-8'))
    except Exception:
        return False

def derive_key(password: str, salt: bytes) -> bytes:
    """Derives a Fernet key from a password and salt"""
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=300000, # Aumenté iteraciones para mayor seguridad
    )
    key = base64.urlsafe_b64encode(kdf.derive(password.encode()))
    return key

def encrypt_data(data: str, key: bytes) -> str:
    f = Fernet(key)
    return f.encrypt(data.encode()).decode()

def decrypt_data(encrypted_data: str, key: bytes) -> str:
    f = Fernet(key)
    return f.decrypt(encrypted_data.encode()).decode()

def encrypt_file(file_path: str, key: bytes):
    f = Fernet(key)
    with open(file_path, 'rb') as file:
        file_data = file.read()
    
    encrypted_data = f.encrypt(file_data)
    
    enc_path = file_path + ".enc"
    with open(enc_path, 'wb') as file:
        file.write(encrypted_data)
    
    # IMPORTANTE: Asegurar borrado seguro del original sería ideal, 
    # pero os.remove es suficiente para nivel básico.
    if os.path.exists(file_path):
        os.remove(file_path)
    return enc_path

def decrypt_file_to_stream(file_path: str, key: bytes):
    f = Fernet(key)
    with open(file_path, 'rb') as file:
        encrypted_data = file.read()
    return f.decrypt(encrypted_data)

def decrypt_file(input_path: str, output_path: str, key: bytes):
    """Decrypts a file from input_path and writes result to output_path"""
    data = decrypt_file_to_stream(input_path, key)
    with open(output_path, 'wb') as f:
        f.write(data)

def generate_recovery_code() -> str:
    """Generates a human readable recovery code XXXX-XXXX-XXXX-XXXX"""
    # Alfabeto seguro (sin I, L, 1, O, 0 para evitar confusión visual)
    chars = "ABCDEFGHJKMNPQRSTUVWXYZ23456789" 
    parts = []
    for _ in range(4):
        part = ''.join(secrets.choice(chars) for _ in range(4))
        parts.append(part)
    return '-'.join(parts)
