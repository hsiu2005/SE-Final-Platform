# routes_issue.py

from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Form
from fastapi.responses import RedirectResponse
from typing import Optional

from db import getDB
from deps import require_role, session_user

router = APIRouter()


# ------------------------------------------------------------
# 小工具：統一 redirect + toast 訊息（避免黑頁）
# ------------------------------------------------------------
def _redirect_job_detail(job_id: int, toast: str, status_code: int = 303):
    msg = quote(toast)
    return RedirectResponse(url=f"/jobDetail.html?job_id={job_id}&toast={msg}", status_code=status_code)


# ------------------------------------------------------------
# 工具：檢查案件存在＋是否為委託人或承包人
# ------------------------------------------------------------
async def _get_job(conn, job_id: int):
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

    return job


# ------------------------------------------------------------
# 取得所有 issue（含留言）
# GET /job/{job_id}/issues
# ------------------------------------------------------------
@router.get("/job/{job_id}/issues")
async def get_issues(job_id: int, user=Depends(session_user), conn=Depends(getDB)):

    job = await _get_job(conn, job_id)

    # 必須是案件相關人
    if user["user_id"] not in (job["client_id"], job["contractor_id"]):
        raise HTTPException(status_code=403, detail="你不是此案件的相關人")

    async with conn.cursor() as cur:
        # ✅ 查 issues：加上建立者名稱
        await cur.execute(
            """
            SELECT
                i.id, i.title, i.description, i.status,
                i.creator_id,
                u.username AS creator_name,
                i.created_at, i.closed_at
            FROM job_issues i
            LEFT JOIN users u ON u.id = i.creator_id
            WHERE i.job_id = %s
            ORDER BY i.created_at ASC
            """,
            (job_id,),
        )
        issues = await cur.fetchall()

        # ✅ 查 comments：加上留言者名稱
        await cur.execute(
            """
            SELECT
                c.issue_id,
                c.author_id,
                u.username AS author_name,
                c.content,
                c.created_at
            FROM job_issue_comments c
            LEFT JOIN users u ON u.id = c.author_id
            WHERE c.issue_id IN (SELECT id FROM job_issues WHERE job_id = %s)
            ORDER BY c.created_at ASC
            """,
            (job_id,),
        )
        comments = await cur.fetchall()

    # 把留言整理進 issue 裡面
    issue_map = {i["id"]: dict(i, comments=[]) for i in issues}

    for c in comments:
        issue_map[c["issue_id"]]["comments"].append(c)

    return list(issue_map.values())



# ------------------------------------------------------------
# 委託人建立 issue
# POST /job/issue/new
# ------------------------------------------------------------
@router.post("/job/issue/new")
async def create_issue(
    job_id: int = Form(...),
    title: str = Form(...),
    description: Optional[str] = Form(""),
    user=Depends(require_role("client")),
    conn=Depends(getDB),
):
    client_id = user["user_id"]

    # 案件不存在：表單送出時也不要黑頁
    try:
        job = await _get_job(conn, job_id)
    except HTTPException:
        return _redirect_job_detail(job_id, "查無此案件")

    # 只有委託人能建立 issue：不要黑頁，回頁面提示
    if job["client_id"] != client_id:
        return _redirect_job_detail(job_id, "只有委託人能建立 Issue")

    # 只能在 uploaded/rejected 建立：不要黑頁，回頁面提示
    if job["status"] not in ("uploaded", "rejected"):
        return _redirect_job_detail(job_id, "目前案件不在可建立 Issue 的階段（需已上傳成果）")

    async with conn.cursor() as cur:
        await cur.execute(
            """
            INSERT INTO job_issues (job_id, creator_id, title, description)
            VALUES (%s, %s, %s, %s)
            """,
            (job_id, client_id, title, description),
        )

    return _redirect_job_detail(job_id, "Issue 已建立")


# ------------------------------------------------------------
# 任一方新增留言
# POST /job/issue/comment
# ------------------------------------------------------------
@router.post("/job/issue/comment")
async def add_issue_comment(
    issue_id: int = Form(...),
    content: str = Form(...),
    user=Depends(session_user),
    conn=Depends(getDB),
):
    user_id = user["user_id"]

    # 找出這個 issue 的 job_id 與雙方資訊 + issue 狀態
    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT j.id AS job_id, j.client_id, j.contractor_id, i.status
            FROM job_issues i
            JOIN jobs j ON j.id = i.job_id
            WHERE i.id = %s
            """,
            (issue_id,),
        )
        row = await cur.fetchone()

    # 查無 issue：不要黑頁，導回（job_id 不知道就回首頁或回上一頁也行）
    if not row:
        # 這裡沒有 job_id 可導回，只能導到首頁 or 你自訂錯誤頁
        return RedirectResponse(url="/?toast=" + quote("查無此 Issue"), status_code=303)

    job_id = row["job_id"]

    # 必須是 client 或 contractor 才能留言：不要黑頁，導回提示
    if user_id not in (row["client_id"], row["contractor_id"]):
        return _redirect_job_detail(job_id, "無權限留言")

    # ✅ Issue 關閉後禁止再留言：不要黑頁，導回提示
    if row["status"] == "closed":
        return _redirect_job_detail(job_id, "此 Issue 已關閉，無法再留言")

    async with conn.cursor() as cur:
        await cur.execute(
            """
            INSERT INTO job_issue_comments (issue_id, author_id, content)
            VALUES (%s, %s, %s)
            """,
            (issue_id, user_id, content),
        )

    return _redirect_job_detail(job_id, "留言成功")


# ------------------------------------------------------------
# 委託人關閉 issue
# POST /job/issue/close
# ------------------------------------------------------------
@router.post("/job/issue/close")
async def close_issue(
    issue_id: int = Form(...),
    user=Depends(require_role("client")),
    conn=Depends(getDB),
):
    client_id = user["user_id"]

    # 找出 issue 與 job 的資訊（含 job_id 用來 redirect）
    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT i.id, i.status, i.job_id, j.client_id
            FROM job_issues i
            JOIN jobs j ON j.id = i.job_id
            WHERE i.id = %s
            """,
            (issue_id,),
        )
        row = await cur.fetchone()

    if not row:
        return RedirectResponse(url="/?toast=" + quote("查無此 Issue"), status_code=303)

    job_id = row["job_id"]

    # 只有委託人能關閉：不要黑頁，導回提示
    if row["client_id"] != client_id:
        return _redirect_job_detail(job_id, "只有委託人能關閉 Issue")

    # 已關閉：也不要黑頁
    if row["status"] == "closed":
        return _redirect_job_detail(job_id, "此 Issue 已經關閉")

    async with conn.cursor() as cur:
        await cur.execute(
            """
            UPDATE job_issues
            SET status = 'closed', closed_at = NOW()
            WHERE id = %s
            """,
            (issue_id,),
        )

    return _redirect_job_detail(job_id, "Issue 已關閉")
