from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from db import getDB
from deps import session_user

router = APIRouter()

# 顯示評價表單 (導向到 HTML)
@router.get("/review/form")
async def review_form_page(job_id: int, user=Depends(session_user), conn=Depends(getDB)):
    async with conn.cursor() as cur:
        await cur.execute("SELECT * FROM jobs WHERE id = %s", (job_id,))
        job = await cur.fetchone()
        
        if not job or job["status"] != "closed":
            return HTMLResponse("案件尚未結案，無法評價", status_code=400)
            
        is_client = (job["client_id"] == user["user_id"])
        is_contractor = (job["contractor_id"] == user["user_id"])
        
        if not (is_client or is_contractor):
            return HTMLResponse("您無權評價此案件", status_code=403)
            
        target_role = "contractor" if is_client else "client"

    return RedirectResponse(
        url=f"/reviewForm.html?job_id={job_id}&target_role={target_role}", 
        status_code=302
    )

# 提交評價
@router.post("/review/add")
async def add_review(
    job_id: int = Form(...),
    rating_1: int = Form(...),
    rating_2: int = Form(...),
    rating_3: int = Form(...),
    comment: str = Form(""),
    user=Depends(session_user),
    conn=Depends(getDB)
):
    user_id = user["user_id"]
    if not all(1 <= r <= 5 for r in [rating_1, rating_2, rating_3]):
        return HTMLResponse("評分需介於 1~5 之間", status_code=400)

    try:
        async with conn.transaction():
            async with conn.cursor() as cur:
                await cur.execute("SELECT client_id, contractor_id, status FROM jobs WHERE id = %s", (job_id,))
                job = await cur.fetchone()
                
                if not job or job["status"] != "closed":
                    raise HTTPException(status_code=400, detail="案件未結案")

                if user_id == job["client_id"]:
                    to_user_id = job["contractor_id"]
                    target_role = "contractor"
                elif user_id == job["contractor_id"]:
                    to_user_id = job["client_id"]
                    target_role = "client"
                else:
                    raise HTTPException(status_code=403, detail="非案件參與者")

                await cur.execute(
                    """
                    INSERT INTO reviews (job_id, from_user_id, to_user_id, target_role, rating_1, rating_2, rating_3, comment)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (job_id, from_user_id) DO UPDATE SET
                        rating_1 = EXCLUDED.rating_1,
                        rating_2 = EXCLUDED.rating_2,
                        rating_3 = EXCLUDED.rating_3,
                        comment = EXCLUDED.comment,
                        created_at = NOW()
                    """,
                    (job_id, user_id, to_user_id, target_role, rating_1, rating_2, rating_3, comment)
                )
                
                await cur.execute(
                    "INSERT INTO job_events (job_id, actor_id, event_type, message, description) VALUES (%s, %s, 'REVIEW_SUBMITTED', '已送出評價', '使用者已對合作對象送出評價。')",
                    (job_id, user_id)
                )
    except Exception as e:
        return HTMLResponse(f"評價失敗：{e}", status_code=500)

    return RedirectResponse(url=f"/jobDetail.html?job_id={job_id}", status_code=302)

# API: 取得詳細評價
@router.get("/api/reviews/{user_id}")
async def get_user_reviews(user_id: int, role: str, conn=Depends(getDB)):
    async with conn.cursor() as cur:
        # 統計
        await cur.execute(
            """
            SELECT COUNT(*) as count, AVG((rating_1 + rating_2 + rating_3) / 3.0) as avg_total,
                   AVG(rating_1) as avg_r1, AVG(rating_2) as avg_r2, AVG(rating_3) as avg_r3
            FROM reviews WHERE to_user_id = %s AND target_role = %s
            """,
            (user_id, role)
        )
        stats = await cur.fetchone()
        
        # 詳細列表 (最新的 10 筆)
        await cur.execute(
            """
            SELECT r.rating_1, r.rating_2, r.rating_3, r.comment, r.created_at, u.username as from_name
            FROM reviews r JOIN users u ON u.id = r.from_user_id
            WHERE r.to_user_id = %s AND r.target_role = %s
            ORDER BY r.created_at DESC LIMIT 10
            """,
            (user_id, role)
        )
        comments = await cur.fetchall()

    return {"stats": stats, "comments": comments}