import json

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, EmailStr

from .auth import create_token, current_user, hash_password, verify_password
from .comparator import compare_tables, read_table
from .database import connect, init_db
from .reports import make_docx, make_pdf, make_xlsx

app = FastAPI(title="SheetWise API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://192.168.1.5:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup():
    init_db()


class RegisterBody(BaseModel):
    name: str
    email: EmailStr
    password: str


class LoginBody(BaseModel):
    email: EmailStr
    password: str


class ProfileBody(BaseModel):
    name: str


@app.get("/")
def root():
    return {"name": "SheetWise API", "status": "ok", "docs": "/docs"}


@app.post("/api/auth/register")
def register(body: RegisterBody):
    if len(body.password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters.")
    if not body.name.strip():
        raise HTTPException(400, "Name is required.")
    try:
        with connect() as c:
            cur = c.execute(
                "INSERT INTO users(name,email,password_hash) VALUES(?,?,?)",
                (body.name.strip(), body.email.lower(), hash_password(body.password)),
            )
            uid = cur.lastrowid
    except Exception as e:
        if "UNIQUE" in str(e).upper():
            raise HTTPException(409, "An account with this email already exists.")
        raise HTTPException(500, "Could not create account.")
    return {
        "token": create_token(uid, body.email.lower()),
        "user": {"id": uid, "name": body.name.strip(), "email": body.email.lower()},
    }


@app.post("/api/auth/login")
def login(body: LoginBody):
    with connect() as c:
        row = c.execute(
            "SELECT id,name,email,password_hash FROM users WHERE email=?",
            (body.email.lower(),),
        ).fetchone()
    if not row or not verify_password(body.password, row["password_hash"]):
        raise HTTPException(401, "Incorrect email or password.")
    return {
        "token": create_token(row["id"], row["email"]),
        "user": {"id": row["id"], "name": row["name"], "email": row["email"]},
    }


@app.get("/api/auth/me")
def me(user=Depends(current_user)):
    return {"user": user}


@app.patch("/api/auth/profile")
def update_profile(body: ProfileBody, user=Depends(current_user)):
    if not body.name.strip():
        raise HTTPException(400, "Name cannot be empty.")
    with connect() as c:
        c.execute("UPDATE users SET name=? WHERE id=?", (body.name.strip(), user["id"]))
    user["name"] = body.name.strip()
    return {"user": user}


@app.post("/api/compare")
async def compare(
    reference_file: UploadFile = File(...),
    comparison_file: UploadFile = File(...),
    matching_key: str | None = Form(None),
    user=Depends(current_user),
):
    try:
        ref = read_table(
            reference_file.filename or "reference.xlsx", await reference_file.read()
        )
        new = read_table(
            comparison_file.filename or "comparison.xlsx", await comparison_file.read()
        )
        key = matching_key.strip() if matching_key and matching_key.strip() else None
        summary, issues = compare_tables(ref, new, key)
        with connect() as c:
            cur = c.execute(
                "INSERT INTO comparisons(user_id,reference_name,comparison_name,matching_key,summary_json,issues_json) VALUES(?,?,?,?,?,?)",
                (
                    user["id"],
                    reference_file.filename or "reference",
                    comparison_file.filename or "comparison",
                    key,
                    json.dumps(summary),
                    json.dumps(issues, ensure_ascii=False),
                ),
            )
            cid = cur.lastrowid
        return {
            "id": cid,
            "reference_name": reference_file.filename,
            "comparison_name": comparison_file.filename,
            "summary": summary,
            "issues": issues,
        }
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(
            400,
            f"Could not compare files. Check that both are valid spreadsheets. ({type(e).__name__})",
        )


@app.get("/api/history")
def history(user=Depends(current_user)):
    with connect() as c:
        rows = c.execute(
            "SELECT id,reference_name,comparison_name,matching_key,summary_json,created_at FROM comparisons WHERE user_id=? ORDER BY id DESC LIMIT 100",
            (user["id"],),
        ).fetchall()
    return [
        {
            "id": r["id"],
            "reference_name": r["reference_name"],
            "comparison_name": r["comparison_name"],
            "matching_key": r["matching_key"],
            "summary": json.loads(r["summary_json"]),
            "created_at": r["created_at"],
        }
        for r in rows
    ]


@app.get("/api/history/{cid}")
def history_detail(cid: int, user=Depends(current_user)):
    with connect() as c:
        r = c.execute(
            "SELECT * FROM comparisons WHERE id=? AND user_id=?", (cid, user["id"])
        ).fetchone()
    if not r:
        raise HTTPException(404, "Comparison not found.")
    return {
        "id": r["id"],
        "reference_name": r["reference_name"],
        "comparison_name": r["comparison_name"],
        "matching_key": r["matching_key"],
        "summary": json.loads(r["summary_json"]),
        "issues": json.loads(r["issues_json"]),
        "created_at": r["created_at"],
    }


def report_response(fmt, summary, issues, cid):
    fmt = fmt.lower()
    if fmt == "xlsx":
        data, media, ext = (
            make_xlsx(summary, issues),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "xlsx",
        )
    elif fmt == "pdf":
        data, media, ext = make_pdf(summary, issues), "application/pdf", "pdf"
    elif fmt == "docx":
        data, media, ext = (
            make_docx(summary, issues),
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "docx",
        )
    else:
        raise HTTPException(400, "Format must be xlsx, pdf, or docx.")
    return StreamingResponse(
        iter([data]),
        media_type=media,
        headers={
            "Content-Disposition": f'attachment; filename="sheetwise-report-{cid}.{ext}"'
        },
    )


@app.get("/api/history/{cid}/report/{fmt}")
def history_report(cid: int, fmt: str, user=Depends(current_user)):
    with connect() as c:
        r = c.execute(
            "SELECT * FROM comparisons WHERE id=? AND user_id=?", (cid, user["id"])
        ).fetchone()
    if not r:
        raise HTTPException(404, "Comparison not found.")
    return report_response(
        fmt, json.loads(r["summary_json"]), json.loads(r["issues_json"]), cid
    )
