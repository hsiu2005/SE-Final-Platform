# routes_rating_public.py
from fastapi import APIRouter, Depends, HTTPException, Query
from db import getDB

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

    async with conn.cursor() as cur:
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

        # 最新留言（只拿有 comment 的）
        await cur.execute(
            """
            SELECT comment, created_at
            FROM user_ratings
            WHERE target_id=%s AND target_role=%s
              AND comment IS NOT NULL AND comment <> ''
            ORDER BY created_at DESC
            LIMIT 5
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
                {"comment": c["comment"], "created_at": c["created_at"]}
                for c in (comments or [])
            ],
        }
    }
