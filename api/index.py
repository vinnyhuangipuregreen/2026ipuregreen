import os
from datetime import datetime
from typing import Optional
from fastapi import FastAPI, Request, Form, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import jwt

app = FastAPI(title="BLIA佛光永續學院簽到系統 - iPure Green")
templates = Jinja2Templates(directory="templates")

SECRET_KEY = os.getenv("SECRET_KEY", "ipuregreen-blia-secret-key-2026")

# 模擬記憶體/資料庫儲存 (正式上線可連線 PostgreSQL)
db = {
    "students": [
        {"id": 1, "name": "黃雅筠", "email": "vinnyhuang.ipuregreen@gmail.com", "phone": "0912345678"}
    ],
    "courses": [
        {
            "id": 1,
            "title": "導論：自然永續的核心觀念與倫理基礎",
            "course_date": "2026/09/15",
            "course_time": "18:00-22:00",
            "open_time": "2026-09-15 18:00:00",
            "close_time": "2026-09-15 22:00:00"
        },
        {
            "id": 2,
            "title": "健康一體（One Health）與系統思維",
            "course_date": "2026/09/22",
            "course_time": "18:30-21:30",
            "open_time": "2026-09-22 18:00:00",
            "close_time": "2026-09-22 21:30:00"
        }
    ],
    "attendances": {
        # 鍵為 f"{student_id}_{course_id}" 防止並發重複簽到
        "1_1": {"status": "SIGNED_IN", "signed_at": "2026-09-15 18:05:12"}
    }
}

# --- 身份認證輔助函式 ---
def get_current_student(request: Request):
    token = request.cookies.get("token")
    if not token:
        return None
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        return next((s for s in db["students"] if s["id"] == payload["id"]), None)
    except:
        return None

# --- 頁面路由 ---
@app.get("/", response_class=HTMLResponse)
async def login_page(request: Request):
    student = get_current_student(request)
    if student:
        return RedirectResponse(url="/dashboard")
    return templates.TemplateResponse("login.html", {"request": request})

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page(request: Request):
    student = get_current_student(request)
    if not student:
        return RedirectResponse(url="/")
    
    # 統計個人紀錄
    signed_count = sum(1 for k, v in db["attendances"].items() if k.startswith(f"{student['id']}_") and v["status"] == "SIGNED_IN")
    leave_count = sum(1 for k, v in db["attendances"].items() if k.startswith(f"{student['id']}_") and v["status"] == "ON_LEAVE")
    makeup_count = sum(1 for k, v in db["attendances"].items() if k.startswith(f"{student['id']}_") and v["status"] == "MAKEUP_DONE")
    absent_count = sum(1 for k, v in db["attendances"].items() if k.startswith(f"{student['id']}_") and v["status"] == "ABSENT")

    courses_view = []
    for c in db["courses"]:
        record = db["attendances"].get(f"{student['id']}_{c['id']}")
        status = record["status"] if record else "PENDING"
        courses_view.append({**c, "status": status})

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "student": student,
        "stats": {
            "signed": signed_count,
            "leave": leave_count,
            "makeup": makeup_count,
            "absent": absent_count
        },
        "courses": courses_view
    })

@app.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request):
    return templates.TemplateResponse("admin.html", {
        "request": request,
        "students": db["students"],
        "courses": db["courses"]
    })

# --- API 端點 ---
@app.post("/api/auth/login")
async def api_login(email: str = Form(...), phone: str = Form(...)):
    student = next((s for s in db["students"] if s["email"].strip().lower() == email.strip().lower() and s["phone"].strip() == phone.strip()), None)
    if not student:
        return JSONResponse(status_code=401, content={"error": "查無此報名資料，請確認 Email 與電話！"})
    
    token = jwt.encode({"id": student["id"], "email": student["email"]}, SECRET_KEY, algorithm="HS256")
    resp = JSONResponse(content={"success": True})
    resp.set_cookie("token", token, httponly=True, max_age=86400*7)
    return resp

@app.post("/api/attendance/checkin")
async def api_checkin(request: Request):
    student = get_current_student(request)
    if not student:
        raise HTTPException(status_code=401, detail="請先登入")
    data = await request.json()
    course_id = data.get("course_id")
    
    # 唯一 key 寫入，防併發衝突
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