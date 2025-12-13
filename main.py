# main.py
from fastapi import FastAPI, Depends, Request, Form
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse,RedirectResponse

from fastapi.templating import Jinja2Templates
templates = Jinja2Templates(directory="templates")

from routes.upload import router as upload_router
from routes.dbQuery import router as db_router
from model.db import getDB
import model.posts as posts

# Include the router
app = FastAPI()
#prefix will be prepended before the route
app.include_router(upload_router, prefix="/api") 
app.include_router(db_router, prefix="/api")

#use session middleware for session mamagement
from starlette.middleware.sessions import SessionMiddleware
app.add_middleware(
    SessionMiddleware,
    secret_key="your-secret-key",
	max_age=None, #86400,  # 1 day
    same_site="lax",  # Options: 'lax', 'strict', 'none'
    https_only=False,  # Set to True in production with HTTPS,
)

#example of using dependency function for login check
def get_current_user(request: Request):
	user_id = request.session.get("user")
	#for not-login user, user_id will be None
	return user_id

def get_current_role(request: Request):
	return request.session.get("role")
	
#example of using function wrapper to check role
def checkRole(requiredRole:str):
	def checker(request: Request):
		user_role = request.session.get("role")
		if user_role == requiredRole:
			return True
		else:
			raise HTTPException(status_code=401, detail="Not authenticated")
	return checker
	

@app.get("/")
async def root(request:Request,conn=Depends(getDB),user:str=Depends(get_current_user)):
	if user is None:
		return RedirectResponse(url="/loginForm.html", status_code=302)

	myRole = get_current_role(request)
	myList= await posts.getList(conn)
	#return templates.TemplateResponse("home.html", {"request":request})
	return RedirectResponse(url="/homeVue.html", status_code=302)
	#return templates.TemplateResponse("postList.html", {"request":request,"items": myList,"role": myRole})

@app.get("/readList")
async def root(request:Request,conn=Depends(getDB),user:str=Depends(get_current_user)):
	myRole = get_current_role(request)
	myList= await posts.getList(conn)
	return templates.TemplateResponse("postList.html", {"request":request,"items": myList,"role": myRole})


@app.get("/read/{id}")
async def readPost(request:Request, id:int,conn=Depends(getDB)):
	postDetail = await posts.getPost(conn,id)
	return templates.TemplateResponse("postDetail.html", {"request":request,"post": postDetail})

@app.get("/delete/{id}")
#only admin can call this
async def delPost(request:Request, id:int,conn=Depends(getDB),role=Depends(checkRole("admin"))):
	await posts.deletePost(conn,id)
	return RedirectResponse(url="/readList", status_code=302)

@app.post("/addPost")
async def addPost(
	request:Request,
	username: str = Depends(get_current_user),
	content:str=Form(...),
	conn=Depends(getDB)
	):

	postDetail = await posts.addPost(conn,username ,content)
	return RedirectResponse(url="/readList", status_code=302)

@app.post("/addPrice")
async def addPrice(
	request:Request,
	id:int=Form(...),
	username:str=Depends(get_current_user),
	price:int=Form(...),
	conn=Depends(getDB)
	):

	applyDetail = await posts.addPrice(conn,id,username,price)
	return RedirectResponse(url="/readList", status_code=302)

@app.post("/addIssue")
async def addIssue(
	request:Request,
	id:int=Form(...),
	username: str = Depends(get_current_user),
	issuecontent:str=Form(...),
	conn=Depends(getDB)
	):

	postDetail = await posts.addIssue(conn,id,username ,issuecontent)
	return RedirectResponse(url="/readList", status_code=302)

@app.post("/addReply")
async def addReply(
	request:Request,
	id:int=Form(...),
	issue_id:int=Form(...),
	username: str = Depends(get_current_user),
	replycontent:str=Form(...),
	conn=Depends(getDB)
	):

	postDetail = await posts.addReply(conn,id,issue_id,username ,replycontent)
	return RedirectResponse(url="/readList", status_code=302)

@app.get("/logout")
async def logout(request: Request):
	request.session.clear()
	return RedirectResponse(url="/loginForm.html")

@app.post("/login") #receive login data from form post
async def login(
	request: Request,
	username: str = Form(...),
	password: str = Form(...),
	conn=Depends(getDB)
):
	#make your own credential check
	varify=await posts.getUsers(conn, username)
	#the code below is just for demonstration
	if varify and varify["password"]==password:
		request.session["user"] = username
		request.session["role"] = "user"
		return RedirectResponse(url="/", status_code=302)
	else:
		request.session.clear()
		return HTMLResponse("Invalid credentials <a href='/loginForm.html'>login again</a>", status_code=401)
	
@app.post("/register") 
async def register(
	request: Request,
	username: str = Form(...),
	password: str = Form(...),
	conn=Depends(getDB)
):
	await posts.addUsers(conn, username, password)
	return RedirectResponse(url="/loginForm.html", status_code=302)

@app.get("/getPostsJson")
async def getPostsJson(request:Request,conn=Depends(getDB)):
	myList= await posts.getList(conn)
	return myList

@app.get("/readPostJson/{id}")
async def readPostJson(request:Request, id:int,conn=Depends(getDB)):
	postDetail = await posts.getPost(conn,id)
	issues=await posts.getIssue(conn,id)
	postDetail["issues"] = issues
	replies=await posts.getReply(conn,id)
	postDetail["replies"] = replies
	return postDetail

@app.get("/readApplyJson/{id}")
async def readApplyJson(request:Request, id:int,conn=Depends(getDB)):
	applyDetail = await posts.getApply(conn,id)
	return applyDetail

@app.get("/getUser")
async def getUser(username: str = Depends(get_current_user)):
    return {"username": username}

@app.post("/chooseWinner")
async def chooseWinner(
	request:Request,
	id:int=Form(...),
	winner:str=Form(...),
	winnerprice:int=Form(...),    
	currentUser:str=Depends(get_current_user), 
	conn=Depends(getDB)      
	):
	postDetail = await posts.getPost(conn, id) 
	await posts.chooseWinner(conn, id, winner,winnerprice) 
	return RedirectResponse(url="/readList", status_code=302)

@app.get("/getMyPosts")
async def getMyPosts(request:Request,conn=Depends(getDB), user:str=Depends(get_current_user)):
	myRole = get_current_role(request)
	myList= await posts.getMyPosts(conn, user)
	return templates.TemplateResponse("postList.html", {"request":request,"items": myList,"role": myRole})

@app.get("/getMyApplies")
async def getMyApplies(request:Request,conn=Depends(getDB), user:str=Depends(get_current_user)):
	myRole = get_current_role(request)
	myList= await posts.getMyApplies(conn, user)
	return templates.TemplateResponse("applyList.html", {"request":request,"items": myList,"role": myRole})

@app.get("/delCases/{id}")
async def delCases(request:Request, id:int,conn=Depends(getDB)):
	await posts.delCases(conn, id)
	return {"success": True}

@app.get("/changeFinish/{id}")
async def changeFinish(request:Request, id:int,conn=Depends(getDB)):
	await posts.changeFinish(conn, id)
	return {"success": True}

@app.get("/changeIssueFinish/{id}")
async def changeIssueFinish(request:Request, id:int,conn=Depends(getDB)):
	await posts.changeIssueFinish(conn, id)
	return {"success": True}


app.mount("/", StaticFiles(directory="www"))