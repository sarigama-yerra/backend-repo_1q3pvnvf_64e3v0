import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import FastAPI, HTTPException, Depends, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
import jwt  # PyJWT
from passlib.context import CryptContext
from pydantic import BaseModel, EmailStr
from bson import ObjectId

from database import db, create_document, get_documents
from schemas import (
    Patient as PatientSchema,
    Doctor as DoctorSchema,
    Appointment as AppointmentSchema,
    Prescription as PrescriptionSchema,
    LabTest as LabTestSchema,
    Medicine as MedicineSchema,
    Dispense as DispenseSchema,
    Admission as AdmissionSchema,
    Payment as PaymentSchema,
    AmbulanceRequest as AmbulanceRequestSchema,
)

# App and CORS
app = FastAPI(title="Aayaan Hospital API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Security setup
SECRET_KEY = os.getenv("SECRET_KEY", "change_this_secret")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 8

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


# Utilities
class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


def verify_password(plain_password, hashed_password):
    try:
        return pwd_context.verify(plain_password, hashed_password)
    except Exception:
        return False


def get_password_hash(password):
    return pwd_context.hash(password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


async def get_current_user(token: str = Depends(oauth2_scheme)):
    credentials_exception = HTTPException(status_code=401, detail="Could not validate credentials")
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except jwt.PyJWTError:
        raise credentials_exception

    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")

    try:
        user = db["user"].find_one({"_id": ObjectId(user_id)})
    except Exception:
        user = None
    if not user:
        raise credentials_exception
    user["_id"] = str(user["_id"])  # serialize
    return user


# Auth routes
class SignupRequest(BaseModel):
    role: str
    full_name: str
    email: EmailStr
    password: str


@app.post("/auth/signup")
def signup(payload: SignupRequest):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    if db["user"].find_one({"email": payload.email}):
        raise HTTPException(status_code=400, detail="Email already registered")
    hashed = get_password_hash(payload.password)
    user_doc = {
        "role": payload.role,
        "full_name": payload.full_name,
        "email": payload.email,
        "password_hash": hashed,
        "is_active": True,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }
    res = db["user"].insert_one(user_doc)
    uid = str(res.inserted_id)

    if payload.role == "patient":
        db["patient"].insert_one({"user_id": uid, "medical_record_number": f"MRN-{uid[-6:].upper()}"})
    if payload.role == "doctor":
        db["doctor"].insert_one({"user_id": uid, "specialization": None})

    return {"id": uid, "message": "Signup successful"}


@app.post("/auth/login", response_model=Token)
def login(form_data: OAuth2PasswordRequestForm = Depends()):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    user = db["user"].find_one({"email": form_data.username})
    if not user or not verify_password(form_data.password, user.get("password_hash", "")):
        raise HTTPException(status_code=400, detail="Incorrect email or password")
    access_token = create_access_token({"sub": str(user["_id"]), "role": user.get("role", "user")})
    return Token(access_token=access_token)


# Dashboard summary
@app.get("/dashboard")
def dashboard(current=Depends(get_current_user)):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    appts_today = db["appointment"].count_documents({"date": datetime.now().date().isoformat()})
    patients_total = db["patient"].count_documents({})
    lab_pending = db["labtest"].count_documents({"status": "ordered"})
    return {
        "appointments_today": appts_today,
        "patients_total": patients_total,
        "lab_pending": lab_pending,
        "alerts": [],
    }


# Patient module
@app.post("/patients")
def create_patient(p: PatientSchema, current=Depends(get_current_user)):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    pid = create_document("patient", p)
    return {"id": pid}

@app.get("/patients")
def list_patients(limit: int = 50, current=Depends(get_current_user)):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    docs = get_documents("patient", {}, limit)
    for d in docs:
        d["_id"] = str(d["_id"])  # serialize
    return docs

# Medical records
@app.post("/records/{patient_id}")
def add_record(patient_id: str, notes: str = Form(...), current=Depends(get_current_user)):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    rid = db["record"].insert_one({
        "patient_id": patient_id,
        "notes": notes,
        "created_at": datetime.now(timezone.utc)
    }).inserted_id
    return {"id": str(rid)}

@app.get("/records/{patient_id}")
def get_records(patient_id: str, current=Depends(get_current_user)):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    items = list(db["record"].find({"patient_id": patient_id}).sort("created_at", -1))
    for i in items:
        i["_id"] = str(i["_id"])  # serialize
    return items


# Doctor module
@app.get("/doctors")
def list_doctors(current=Depends(get_current_user)):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    items = list(db["doctor"].find({}))
    for i in items:
        i["_id"] = str(i["_id"])  # serialize
    return items

@app.post("/appointments")
def create_appointment(a: AppointmentSchema, current=Depends(get_current_user)):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    aid = create_document("appointment", a)
    return {"id": aid}

@app.get("/appointments/today")
def today_appointments(current=Depends(get_current_user)):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    today = datetime.now().date().isoformat()
    items = list(db["appointment"].find({"date": today}))
    for i in items:
        i["_id"] = str(i["_id"])  # serialize
    return items


# Prescriptions
@app.post("/prescriptions")
def write_prescription(p: PrescriptionSchema, current=Depends(get_current_user)):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    pid = create_document("prescription", p)
    return {"id": pid}

@app.get("/prescriptions/{patient_id}")
def list_prescriptions(patient_id: str, current=Depends(get_current_user)):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    items = list(db["prescription"].find({"patient_id": patient_id}).sort("issued_at", -1))
    for i in items:
        i["_id"] = str(i["_id"])  # serialize
    return items


# Laboratory module
@app.post("/lab/tests")
def order_test(t: LabTestSchema, current=Depends(get_current_user)):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    tid = create_document("labtest", t)
    return {"id": tid}

@app.post("/lab/results/upload")
def upload_result(test_id: str = Form(...), file: UploadFile = File(...), current=Depends(get_current_user)):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    db["labtest"].update_one({"_id": ObjectId(test_id)}, {"$set": {"status": "completed", "result_pdf_url": f"/files/{file.filename}"}})
    return {"message": "Result uploaded"}

@app.get("/lab/tests/{patient_id}")
def lab_tests(patient_id: str, current=Depends(get_current_user)):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    items = list(db["labtest"].find({"patient_id": patient_id}).sort("_id", -1))
    for i in items:
        i["_id"] = str(i["_id"])  # serialize
    return items


# Pharmacy
@app.get("/pharmacy/medicines")
def medicines(current=Depends(get_current_user)):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    items = list(db["medicine"].find({}))
    for i in items:
        i["_id"] = str(i["_id"])  # serialize
    return items

@app.post("/pharmacy/medicines")
def add_medicine(m: MedicineSchema, current=Depends(get_current_user)):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    mid = create_document("medicine", m)
    return {"id": mid}

@app.post("/pharmacy/dispense")
def dispense(d: DispenseSchema, current=Depends(get_current_user)):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    did = create_document("dispense", d)
    for item in d.items:
        try:
            db["medicine"].update_one({"_id": ObjectId(item.get("medicine_id"))}, {"$inc": {"stock": -int(item.get("quantity", 0))}})
        except Exception:
            pass
    return {"id": did}


# Admission
@app.get("/admissions")
def list_admissions(current=Depends(get_current_user)):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    items = list(db["admission"].find({}))
    for i in items:
        i["_id"] = str(i["_id"])  # serialize
    return items

@app.post("/admissions")
def admit(a: AdmissionSchema, current=Depends(get_current_user)):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    aid = create_document("admission", a)
    return {"id": aid}


# Payments
@app.post("/payments")
def pay(p: PaymentSchema, current=Depends(get_current_user)):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    pid = create_document("payment", p)
    return {"id": pid}


# Ambulance
@app.post("/ambulance/request")
def ambulance(req: AmbulanceRequestSchema):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    rid = create_document("ambulancerequest", req)
    return {"id": rid}


@app.get("/")
def root():
    return {"message": "Aayaan Hospital API is running"}


@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": "❌ Not Set",
        "database_name": "❌ Not Set",
        "connection_status": "Not Connected",
        "collections": []
    }
    try:
        if db is not None:
            response["database"] = "✅ Available"
            response["database_url"] = "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set"
            response["database_name"] = os.getenv("DATABASE_NAME") or "❌ Not Set"
            response["connection_status"] = "Connected"
            try:
                collections = db.list_collection_names()
                response["collections"] = collections[:10]
                response["database"] = "✅ Connected & Working"
            except Exception as e:
                response["database"] = f"⚠️  Connected but Error: {str(e)[:50]}"
        else:
            response["database"] = "⚠️  Available but not initialized"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:50]}"
    return response


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
