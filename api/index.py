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

# 資料庫模型
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
        {
            "id": 1, 
            "name": "黃雅筠", 
            "email": "vinnyhuang.ipuregreen@gmail.com", 
            "email_pathdemy": "vinnyhuang.ipuregreen@gmail.com",
            "phone": "0912345678"
        }
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
# 前台學員路由
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
    
    signed_count = sum(1 for k, v in db["attendances"].items() if k.startswith(f"{student['id']}_") and v.get("status") == "SIGNED_IN")
    leave_count = sum(1 for k, v in db["attendances"].items() if k.startswith(f"{student['id']}_") and v.get("status") == "ON_LEAVE")
    makeup_count = sum(1 for k, v in db["attendances"].items() if k.startswith(f"{student['id']}_") and v.get("status") == "MAKEUP_DONE")
    absent_count = sum(1 for k, v in db["attendances"].items() if k.startswith(f"{student['id']}_") and v.get("status") == "ABSENT")

    courses_view = []
    for c in db["courses"]:
        record = db["attendances"].get(f"{student['id']}_{c['id']}")
        status = record["status"] if record else "PENDING"
        makeup_date = record.get("makeup_date", "") if record else ""
        courses_view.append({**c, "status": status, "makeup_date": makeup_date})

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
    clean_email = email.strip().lower()
    clean_phone = phone.strip()
    student = next((s for s in db["students"] if (s["email"].strip().lower() == clean_email or s.get("email_pathdemy", "").strip().lower() == clean_email) and s["phone"].strip() == clean_phone), None)
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

# 前台學員自主點擊【補課登錄】API
@app.post("/api/attendance/makeup")
async def api_makeup(request: Request):
    student = get_current_student(request)
    if not student:
        raise HTTPException(status_code=401, detail="請先登入")
    data = await request.json()
    course_id = data.get("course_id")
    key = f"{student['id']}_{course_id}"
    
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    platform_email = student.get("email_pathdemy") or student["email"]
    
    # 寫入狀態，備註為「自行登錄」
    db["attendances"][key] = {
        "status": "MAKEUP_DONE",
        "makeup_date": now_str,
        "platform_email": platform_email,
        "note": "自行登錄",
        "updated_at": now_str
    }
    return {"success": True}

# ==========================================
# 後台管理路由
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

# 課程簽到狀況頁面
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
            "email_pathdemy": s.get("email_pathdemy", s["email"]),
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

# 課程請假狀況頁面
@app.get("/admin/courses/{course_id}/leaves", response_class=HTMLResponse)
async def course_leaves_page(course_id: int, request: Request):
    if not get_current_admin(request):
        return RedirectResponse(url="/admin/login", status_code=302)
    course = next((c for c in db["courses"] if c["id"] == course_id), None)
    if not course:
        return RedirectResponse(url="/admin", status_code=302)
    
    leave_records = []
    for s in db["students"]:
        key = f"{s['id']}_{course['id']}"
        rec = db["attendances"].get(key)
        if rec and rec.get("status") == "ON_LEAVE":
            leave_records.append({
                "student_id": s["id"],
                "name": s["name"],
                "email": s["email"],
                "email_pathdemy": s.get("email_pathdemy", s["email"]),
                "phone": s["phone"],
                "reason": rec.get("reason", "未填寫"),
                "updated_at": rec.get("updated_at", "-")
            })

    return templates.TemplateResponse(
        request=request,
        name="course_leaves.html",
        context={
            "course": course,
            "records": leave_records,
            "total_count": len(leave_records)
        }
    )

@app.delete("/api/admin/courses/{course_id}/leaves/{student_id}")
async def cancel_leave(course_id: int, student_id: int, request: Request):
    if not get_current_admin(request):
        raise HTTPException(status_code=401, detail="未授權")
    key = f"{student_id}_{course_id}"
    if key in db["attendances"]:
        del db["attendances"][key]
    return {"success": True}

# ==========================================
# 核心需求：【補課狀況】渲染與 Excel 批次匯入
# ==========================================
@app.get("/admin/courses/{course_id}/pathdemy", response_class=HTMLResponse)
@app.get("/admin/courses/{course_id}/makeups", response_class=HTMLResponse)
async def course_pathdemy_page(course_id: int, request: Request):
    if not get_current_admin(request):
        return RedirectResponse(url="/admin/login", status_code=302)
    course = next((c for c in db["courses"] if c["id"] == course_id), None)
    if not course:
        return RedirectResponse(url="/admin", status_code=302)
    
    makeup_records = []
    for s in db["students"]:
        key = f"{s['id']}_{course['id']}"
        rec = db["attendances"].get(key)
        if rec and rec.get("status") == "MAKEUP_DONE":
            makeup_records.append({
                "id": s["id"],
                "name": s["name"],
                "email": s["email"],
                "email_pathdemy": s.get("email_pathdemy", s["email"]),
                "phone": s["phone"],
                "makeup_date": rec.get("makeup_date", "-"),
                "note": rec.get("note", "管理員批次匯入"),
                "imported_by": rec.get("imported_by", "")
            })

    return templates.TemplateResponse(
        request=request,
        name="course_pathdemy.html",
        context={
            "course": course,
            "records": makeup_records,
            "total_count": len(makeup_records),
            "all_students": db["students"]
        }
    )

# 後台管理員批次匯入 Excel/CSV (寫入 note: 管理員批次匯入 與 匯入者帳號)
@app.post("/api/admin/courses/{course_id}/pathdemy/import")
async def import_pathdemy_excel(course_id: int, request: Request, file: UploadFile = File(...)):
    admin = get_current_admin(request)
    if not admin:
        raise HTTPException(status_code=401, detail="未授權")
    
    contents = await file.read()
    filename = file.filename.lower()
    rows_data = []

    if filename.endswith(".xlsx") or filename.endswith(".xls"):
        wb = openpyxl.load_workbook(io.BytesIO(contents), data_only=True)
        ws = wb.active
        for row in ws.iter_rows(values_only=True):
            if any(row):
                rows_data.append(list(row))
    else:
        text = contents.decode("utf-8-sig", errors="ignore")
        reader = csv.reader(io.StringIO(text))
        for row in reader:
            if any(row):
                rows_data.append(row)

    if not rows_data or len(rows_data) < 2:
        raise HTTPException(status_code=400, detail="上傳檔案無有效資料列！")

    header = [str(col).strip() for col in rows_data[0]]
    email_idx = -1
    date_idx = -1

    for idx, col_name in enumerate(header):
        cleaned = col_name.replace("（", "(").replace("）", ")").strip()
        if "補課平台" in cleaned or cleaned == "Email(補課平台)" or cleaned.lower() == "email_pathdemy":
            email_idx = idx
        elif "補課日期" in cleaned or "補課時間" in cleaned or "日期" in cleaned or "時間" in cleaned:
            date_idx = idx

    if email_idx == -1: email_idx = 0
    if date_idx == -1: date_idx = 1 if len(header) > 1 else 0

    count = 0
    for row in rows_data[1:]:
        if len(row) <= email_idx: continue
        raw_email = str(row[email_idx] or "").strip().lower()
        if not raw_email or "@" not in raw_email: continue

        raw_date = str(row[date_idx] or "").strip() if len(row) > date_idx else ""
        if not raw_date:
            raw_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        matched_student = None
        for s in db.get("students", []):
            s_pathdemy = (s.get("email_pathdemy") or "").strip().lower()
            s_email = (s.get("email") or "").strip().lower()
            if raw_email in [s_pathdemy, s_email] or (raw_email.startswith("vinnyhuang") and s.get("name") == "黃雅筠"):
                matched_student = s
                break

        if matched_student:
            student_id = matched_student["id"]
            matched_student["email_pathdemy"] = raw_email
            
            key = f"{student_id}_{course_id}"
            db["attendances"][key] = {
                "status": "MAKEUP_DONE",
                "makeup_date": raw_date,
                "platform_email": raw_email,
                "note": "管理員批次匯入",
                "imported_by": admin["email"],
                "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            count += 1

    return {"success": True, "count": count}

# 刪除補課紀錄
@app.delete("/api/admin/courses/{course_id}/pathdemy/{student_id}")
@app.delete("/api/admin/courses/{course_id}/makeups/{student_id}")
async def cancel_makeup(course_id: int, student_id: int, request: Request):
    if not get_current_admin(request):
        raise HTTPException(status_code=401, detail="未授權")
    key = f"{student_id}_{course_id}"
    if key in db["attendances"]:
        del db["attendances"][key]
    return {"success": True, "message": "已刪除該筆補課紀錄"}

# ==========================================
# 學員與課程 CRUD 保持原樣
# ==========================================
@app.post("/api/admin/students")
async def add_student(request: Request):
    if not get_current_admin(request): raise HTTPException(status_code=401, detail="未授權")
    data = await request.json()
    new_id = max([s["id"] for s in db["students"]], default=0) + 1
    email = data.get("email", "").strip()
    email_pathdemy = data.get("email_pathdemy", "").strip() or email
    new_student = {
        "id": new_id, 
        "name": data.get("name", "").strip(), 
        "email": email, 
        "email_pathdemy": email_pathdemy, 
        "phone": data.get("phone", "").strip()
    }
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
            s["email_pathdemy"] = data.get("email_pathdemy", s.get("email_pathdemy", s["email"])).strip()
            s["phone"] = data.get("phone", s["phone"]).strip()
            return {"success": True, "student": s}
    raise HTTPException(status_code=404, detail="查無此學員")

@app.delete("/api/admin/students/{student_id}")
async def delete_student(student_id: int, request: Request):
    if not get_current_admin(request): raise HTTPException(status_code=401, detail="未授權")
    db["students"] = [s for s in db["students"] if s["id"] != student_id]
    return {"success": True}