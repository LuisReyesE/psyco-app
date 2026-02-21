"""
Patient Routes
- List patients
- Create patient
- Delete patient
"""
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session

from backend.database import SessionLocal, Patient

router = APIRouter(prefix="/patients", tags=["Patients"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("/")
def list_patients(db: Session = Depends(get_db)):
    return db.query(Patient).all()


@router.post("/")
def create_patient(name: str, db: Session = Depends(get_db)):
    p = Patient(full_name=name)
    db.add(p)
    db.commit()
    return p


@router.delete("/{patient_id}")
def delete_patient(patient_id: int, db: Session = Depends(get_db)):
    p = db.query(Patient).filter(Patient.id == patient_id).first()
    if p:
        db.delete(p)
        db.commit()
    return {"status": "deleted"}
