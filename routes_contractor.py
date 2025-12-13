from pathlib import Path
import os
import shutil
import uuid
from datetime import date

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse

from db import getDB
from deps import require_role

router = APIRouter()


# 承包人：可報價案件列表
@router.get("/contractor/jobs")
async def contractor_jobs(user=Depends(require_role("contractor")), conn=Depends(getDB)):
    contractor_id = user["user_id"]
    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT
                j.id, j.title, j.status, j.created_at, j.client_id,
                u.username AS client_name,
                COALESCE(bc.cnt, 0) AS bid_count,
                mb.price AS my_bid_price,
                (
                    SELECT AVG((rating_1 + rating_2 + rating_3)/3.0)
                    FROM reviews r
                    WHERE r.to_user_id = j.client_id AND r.target_role = 'client'
                ) as client_avg_rating
            FROM jobs j
            JOIN users u ON u.id = j.client_id
            LEFT JOIN LATERAL (
                SELECT COUNT(*)::int AS cnt FROM bids b WHERE b.job_id = j.id
            ) bc ON TRUE
            LEFT JOIN LATERAL (
                SELECT price FROM bids WHERE job_id = j.id AND contractor_id = %s LIMIT 1
            ) mb ON TRUE
            WHERE j.status = 'pending'
              AND j.client_id <> %s
              AND (j.due_date IS NULL OR j.due_date >= CURRENT_DATE)
            ORDER BY j.id DESC
            """,
            (contractor_id, contractor_id),
        )
        rows = await cur.fetchall()
    return {"contractor": contractor_id, "count": len(rows), "items": rows}


# 新增 / 更新報價
@router.post("/bid/new")
async def bid_new(
    job_id: int = Form(...),
    price: int = Form(...),
    note: str = Form(""),
    proposal_file: UploadFile = File(...),
    user=Depends(require_role("contractor")),
    conn=Depends(getDB),
):
    contractor_id = user["user_id"]
    contractor_username = user["username"]

    if price < 0 or price > 999_999_999:
        return HTMLResponse(f"金額錯誤<br><a href='/bidForm.html?job_id={job_id}'>回上一頁</a>", status_code=400)

    ext = os.path.splitext(proposal_file.filename or "")[1].lower()
    if ext != ".pdf":
        return HTMLResponse(f"僅限 PDF<br><a href='/bidForm.html?job_id={job_id}'>回上一頁</a>", status_code=400)

    uploads_dir = Path("uploads")
    uploads_dir.mkdir(exist_ok=True)
    safe_proposal_filename = f"proposal_job_{job_id}_user_{contractor_id}_{uuid.uuid4().hex}{ext}"
    proposal_path = uploads_dir / safe_proposal_filename

    try:
        with proposal_path.open("wb") as buffer:
            shutil.copyfileobj(proposal_file.file, buffer)
    finally:
        proposal_file.file.close()

    try:
        async with conn.transaction():
            async with conn.cursor() as cur:
                await cur.execute("SELECT client_id, status, due_date FROM jobs WHERE id=%s FOR UPDATE", (job_id,))
                job = await cur.fetchone()
                if not job: raise HTTPException(status_code=404, detail="Job not found")
                if job["status"] != "pending": raise HTTPException(status_code=400, detail="Not pending")
                if job["client_id"] == contractor_id: raise HTTPException(status_code=400, detail="Own job")
                if job["due_date"] is not None and date.today() > job["due_date"]: raise HTTPException(status_code=400, detail="Expired")

                await cur.execute(
                    """
                    INSERT INTO bids (job_id, contractor_id, price, note, proposal_file, proposal_original_name)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (job_id, contractor_id) DO UPDATE SET
                        price = EXCLUDED.price, note = EXCLUDED.note,
                        proposal_file = EXCLUDED.proposal_file, proposal_original_name = EXCLUDED.proposal_original_name
                    """,
                    (job_id, contractor_id, price, note, safe_proposal_filename, proposal_file.filename),
                )
                await cur.execute(
                    "INSERT INTO job_events (job_id, actor_id, event_type, message, description) VALUES (%s, %s, 'BID_SUBMITTED', %s, %s)",
                    (job_id, contractor_id, f"報價 ${price}", f"承包人 {contractor_username} 報價 ${price}")
                )
    except HTTPException as e:
        return HTMLResponse(f"失敗：{e.detail}", status_code=e.status_code)
    except Exception as e:
        return HTMLResponse(f"失敗：{e}", status_code=500)
    return RedirectResponse(url="/contractorMyJobs.html", status_code=302)


# 承包人：自己的報價 / 案件列表 (主要修改這裡)
@router.get("/contractor/my-jobs")
async def contractor_my_jobs(user=Depends(require_role("contractor")), conn=Depends(getDB)):
    contractor_id = user["user_id"]
    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT 
                j.id, j.title, j.status, j.updated_at, j.client_id, -- 記得撈 client_id
                u.username AS client_name,
                b.price AS my_bid_price,
                (j.contractor_id = %s) AS am_i_winner,
                -- 新增：計算 Client 平均評價
                (
                    SELECT AVG((rating_1 + rating_2 + rating_3)/3.0)
                    FROM reviews r
                    WHERE r.to_user_id = j.client_id AND r.target_role = 'client'
                ) as client_avg_rating
            FROM jobs j
            LEFT JOIN bids b ON b.job_id = j.id AND b.contractor_id = %s
            JOIN users u ON u.id = j.client_id
            WHERE (b.contractor_id = %s) OR (j.contractor_id = %s AND j.status <> 'invited')
            GROUP BY j.id, u.username, b.price, j.client_id
            ORDER BY j.updated_at DESC
            """,
            (contractor_id, contractor_id, contractor_id, contractor_id),
        )
        rows = await cur.fetchall()
    return {"contractor": contractor_id, "count": len(rows), "items": rows}


# 承包人：我的邀請
@router.get("/contractor/my-invitations")
async def contractor_my_invitations(user=Depends(require_role("contractor")), conn=Depends(getDB)):
    contractor_id = user["user_id"]
    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT 
                j.id, j.title, j.budget, j.due_date, j.created_at,
                u.username AS client_name
            FROM jobs j
            JOIN users u ON u.id = j.client_id
            WHERE j.status = 'invited' 
              AND j.contractor_id = %s
            ORDER BY j.created_at DESC
            """,
            (contractor_id,),
        )
        rows = await cur.fetchall()
    return {"items": rows}


@router.post("/invitation/accept")
async def invitation_accept(job_id: int = Form(...), user=Depends(require_role("contractor")), conn=Depends(getDB)):
    contractor_id = user["user_id"]
    try:
        async with conn.transaction():
            async with conn.cursor() as cur:
                await cur.execute("SELECT 1 FROM jobs WHERE id = %s AND contractor_id = %s AND status = 'invited' FOR UPDATE", (job_id, contractor_id))
                if not await cur.fetchone(): raise HTTPException(status_code=403, detail="Invitation error")
                await cur.execute("UPDATE jobs SET status = 'accepted', updated_at = NOW() WHERE id = %s", (job_id,))
                await cur.execute("INSERT INTO job_events (job_id, actor_id, event_type, message, description) VALUES (%s, %s, 'INVITE_ACCEPTED', '接受邀請', '接受邀請')", (job_id, contractor_id))
    except Exception as e: return HTMLResponse(f"錯誤：{e}", status_code=500)
    return RedirectResponse(url=f"/jobDetail.html?job_id={job_id}", status_code=302)


@router.post("/invitation/decline")
async def invitation_decline(job_id: int = Form(...), user=Depends(require_role("contractor")), conn=Depends(getDB)):
    contractor_id = user["user_id"]
    try:
        async with conn.transaction():
            async with conn.cursor() as cur:
                await cur.execute("SELECT 1 FROM jobs WHERE id = %s AND contractor_id = %s AND status = 'invited' FOR UPDATE", (job_id, contractor_id))
                if not await cur.fetchone(): raise HTTPException(status_code=403, detail="Invitation error")
                await cur.execute("UPDATE jobs SET status = 'pending', contractor_id = NULL, updated_at = NOW() WHERE id = %s", (job_id,))
                await cur.execute("INSERT INTO job_events (job_id, actor_id, event_type, message, description) VALUES (%s, %s, 'INVITE_DECLINED', '婉拒邀請', '婉拒邀請')", (job_id, contractor_id))
    except Exception as e: return HTMLResponse(f"錯誤：{e}", status_code=500)
    return RedirectResponse(url="/contractorMyInvitations.html", status_code=302)


@router.post("/job/upload")
async def job_upload(user=Depends(require_role("contractor")), job_id: int = Form(...), report_file: UploadFile = File(...), conn=Depends(getDB)):
    contractor_id = user["user_id"]
    ext = os.path.splitext(report_file.filename or "")[1].lower()
    if ext not in [".pdf", ".zip", ".docx", ".pptx"]: return HTMLResponse("檔案格式錯誤", status_code=400)
    
    uploads_dir = Path("uploads")
    uploads_dir.mkdir(exist_ok=True)
    safe_filename = f"job_{job_id}_user_{contractor_id}_{uuid.uuid4().hex}{ext}"
    
    try:
        with (uploads_dir / safe_filename).open("wb") as buffer:
            shutil.copyfileobj(report_file.file, buffer)
    finally:
        report_file.file.close()

    try:
        async with conn.transaction():
            async with conn.cursor() as cur:
                await cur.execute("SELECT id FROM jobs WHERE id=%s AND contractor_id=%s AND (status='accepted' OR status='rejected') FOR UPDATE", (job_id, contractor_id))
                if not await cur.fetchone(): raise HTTPException(status_code=403, detail="Permission denied")

                await cur.execute("SELECT 1 FROM job_events WHERE job_id=%s AND event_type='JOB_REJECTED' LIMIT 1", (job_id,))
                is_re_upload = await cur.fetchone()

                await cur.execute("SELECT COALESCE(MAX(version), 0)+1 AS v FROM job_result_files WHERE job_id=%s", (job_id,))
                version = (await cur.fetchone())["v"]

                await cur.execute("INSERT INTO job_result_files (job_id, contractor_id, version, file_path, original_name) VALUES (%s, %s, %s, %s, %s)", (job_id, contractor_id, version, safe_filename, report_file.filename))
                await cur.execute("UPDATE jobs SET status='uploaded', report_file=%s, updated_at=NOW() WHERE id=%s", (safe_filename, job_id))
                
                evt = "REPORT_RE_UPLOADED" if is_re_upload else "REPORT_UPLOADED"
                await cur.execute("INSERT INTO job_events (job_id, actor_id, event_type, message, description) VALUES (%s, %s, %s, '上傳檔案', %s)", (job_id, contractor_id, evt, f"上傳了 {report_file.filename}"))
    except Exception as e: return HTMLResponse(f"錯誤：{e}", status_code=500)
    return RedirectResponse(url=f"/jobDetail.html?job_id={job_id}", status_code=302)