import os
import io
import csv
from pathlib import Path
from datetime import datetime
from typing import Optional
from fastapi import FastAPI, Request, Form, HTTPException, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
import jwt
import openpyxl

app = FastAPI(title="BLIA佛光永續學院簽到系統 - iPure Green")

BASE_DIR = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = BASE_DIR / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

SECRET_KEY = os.getenv("SECRET_KEY", "ipuregreen-blia-secret-key-2026")

# 資料庫預設資料
db = {
    "admins": [
        {
            "id": 1,
            "email": "service@ipuregreen.org",
            "password": "2026ipuregreen",
            "status": "active",
            "role": "superadmin"
        },
        {
            "id": 2,
            "email": "vinnyhuang.ipuregreen@gmail.com",
            "password": "123456",
            "status": "active",
            "role": "admin"
        }
    ],
    "students": [
        {"id": 1, "name": "黃雅筠", "email": "vinnyhuang.ipuregreen@gmail.com", "phone": "0912345678"}
    ],
    "courses": [
        {
            "id": 1,
            "title": "導論：自然永續的核心觀念與倫理基礎",
            "course_date": "2026/09/15",
            "course_time": "18:00-22:00",
            "open_time": "2026-09-15 18:00:00"
        },
        {
            "id": 2,
            "title": "健康一體（One Health）與系統思維",
            "course_date": "2026/09/22",
            "course_time": "18:30-21:30",
            "open_time": "2026-09-22 18:00:00"
        }
    ],
    "attendances": {
        "1_1": {"status": "SIGNED_IN", "signed_at": "2026-09-15 18:05:12"}
    }
}

# --- 認證輔助函式 ---
def get_current_student(request: Request):
    token = request.cookies.get("token")
    if not token:
        return None
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        return next((s for s in db["students"] if s["id"] == payload["id"]), None)
    except:
        return None

def get_current_admin(request: Request):
    token = request.cookies.get("admin_token")
    if not token:
        return None
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        admin = next((a for a in db["admins"] if a["id"] == payload.get("id")), None)
        if admin and admin["status"] == "active":
            return admin
    except:
        return None
    return None

# ==========================================
# 前台學員頁面與登入/登出 (秒退登出)
# ==========================================
@app.get("/", response_class=HTMLResponse)
async def login_page(request: Request):
    token = request.cookies.get("token")
    if token:
        student = get_current_student(request)
        if student:
            return RedirectResponse(url="/dashboard", status_code=302)
    return templates.TemplateResponse(request=request, name="login.html", context={})

@app.get("/logout")
async def logout():
    resp = RedirectResponse(url="/", status_code=302)
    resp.delete_cookie(key="token", path="/")
    return resp

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page(request: Request):
    student = get_current_student(request)
    if not student:
        return RedirectResponse(url="/", status_code=302)
    
    signed_count = sum(1 for k, v in db["attendances"].items() if k.startswith(f"{student['id']}_") and v["status"] == "SIGNED_IN")
    leave_count = sum(1 for k, v in db["attendances"].items() if k.startswith(f"{student['id']}_") and v["status"] == "ON_LEAVE")
    makeup_count = sum(1 for k, v in db["attendances"].items() if k.startswith(f"{student['id']}_") and v["status"] == "MAKEUP_DONE")
    absent_count = sum(1 for k, v in db["attendances"].items() if k.startswith(f"{student['id']}_") and v["status"] == "ABSENT")

    courses_view = []
    for c in db["courses"]:
        record = db["attendances"].get(f"{student['id']}_{c['id']}")
        status = record["status"] if record else "PENDING"
        courses_view.append({**c, "status": status})

    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "student": student,
            "stats": {
                "signed": signed_count,
                "leave": leave_count,
                "makeup": makeup_count,
                "absent": absent_count
            },
            "courses": courses_view
        }
    )

@app.get("/api/auth/logout")
async def student_logout():
    resp = RedirectResponse(url="/", status_code=302)
    resp.delete_cookie(key="token", path="/")
    return resp

@app.post("/api/auth/login")
async def api_login(email: str = Form(...), phone: str = Form(...)):
    student = next((s for s in db["students"] if s["email"].strip().lower() == email.strip().lower() and s["phone"].strip() == phone.strip()), None)
    if not student:
        return JSONResponse(status_code=401, content={"error": "查無此報名資料，請確認 Email 與電話！"})
    
    token = jwt.encode({"id": student["id"], "email": student["email"]}, SECRET_KEY, algorithm="HS256")
    resp = JSONResponse(content={"success": True})
    resp.set_cookie("token", token, httponly=True, max_age=86400*7, path="/")
    return resp

@app.post("/api/attendance/checkin")
async def api_checkin(request: Request):
    student = get_current_student(request)
    if not student:
        raise HTTPException(status_code=401, detail="請先登入")
    data = await request.json()
    course_id = data.get("course_id")
    key = f"{student['id']}_{course_id}"
    db["attendances"][key] = {
        "status": "SIGNED_IN",
        "signed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    return {"success": True}

@app.post("/api/attendance/leave")
async def api_leave(request: Request):
    student = get_current_student(request)
    if not student:
        raise HTTPException(status_code=401, detail="請先登入")
    data = await request.json()
    course_id = data.get("course_id")
    reason = data.get("reason", "")
    key = f"{student['id']}_{course_id}"
    db["attendances"][key] = {
        "status": "ON_LEAVE",
        "reason": reason,
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    return {"success": True}

# ==========================================
# 後台管理：登入 / 修改密碼 / 忘記密碼 / 帳號維護
# ==========================================

@app.get("/admin/login", response_class=HTMLResponse)
async def admin_login_page(request: Request):
    if get_current_admin(request):
        return RedirectResponse(url="/admin", status_code=302)
    return templates.TemplateResponse(request=request, name="admin_login.html", context={})

@app.post("/api/admin/auth/login")
async def admin_login(email: str = Form(...), password: str = Form(...)):
    admin = next((a for a in db["admins"] if a["email"].strip().lower() == email.strip().lower() and a["password"] == password.strip()), None)
    if not admin:
        return JSONResponse(status_code=401, content={"error": "管理者帳號或密碼錯誤！"})
    
    if admin["status"] != "active":
        return JSONResponse(status_code=403, content={"error": "此管理者帳號已被停用，請聯繫最高管理者！"})
    
    token = jwt.encode({"id": admin["id"], "role": admin["role"], "email": admin["email"]}, SECRET_KEY, algorithm="HS256")
    resp = JSONResponse(content={"success": True})
    resp.set_cookie("admin_token", token, httponly=True, max_age=86400*7, path="/")
    return resp

@app.get("/api/admin/auth/logout")
async def admin_logout():
    resp = RedirectResponse(url="/admin/login", status_code=302)
    resp.delete_cookie(key="admin_token", path="/")
    return resp

@app.post("/api/admin/auth/change-password")
async def change_password(request: Request):
    current_admin = get_current_admin(request)
    if not current_admin:
        raise HTTPException(status_code=401, detail="請先登入後台")
    data = await request.json()
    old_pwd = data.get("old_password")
    new_pwd = data.get("new_password")
    
    if old_pwd != current_admin["password"]:
        return JSONResponse(status_code=400, content={"error": "舊密碼不正確！"})
    if not new_pwd or len(new_pwd) < 4:
        return JSONResponse(status_code=400, content={"error": "新密碼長度至少需 4 碼！"})
    
    current_admin["password"] = new_pwd
    return {"success": True}

@app.post("/api/admin/auth/forgot-password")
async def forgot_password(request: Request):
    data = await request.json()
    email = data.get("email", "").strip()
    admin = next((a for a in db["admins"] if a["email"].lower() == email.lower()), None)
    if admin:
        print(f"【系統郵件已寄出】收件者: {email}，您的管理者密碼為: {admin['password']}")
        return {
            "success": True, 
            "message": f"密碼已成功寄送至 {email}！(測試環境提示：密碼為 {admin['password']})"
        }
    return JSONResponse(status_code=404, content={"error": "查無此管理者 Email，請確認輸入是否正確！"})

# 後台主頁
@app.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request):
    current_admin = get_current_admin(request)
    if not current_admin:
        return RedirectResponse(url="/admin/login", status_code=302)
    return templates.TemplateResponse(
        request=request,
        name="admin.html",
        context={
            "admins": db["admins"],
            "students": db["students"],
            "courses": db["courses"],
            "current_admin": current_admin
        }
    )

# 課程學員簽到狀況頁面 (含圓餅圖)
@app.get("/admin/courses/{course_id}/attendance", response_class=HTMLResponse)
async def course_attendance_page(course_id: int, request: Request):
    if not get_current_admin(request):
        return RedirectResponse(url="/admin/login", status_code=302)
    
    course = next((c for c in db["courses"] if c["id"] == course_id), None)
    if not course:
        return RedirectResponse(url="/admin", status_code=302)
    
    student_records = []
    signed_count = 0
    not_signed_count = 0
    
    for s in db["students"]:
        key = f"{s['id']}_{course['id']}"
        rec = db["attendances"].get(key)
        status = rec["status"] if rec else "PENDING"
        signed_at = rec.get("signed_at", "-") if rec else "-"
        
        if status == "SIGNED_IN":
            signed_count += 1
        else:
            not_signed_count += 1
            
        student_records.append({
            "id": s["id"],
            "name": s["name"],
            "email": s["email"],
            "phone": s["phone"],
            "status": status,
            "signed_at": signed_at
        })

    return templates.TemplateResponse(
        request=request,
        name="course_attendance.html",
        context={
            "course": course,
            "records": student_records,
            "signed_count": signed_count,
            "not_signed_count": not_signed_count,
            "total_count": len(student_records)
        }
    )

# ==========================================
# 管理者帳號維護 API (CRUD)
# ==========================================
@app.post("/api/admin/accounts")
async def add_admin_account(request: Request):
    current_admin = get_current_admin(request)
    if not current_admin:
        raise HTTPException(status_code=401, detail="未授權")
    
    data = await request.json()
    email = data.get("email", "").strip()
    password = data.get("password", "").strip()
    status = data.get("status", "active")
    
    if not email or not password:
        return JSONResponse(status_code=400, content={"error": "請填寫完整帳號與密碼！"})
    
    if any(a["email"].lower() == email.lower() for a in db["admins"]):
        return JSONResponse(status_code=400, content={"error": "該管理者帳號已存在！"})
    
    new_id = max([a["id"] for a in db["admins"]], default=0) + 1
    new_acc = {"id": new_id, "email": email, "password": password, "status": status, "role": "admin"}
    db["admins"].append(new_acc)
    return {"success": True, "account": new_acc}

@app.put("/api/admin/accounts/{account_id}")
async def update_admin_account(account_id: int, request: Request):
    current_admin = get_current_admin(request)
    if not current_admin:
        raise HTTPException(status_code=401, detail="未授權")
    
    data = await request.json()
    target = next((a for a in db["admins"] if a["id"] == account_id), None)
    if not target:
        raise HTTPException(status_code=404, detail="查無此帳號")
    
    if target["email"].lower() == "service@ipuregreen.org":
        if data.get("status") == "disabled":
            return JSONResponse(status_code=400, content={"error": "最高權限帳號不可設定為停用！"})
        if data.get("password"):
            target["password"] = data.get("password").strip()
        return {"success": True, "account": target}

    if data.get("email"): target["email"] = data.get("email").strip()
    if data.get("password"): target["password"] = data.get("password").strip()
    if data.get("status"): target["status"] = data.get("status")
        
    return {"success": True, "account": target}

@app.delete("/api/admin/accounts/{account_id}")
async def delete_admin_account(account_id: int, request: Request):
    current_admin = get_current_admin(request)
    if not current_admin:
        raise HTTPException(status_code=401, detail="未授權")
    
    target = next((a for a in db["admins"] if a["id"] == account_id), None)
    if not target:
        raise HTTPException(status_code=404, detail="查無此帳號")
    
    if target["email"].lower() == "service@ipuregreen.org" or target.get("role") == "superadmin":
        return JSONResponse(status_code=400, content={"error": "此為最高權限帳號 (service@ipuregreen.org)，嚴禁刪除！"})
    
    db["admins"] = [a for a in db["admins"] if a["id"] != account_id]
    return {"success": True}

# ==========================================
# 學員與課程 CRUD API (含 Admin 權限驗證與 Excel 正確解構)
# ==========================================

# 1. 課程匯入 (核心修復：Admin 專屬 + 精準解構 4 欄位)
@app.post("/api/admin/courses/import")
async def import_courses(request: Request, file: UploadFile = File(...)):
    # 嚴格確認管理者權限
    current_admin = get_current_admin(request)
    if not current_admin:
        raise HTTPException(status_code=401, detail="未授權，匯入功能僅限管理者使用！")

    contents = await file.read()
    filename = file.filename.lower()
    imported_count = 0
    rows = []

    if filename.endswith(".xlsx") or filename.endswith(".xls"):
        wb = openpyxl.load_workbook(io.BytesIO(contents))
        sheet = wb.active
        rows = list(sheet.iter_rows(values_only=True)) if sheet else []
    elif filename.endswith(".csv"):
        text = contents.decode("utf-8-sig", errors="ignore")
        rows = list(csv.reader(io.StringIO(text)))
    else:
        raise HTTPException(status_code=400, detail="請上傳 .xlsx 或 .csv 檔案")

    def cell_to_str(val):
        if val is None:
            return ""
        if isinstance(val, datetime):
            return val.strftime("%Y-%m-%d %H:%M:%S")
        if hasattr(val, "strftime"):
            return val.strftime("%Y-%m-%d")
        return str(val).strip()

    for r in rows[1:]:
        row_vals = [cell_to_str(x) for x in r]
        if len(row_vals) < 4 or not row_vals[0]:
            continue

        # 精準抓取 4 個獨立欄位 (避免整列字串化)
        title, raw_date, raw_time, raw_open = row_vals[:4]
        
        # 轉換為標準日期 2026/09/15 (完全符合圖二樣式)
        cdate = raw_date.replace("-", "/").split(" ")[0]
        ctime = raw_time
        otime = raw_open

        # 智慧覆蓋更新已存在之課程，並修復原本破損的資料
        existing = next((c for c in db["courses"] if c["title"].strip() == title), None)
        if existing:
            existing["course_date"] = cdate
            existing["course_time"] = ctime
            existing["open_time"] = otime
        else:
            new_id = max([c["id"] for c in db["courses"]], default=0) + 1
            db["courses"].append({
                "id": new_id,
                "title": title,
                "course_date": cdate,
                "course_time": ctime,
                "open_time": otime
            })
        imported_count += 1

    return {"success": True, "count": imported_count}

# 2. 學員匯入 (核心修復：Admin 專屬 + 精準解構 3 欄位)
@app.post("/api/admin/students/import")
async def import_students(request: Request, file: UploadFile = File(...)):
    current_admin = get_current_admin(request)
    if not current_admin:
        raise HTTPException(status_code=401, detail="未授權，匯入功能僅限管理者使用！")

    contents = await file.read()
    filename = file.filename.lower()
    imported_count = 0
    rows = []

    if filename.endswith(".xlsx") or filename.endswith(".xls"):
        wb = openpyxl.load_workbook(io.BytesIO(contents))
        sheet = wb.active
        rows = list(sheet.iter_rows(values_only=True)) if sheet else []
    elif filename.endswith(".csv"):
        text = contents.decode("utf-8-sig", errors="ignore")
        rows = list(csv.reader(io.StringIO(text)))
    else:
        raise HTTPException(status_code=400, detail="請上傳 .xlsx 或 .csv 檔案")

    def cell_to_str(val):
        return str(val).strip() if val is not None else ""

    for r in rows[1:]:
        row_vals = [cell_to_str(x) for x in r]
        if len(row_vals) < 3 or not row_vals[0]:
            continue

        name, email, phone = row_vals[:3]

        existing = next((s for s in db["students"] if s["email"].lower() == email.lower()), None)
        if existing:
            existing["name"] = name
            existing["phone"] = phone
        else:
            new_id = max([s["id"] for s in db["students"]], default=0) + 1
            db["students"].append({"id": new_id, "name": name, "email": email, "phone": phone})
        imported_count += 1

    return {"success": True, "count": imported_count}

# 3. 手動新增/修改/刪除 學員與課程
@app.post("/api/admin/students")
async def add_student(request: Request):
    if not get_current_admin(request): raise HTTPException(status_code=401, detail="未授權")
    data = await request.json()
    new_id = max([s["id"] for s in db["students"]], default=0) + 1
    new_student = {"id": new_id, "name": data.get("name", "").strip(), "email": data.get("email", "").strip(), "phone": data.get("phone", "").strip()}
    db["students"].append(new_student)
    return {"success": True, "student": new_student}

@app.put("/api/admin/students/{student_id}")
async def update_student(student_id: int, request: Request):
    if not get_current_admin(request): raise HTTPException(status_code=401, detail="未授權")
    data = await request.json()
    for s in db["students"]:
        if s["id"] == student_id:
            s["name"] = data.get("name", s["name"]).strip()
            s["email"] = data.get("email", s["email"]).strip()
            s["phone"] = data.get("phone", s["phone"]).strip()
            return {"success": True, "student": s}
    raise HTTPException(status_code=404, detail="查無此學員")

@app.delete("/api/admin/students/{student_id}")
async def delete_student(student_id: int, request: Request):
    if not get_current_admin(request): raise HTTPException(status_code=401, detail="未授權")
    db["students"] = [s for s in db["students"] if s["id"] != student_id]
    return {"success": True}

@app.post("/api/admin/courses")
async def add_course(request: Request):
    if not get_current_admin(request): raise HTTPException(status_code=401, detail="未授權")
    data = await request.json()
    new_id = max([c["id"] for c in db["courses"]], default=0) + 1
    new_course = {"id": new_id, "title": data.get("title", "").strip(), "course_date": data.get("course_date", "").strip(), "course_time": data.get("course_time", "").strip(), "open_time": data.get("open_time", "").strip()}
    db["courses"].append(new_course)
    return {"success": True, "course": new_course}

@app.put("/api/admin/courses/{course_id}")
async def update_course(course_id: int, request: Request):
    if not get_current_admin(request): raise HTTPException(status_code=401, detail="未授權")
    data = await request.json()
    for c in db["courses"]:
        if c["id"] == course_id:
            c["title"] = data.get("title", c["title"]).strip()
            c["course_date"] = data.get("course_date", c["course_date"]).strip()
            c["course_time"] = data.get("course_time", c["course_time"]).strip()
            c["open_time"] = data.get("open_time", c["open_time"]).strip()
            return {"success": True, "course": c}
    raise HTTPException(status_code=404, detail="查無此課程")

@app.delete("/api/admin/courses/{course_id}")
async def delete_course(course_id: int, request: Request):
    if not get_current_admin(request): raise HTTPException(status_code=401, detail="未授權")
    db["courses"] = [c for c in db["courses"] if c["id"] != course_id]
    return {"success": True}