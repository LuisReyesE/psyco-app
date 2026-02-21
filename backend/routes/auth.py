"""
Authentication Routes
- Check registration
- Register user
- Login
- Verify token
- Password recovery
"""
import os
from fastapi import APIRouter, Form, HTTPException, Depends
from sqlalchemy.orm import Session
from cryptography.fernet import Fernet

from backend.database import SessionLocal, User
from backend.security import (
    get_password_hash, verify_password, derive_key, 
    encrypt_data, decrypt_data, generate_recovery_code
)
from backend.licensing import get_license_manager

router = APIRouter(prefix="/auth", tags=["Authentication"])

# In-Memory Cache for Decrypted Master Keys
# Format: { token_str: b"master_key_bytes" }
# This is shared across the app - imported by other modules
ACTIVE_KEYS = {}


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("/check")
def check_registration(db: Session = Depends(get_db)):
    """Check if any user is registered (Single User App)"""
    user = db.query(User).first()
    return {"has_user": bool(user)}


@router.post("/register")
def register(username: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    if db.query(User).first():
        raise HTTPException(status_code=400, detail="User already registered")

    # 1. Generate Universal Master Key (MK)
    master_key = Fernet.generate_key() 
    
    # 2. Setup Recovery Code
    recovery_code = generate_recovery_code()  # "ABCD-EFGH-..."
    recovery_salt = os.urandom(16).hex()
    
    # 3. Encrypt MK in Box A (Password Protection + HWID Binding)
    salt = os.urandom(16).hex()
    hashed = get_password_hash(password)
    
    hardware_id = get_license_manager().hardware_id
    hardware_mix = password + hardware_id
    derived_pwd_key = derive_key(hardware_mix, bytes.fromhex(salt))
    encrypted_mk_pwd = encrypt_data(master_key.decode(), derived_pwd_key)
    
    # 4. Encrypt MK in Box B (Recovery Code Protection)
    derived_rec_key = derive_key(recovery_code, bytes.fromhex(recovery_salt))
    encrypted_mk_rec = encrypt_data(master_key.decode(), derived_rec_key)
    
    user = User(
        username=username, 
        hashed_password=hashed, 
        salt=salt,
        encrypted_master_key=encrypted_mk_pwd,
        recovery_encrypted_master_key=encrypted_mk_rec,
        recovery_salt=recovery_salt
    )
    db.add(user)
    db.commit()
    
    return {"status": "success", "recovery_code": recovery_code}


@router.post("/login")
def login(username: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == username).first()
    if not user or not verify_password(password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    try:
        # Open Box A (with HWID Binding)
        hardware_id = get_license_manager().hardware_id
        hardware_mix = password + hardware_id
        derived_pwd_key = derive_key(hardware_mix, bytes.fromhex(user.salt))
        master_key_str = decrypt_data(user.encrypted_master_key, derived_pwd_key)
        master_key = master_key_str.encode()
    except Exception:
        # Fallback & Migration for older DBs without HWID binding
        try:
            derived_pwd_key_old = derive_key(password, bytes.fromhex(user.salt))
            master_key_str = decrypt_data(user.encrypted_master_key, derived_pwd_key_old)
            master_key = master_key_str.encode()
            
            # Re-encrypt with HWID binding
            hardware_id = get_license_manager().hardware_id
            hardware_mix = password + hardware_id
            new_salt = os.urandom(16).hex()
            new_derived_pwd_key = derive_key(hardware_mix, bytes.fromhex(new_salt))
            new_encrypted_mk_pwd = encrypt_data(master_key_str, new_derived_pwd_key)
            
            user.salt = new_salt
            user.encrypted_master_key = new_encrypted_mk_pwd
            db.commit()
        except Exception:
            raise HTTPException(status_code=500, detail="Crypto check failed")
    
    token = os.urandom(24).hex()
    ACTIVE_KEYS[token] = master_key  # Session uses the Real Master Key
    
    return {"status": "success", "token": token, "username": user.username}


@router.post("/verify")
def verify_token(token: str = Form(...)):
    """Check if token is active in RAM"""
    if token in ACTIVE_KEYS:
        return {"valid": True}
    raise HTTPException(status_code=401, detail="Token invalid")


@router.post("/recover")
def recover_password(
    username: str = Form(...), 
    recovery_code: str = Form(...), 
    new_password: str = Form(...), 
    db: Session = Depends(get_db)
):
    user = db.query(User).filter(User.username == username).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
        
    try:
        # Open Box B
        derived_rec_key = derive_key(recovery_code, bytes.fromhex(user.recovery_salt))
        master_key_str = decrypt_data(user.recovery_encrypted_master_key, derived_rec_key)
        # If we are here, recovery code is correct
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid recovery code")
        
    # Re-encrypt in Box A with New Password + HWID Binding
    new_salt = os.urandom(16).hex()
    new_hashed = get_password_hash(new_password)
    
    hardware_id = get_license_manager().hardware_id
    hardware_mix = new_password + hardware_id
    derived_new_pwd_key = derive_key(hardware_mix, bytes.fromhex(new_salt))
    
    new_encrypted_mk_pwd = encrypt_data(master_key_str, derived_new_pwd_key)
    
    user.hashed_password = new_hashed
    user.salt = new_salt
    user.encrypted_master_key = new_encrypted_mk_pwd
    db.commit()
    
    return {"status": "recovered"}
