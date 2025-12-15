# routes_rating.py
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException
from fastapi.responses import RedirectResponse

from db import getDB
from deps import require_role, session_user

router = APIRouter()


# ------------------------------------------------------------
# 共用：檢查 job 是否存在、已結案、且 user 是案件相關人
# ------------------------------------------------------------
async def _check_job_is_closed(job_id: int, user_id: int, conn):
    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT id, client_id, contractor_id, status
            FROM jobs
            WHERE id = %s
            """,
            (job_id,),
        )
        job = await cur.fetchone()

    if not job:
        raise HTTPException(status_code=404, detail="查無此案件")

    if job["status"] != "closed":
        raise HTTPException(status_code=400, detail="案件尚未結案，無法評價")

    if job["client_id"] != user_id and job["contractor_id"] != user_id:
        raise HTTPException(status_code=403, detail="你不是此案件的相關人員")

    return job


def _validate_dims(dim1: int, dim2: int, dim3: int):
    for d in (dim1, dim2, dim3):
        if d < 1 or d > 5:
            raise HTTPException(status_code=400, detail="評分必須介於 1 到 5")


# ------------------------------------------------------------
# 承包人 → 評價委託人
# ------------------------------------------------------------
@router.post("/job/rate-client")
async def rate_client(
    job_id: int = Form(...),
    dim1: int = Form(...),
    dim2: int = Form(...),
    dim3: int = Form(...),
    comment: Optional[str] = Form(""),
    user=Depends(require_role("contractor")),
    conn=Depends(getDB),
):
    contractor_id = user["user_id"]
    _validate_dims(dim1, dim2, dim3)

    job = await _check_job_is_closed(job_id, contractor_id, conn)
    if job["contractor_id"] != contractor_id:
        raise HTTPException(status_code=403, detail="你不是這案件的承包人，不能評委託人")

    async with conn.cursor() as cur:
        await cur.execute(
            """
            INSERT INTO user_ratings (
                job_id, rater_id, target_id, target_role,
                dim1, dim2, dim3, comment
            )
            VALUES (%s, %s, %s, 'client', %s, %s, %s, %s)
            ON CONFLICT (job_id, rater_id, target_id, target_role)
            DO NOTHING
            """,
            (job_id, contractor_id, job["client_id"], dim1, dim2, dim3, comment),
        )

        if cur.rowcount == 0:
            return RedirectResponse(
                url=f"/jobDetail.html?job_id={job_id}&toast=你已經送出過評價（送出後不可修改）",
                status_code=303,
            )

    return RedirectResponse(
        url=f"/jobDetail.html?job_id={job_id}&toast=已成功評價委託人",
        status_code=303,
    )


# ------------------------------------------------------------
# 委託人 → 評價承包人
# ------------------------------------------------------------
@router.post("/job/rate-contractor")
async def rate_contractor(
    job_id: int = Form(...),
    dim1: int = Form(...),
    dim2: int = Form(...),
    dim3: int = Form(...),
    comment: Optional[str] = Form(""),
    user=Depends(require_role("client")),
    conn=Depends(getDB),
):
    client_id = user["user_id"]
    _validate_dims(dim1, dim2, dim3)

    job = await _check_job_is_closed(job_id, client_id, conn)
    if job["client_id"] != client_id:
        raise HTTPException(status_code=403, detail="你不是此案件的委託人，不能評承包人")

    async with conn.cursor() as cur:
        await cur.execute(
            """
            INSERT INTO user_ratings (
                job_id, rater_id, target_id, target_role,
                dim1, dim2, dim3, comment
            )
            VALUES (%s, %s, %s, 'contractor', %s, %s, %s, %s)
            ON CONFLICT (job_id, rater_id, target_id, target_role)
            DO NOTHING
            """,
            (job_id, client_id, job["contractor_id"], dim1, dim2, dim3, comment),
        )

        if cur.rowcount == 0:
            return RedirectResponse(
                url=f"/jobDetail.html?job_id={job_id}&toast=你已經送出過評價（送出後不可修改）",
                status_code=303,
            )

    return RedirectResponse(
        url=f"/jobDetail.html?job_id={job_id}&toast=已成功評價承包人",
        status_code=303,
    )


# ------------------------------------------------------------
# 查「某案件」的所有評價（給 jobDetail 用）
# GET /job/{job_id}/ratings
# ------------------------------------------------------------
@router.get("/job/{job_id}/ratings")
async def get_job_ratings(job_id: int, user=Depends(session_user), conn=Depends(getDB)):
    # 權限：必須是此案件相關人
    async with conn.cursor() as cur:
        await cur.execute(
            "SELECT id, client_id, contractor_id, status FROM jobs WHERE id=%s",
            (job_id,),
        )
        job = await cur.fetchone()

    if not job:
        raise HTTPException(status_code=404, detail="查無此案件")

    if user["user_id"] not in (job["client_id"], job["contractor_id"]):
        raise HTTPException(status_code=403, detail="你不是此案件的相關人")

    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT job_id, rater_id, target_id, target_role,
                   dim1, dim2, dim3, comment, created_at
            FROM user_ratings
            WHERE job_id = %s
            ORDER BY created_at DESC
            """,
            (job_id,),
        )
        rows = await cur.fetchall()

    return {"ratings": rows}


# ------------------------------------------------------------
# 查某個使用者的平均評價 + 所有評論（你原本就有）
# GET /ratings/summary?user_id=...
# ------------------------------------------------------------
@router.get("/ratings/summary")
async def get_user_rating_summary(user_id: int, conn=Depends(getDB)):
    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT
                ROUND(AVG(dim1)::numeric, 1) AS avg_dim1,
                ROUND(AVG(dim2)::numeric, 1) AS avg_dim2,
                ROUND(AVG(dim3)::numeric, 1) AS avg_dim3,
                COUNT(*)::int AS count
            FROM user_ratings
            WHERE target_id = %s
            """,
            (user_id,),
        )
        avg_row = await cur.fetchone()

        await cur.execute(
            """
            SELECT job_id, target_role, comment, created_at
            FROM user_ratings
            WHERE target_id = %s
              AND COALESCE(comment,'') <> ''
            ORDER BY created_at DESC
            """,
            (user_id,),
        )
        comments = await cur.fetchall()

    return {"average": avg_row, "comments": comments}
