import hashlib
from fastapi import APIRouter, Depends, Form, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from db import getDB
from deps import session_user

router = APIRouter()

@router.post("/register")
async def register(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    role: str = Form(...),
    conn=Depends(getDB),
):
    if role not in ("client", "contractor"):
        return HTMLResponse("註冊失敗：角色錯誤<br><a href='/registerForm.html'>回註冊</a>", status_code=400)

    pwd_hash = hashlib.sha256(password.encode()).hexdigest()

    async with conn.cursor() as cur:
        try:
            await cur.execute(
                "INSERT INTO users (username, password_hash, role) VALUES (%s, %s, %s)",
                (username, pwd_hash, role),
            )
        except Exception as e:
            return HTMLResponse(
                f"註冊失敗：{e}<br><a href='/registerForm.html'>回註冊</a>",
                status_code=400,
            )
    return RedirectResponse(url="/loginForm.html", status_code=302)


@router.post("/login")
async def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    conn=Depends(getDB),
):
    pwd_hash = hashlib.sha256(password.encode()).hexdigest()
    async with conn.cursor() as cur:
        await cur.execute(
            "SELECT id, role, username FROM users WHERE username=%s AND password_hash=%s",
            (username, pwd_hash),
        )
        user = await cur.fetchone()

    if not user:
        return HTMLResponse(
            "帳號或密碼錯誤<br><a href='/loginForm.html'>重新登入</a>",
            status_code=401,
        )

    request.session["user_id"] = user["id"]
    request.session["role"] = user["role"]
    request.session["username"] = user["username"]
    return RedirectResponse(url="/", status_code=302)


@router.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/loginForm.html", status_code=302)


# 修改這裡：加入計算自己平均分數的邏輯
@router.get("/me")
async def me(request: Request, conn=Depends(getDB)):
    try:
        # 1. 取得 Session 使用者資訊
        user = session_user(request)
        user_id = user["user_id"]
        role = user["role"]

        # 2. 去資料庫查自己的平均分
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT AVG((rating_1 + rating_2 + rating_3) / 3.0) as avg_rating
                FROM reviews
                WHERE to_user_id = %s AND target_role = %s
                """,
                (user_id, role)
            )
            row = await cur.fetchone()
            rating = row["avg_rating"] if row and row["avg_rating"] else None
        
        # 3. 回傳整合後的資料
        return {**user, "rating": rating}

    except HTTPException:
        return RedirectResponse(url="/loginForm.html", status_code=302)