import os
import base64
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.fernet import Fernet
from passlib.context import CryptContext

import hashlib

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def _pre_hash(password: str) -> str:
    """Pre-hashes password with SHA256 to bypass bcrypt 72-char limit.
    Returns a 44-character base64 string."""
    digest = hashlib.sha256(password.encode()).digest()
    return base64.b64encode(digest).decode()

def get_password_hash(password):
    return pwd_context.hash(_pre_hash(password))

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(_pre_hash(plain_password), hashed_password)

# Key derivation for encryption
def derive_key(password: str, salt: bytes) -> bytes:
    """Derives a Fernet key from a password and salt"""
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100000,
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
    """Encrypts a file in place and adds .enc extension"""
    f = Fernet(key)
    with open(file_path, 'rb') as file:
        file_data = file.read()
    
    encrypted_data = f.encrypt(file_data)
    
    enc_path = file_path + ".enc"
    with open(enc_path, 'wb') as file:
        file.write(encrypted_data)
    
    os.remove(file_path)
    return enc_path

def decrypt_file_to_stream(file_path: str, key: bytes):
    """Returns decrypted bytes of a file"""
    f = Fernet(key)
    with open(file_path, 'rb') as file:
        encrypted_data = file.read()
    return f.decrypt(encrypted_data)
