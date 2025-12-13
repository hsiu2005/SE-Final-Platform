#處理檔案上傳的範例範例，將route定義放在目錄下的個別檔案中
#To handle file upload, pip install python-multipart first
from fastapi import APIRouter,File, UploadFile, Form,Depends
from fastapi.responses import HTMLResponse,RedirectResponse

import os
import re
import model.posts as posts
from model.db import getDB

#使用APIRouter來定義route, 再從main.py中引入
router = APIRouter()

#簡易版，直接讀檔存檔
@router.post("/upload")
async def upload_file(
	uploadedFile: UploadFile = File(...), 
	msg:str=Form(...), #this is the postID
	conn=Depends(getDB) ):
	
	contents = await uploadedFile.read()
	
	#危險!!! 若要使用原檔名，應該先檢查檔名是否安全
	#參考下面的safeFilename()
	with open(f"www/uploads/{uploadedFile.filename}", "wb") as f:
		f.write(contents)
	print(msg)
	await posts.setUploadFile(conn, msg,uploadedFile.filename)
	return RedirectResponse(url=f"/read/{msg}", status_code=302)


def safeFilename(filename:str):
	ALLOWED_EXTENSIONS = {".txt", ".pdf", ".png", ".jpg", ".jpeg"}
	name, ext = os.path.splitext(filename)

	if ext.lower() not in ALLOWED_EXTENSIONS:
		return False
	#replace illegal chars with _
	safe = re.sub(r'[<>:"/\\|?*\x00-\x1F]', '_', filename)
	safe = re.sub(r'_+', '_', safe)
	# Trim to 255 characters (common filesystem limit)
	return safe[:255]

#進階版，分段讀取，並限制檔案大小, 參數中的fileField須跟form中的欄位名稱相同
@router.post("/upload/chunked")
async def chunk_upload_file(fileField: UploadFile = File(...)):
	MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
	CHUNK_SIZE = 1024 * 1024  # 1MB per chunk
	safeFn = safeFilename(fileField.filename)
	upload_path = f"uploads/{safeFn}"
	total_size = 0

	try:
		with open(upload_path, "wb") as buffer:
			while True:
				chunk = await fileField.read(CHUNK_SIZE)
				if not chunk:
					break
				total_size += len(chunk)
				if total_size > MAX_FILE_SIZE:
					buffer.close()
					os.remove(upload_path)
					raise HTTPException(status_code=413, detail="File too large")
				buffer.write(chunk)
	except Exception as e:
		raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")

	return {"filename": safeFn, "size_bytes": total_size}
