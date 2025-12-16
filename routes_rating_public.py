# routes_rating_public.py
from fastapi import APIRouter, Depends, Query
from typing import Optional
from db import getDB
from psycopg.rows import dict_row
from deps import session_user


router = APIRouter()

@router.get("/user/{target_id}/rating-summary")
async def rating_summary(
    target_id: int,
    as_target_role: str = Query(..., pattern="^(client|contractor)$"),
    conn = Depends(getDB),
):
    """
    回傳某個使用者(被評者)在指定角色下的平均評價與留言
    as_target_role:
      - client: 這個人以委託人身份被評
      - contractor: 這個人以承包人身份被評
    """

    # ✅ 讓 fetchone()/fetchall() 回來是 dict（不然 stats["count"] 會爆）
    async with conn.cursor(row_factory=dict_row) as cur:
        # 平均分（總平均 + 三維度平均 + 評價數）
        await cur.execute(
            """
            SELECT
              COUNT(*)::int AS count,
              ROUND(AVG((dim1+dim2+dim3)/3.0)::numeric, 2) AS avg_overall,
              ROUND(AVG(dim1)::numeric, 2) AS avg_dim1,
              ROUND(AVG(dim2)::numeric, 2) AS avg_dim2,
              ROUND(AVG(dim3)::numeric, 2) AS avg_dim3
            FROM user_ratings
            WHERE target_id=%s AND target_role=%s
            """,
            (target_id, as_target_role),
        )
        stats = await cur.fetchone()

        # ✅ 最新留言（加上 from_name；最多 10 筆；只拿有 comment 的）
        await cur.execute(
            """
            SELECT
              u.username AS from_name,
              r.comment,
              r.created_at
            FROM user_ratings r
            JOIN users u ON u.id = r.rater_id
            WHERE r.target_id=%s AND r.target_role=%s
              AND r.comment IS NOT NULL AND r.comment <> ''
            ORDER BY r.created_at DESC
            LIMIT 10
            """,
            (target_id, as_target_role),
        )
        comments = await cur.fetchall()

    return {
        "success": True,
        "data": {
            "target_id": target_id,
            "target_role": as_target_role,
            "count": stats["count"] if stats else 0,
            "avg_overall": float(stats["avg_overall"]) if stats and stats["avg_overall"] is not None else None,
            "avg_dim1": float(stats["avg_dim1"]) if stats and stats["avg_dim1"] is not None else None,
            "avg_dim2": float(stats["avg_dim2"]) if stats and stats["avg_dim2"] is not None else None,
            "avg_dim3": float(stats["avg_dim3"]) if stats and stats["avg_dim3"] is not None else None,
            "recent_comments": [
                {
                    "from_name": c["from_name"],
                    "comment": c["comment"],
                    "created_at": c["created_at"],
                }
                for c in (comments or [])
            ],
        }
    }
@router.get("/user/{uid}/ratings")
async def user_ratings(
    uid: int,
    mode: str = Query("received", pattern="^(received|given)$"),
    target_role: Optional[str] = Query(None, pattern="^(client|contractor)$"),
    conn=Depends(getDB),
):
    """
    mode:
      - received: 別人評我（target_id = uid）
      - given:    我評別人（rater_id = uid）
    target_role:
      - 可選：只看被評身分 client/contractor
    """
    async with conn.cursor(row_factory=dict_row) as cur:
        if mode == "received":
            sql = """
            SELECT
              r.id,
              r.job_id,
              j.title AS job_title,
              r.rater_id,
              u_from.username AS from_name,
              r.target_id,
              u_to.username AS to_name,
              r.target_role,
              r.dim1, r.dim2, r.dim3,
              r.comment,
              r.created_at
            FROM user_ratings r
            JOIN users u_from ON u_from.id = r.rater_id
            JOIN users u_to   ON u_to.id   = r.target_id
            LEFT JOIN jobs j  ON j.id      = r.job_id
            WHERE r.target_id = %s
            """
            params = [uid]
            if target_role:
                sql += " AND r.target_role = %s"
                params.append(target_role)
            sql += " ORDER BY r.created_at DESC LIMIT 200"
            await cur.execute(sql, tuple(params))
        else:
            sql = """
            SELECT
              r.id,
              r.job_id,
              j.title AS job_title,
              r.rater_id,
              u_from.username AS from_name,
              r.target_id,
              u_to.username AS to_name,
              r.target_role,
              r.dim1, r.dim2, r.dim3,
              r.comment,
              r.created_at
            FROM user_ratings r
            JOIN users u_from ON u_from.id = r.rater_id
            JOIN users u_to   ON u_to.id   = r.target_id
            LEFT JOIN jobs j  ON j.id      = r.job_id
            WHERE r.rater_id = %s
            """
            params = [uid]
            if target_role:
                sql += " AND r.target_role = %s"
                params.append(target_role)
            sql += " ORDER BY r.created_at DESC LIMIT 200"
            await cur.execute(sql, tuple(params))

        rows = await cur.fetchall()

    return {"success": True, "items": rows}

# ============================================================
# ✅ 新增：個人頁面用（同時拿到「我被評」+「我評別人」所有明細）
# GET /me/ratings
# ============================================================
@router.get("/me/ratings")
async def my_ratings(user=Depends(session_user), conn=Depends(getDB)):
    uid = user["user_id"]

    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            """
            SELECT
              ur.job_id,
              j.title AS job_title,

              ur.rater_id,
              ru.username AS rater_name,

              ur.target_id,
              tu.username AS target_name,

              ur.target_role,
              ur.dim1, ur.dim2, ur.dim3,
              ur.comment,
              ur.created_at
            FROM user_ratings ur
            LEFT JOIN jobs j ON j.id = ur.job_id
            JOIN users ru ON ru.id = ur.rater_id
            JOIN users tu ON tu.id = ur.target_id
            WHERE ur.rater_id = %s OR ur.target_id = %s
            ORDER BY ur.created_at DESC
            """,
            (uid, uid),
        )
        rows = await cur.fetchall()

    # 分類：你要前端好做 Tabs
    received_as_client = []
    received_as_contractor = []
    given_to_client = []
    given_to_contractor = []

    for r in rows:
        is_received = (r["target_id"] == uid)
        is_given = (r["rater_id"] == uid)

        if is_received:
            if r["target_role"] == "client":
                received_as_client.append(r)
            else:
                received_as_contractor.append(r)

        if is_given:
            if r["target_role"] == "client":
                given_to_client.append(r)
            else:
                given_to_contractor.append(r)

    return {
        "success": True,
        "data": {
            "me": user,
            "received_as_client": received_as_client,
            "received_as_contractor": received_as_contractor,
            "given_to_client": given_to_client,
            "given_to_contractor": given_to_contractor,
        }
    }
