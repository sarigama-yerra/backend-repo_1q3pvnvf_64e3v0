"""
Aayaan Hospital - Database Schemas

Each Pydantic model corresponds to a MongoDB collection (lowercased class name).
We focus on core entities required by the hospital system.
"""

from pydantic import BaseModel, Field, EmailStr
from typing import Optional, List, Literal
from datetime import datetime

# Users (doctors, nurses, patients, lab, pharmacy, admin)
class User(BaseModel):
    role: Literal['doctor','nurse','patient','lab','pharmacy','admin']
    full_name: str = Field(..., min_length=2)
    email: EmailStr
    password_hash: str
    phone: Optional[str] = None
    gender: Optional[Literal['male','female','other']] = None
    date_of_birth: Optional[str] = None
    address: Optional[str] = None
    is_active: bool = True

class Patient(BaseModel):
    user_id: str
    medical_record_number: str
    blood_group: Optional[str] = None
    allergies: Optional[List[str]] = None
    chronic_conditions: Optional[List[str]] = None
    emergency_contact: Optional[str] = None
    insurance_provider: Optional[str] = None
    insurance_number: Optional[str] = None

class Doctor(BaseModel):
    user_id: str
    specialization: Optional[str] = None
    license_number: Optional[str] = None
    years_of_experience: Optional[int] = None
    schedule: Optional[List[dict]] = None  # [{day:'Mon', slots:["09:00-12:00"]}]

class Appointment(BaseModel):
    patient_id: str
    doctor_id: str
    date: str
    time: str
    status: Literal['scheduled','completed','cancelled','no_show'] = 'scheduled'
    reason: Optional[str] = None
    notes: Optional[str] = None

class Prescription(BaseModel):
    patient_id: str
    doctor_id: str
    items: List[dict]  # [{medicine_id, name, dosage, frequency, days, notes}]
    issued_at: Optional[datetime] = None

class LabTest(BaseModel):
    patient_id: str
    ordered_by: str  # doctor_id
    test_type: str
    status: Literal['ordered','in_progress','completed','cancelled'] = 'ordered'
    result_summary: Optional[str] = None
    result_pdf_url: Optional[str] = None

class Medicine(BaseModel):
    name: str
    stock: int
    price: float
    manufacturer: Optional[str] = None
    expiry_date: Optional[str] = None

class Dispense(BaseModel):
    patient_id: str
    prescription_id: str
    items: List[dict]  # [{medicine_id, quantity, price}]
    total: float
    paid: bool = False

class Admission(BaseModel):
    patient_id: str
    room_number: str
    bed_number: Optional[str] = None
    admitted_at: str
    discharge_at: Optional[str] = None
    status: Literal['admitted','discharged'] = 'admitted'

class Payment(BaseModel):
    patient_id: str
    amount: float
    method: Literal['cash','card','insurance']
    invoice_number: str
    insurance_provider: Optional[str] = None
    status: Literal['pending','paid','failed'] = 'pending'

class AmbulanceRequest(BaseModel):
    patient_name: str
    phone: str
    location: str
    destination: Optional[str] = None
    eta_minutes: Optional[int] = None
    status: Literal['requested','enroute','arrived','cancelled'] = 'requested'
