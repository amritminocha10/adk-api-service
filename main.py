from fastapi import FastAPI, UploadFile, File, Form, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from google.genai.types import Part, Blob
from autoclaim_agents import autoclaim_agent
from util import upload_image_to_gcs, insert_claim_to_db,decode_vin_number
import base64
import uuid
import os
import asyncio
import json
from typing import List
from fastapi.staticfiles import StaticFiles
import pathlib
import pymssql


APP_NAME = "auto_claim_360"
USER_ID = "user_001"
SESSION_ID = str(uuid.uuid4())
session_service = InMemorySessionService()


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Lifespan started....")
    await session_service.create_session(app_name=APP_NAME, user_id=USER_ID, session_id=SESSION_ID)
    app.state.runner = Runner(agent=autoclaim_agent, app_name=APP_NAME, session_service=session_service)
    yield
    print("Lifespan ended")


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="build/static"), name="static")


def serialize_part(part):
    if part.text:
        return {"text": part.text}
    elif part.inline_data:
        return {
            "inline_data": {
                "mime_type": part.inline_data.mime_type,
                "data": base64.b64encode(part.inline_data.data).decode("utf-8")
            }
        }
    else:
        return {}

def deserialize_part(part_dict):
    if "text" in part_dict:
        return Part(text=part_dict["text"])
    elif "inline_data" in part_dict:
        return Part(inline_data=Blob(
            mime_type=part_dict["inline_data"]["mime_type"],
            data=base64.b64decode(part_dict["inline_data"]["data"])
        ))
    return None


@app.post("/upload-claim")
async def process_claim(
    vehicle_image: List[UploadFile] = File(...),
    vin: str = Form(...),
    customer_prompt: str = Form(...)
):
    print(f"Processing  claim for VIN::: {vin}")

    if not vin  or len(vin) != 17:
        return JSONResponse(status_code=400, content={"error": "Invalid VIN length"})
    
    try:
      vin_check = decode_vin_number(vin)
      print(f"VIN decode result: {vin_check}")
      if isinstance(vin_check, str) and vin_check.startswith("error"):
        raise ValueError()
    except Exception as e:
      print(f"VIN decode failed for {vin}: {e}")
      return JSONResponse(status_code=400, content={f"error": "Invalid VIN — decode failed : {e}"})
    
    encoded_images = []
    uploaded_urls = []
    parts = [
        types.Part(text=customer_prompt),
        types.Part(text=f"VIN: {vin}")
    ]

    for img in vehicle_image:
        image_bytes = await img.read()
        encoded_image = base64.b64encode(image_bytes).decode("utf-8")
        encoded_images.append(encoded_image)

        parts.append(types.Part(inline_data=types.Blob(
            mime_type=img.content_type,
            data=image_bytes
        )))

        image_filename = f"{vin}_{uuid.uuid4().hex}{os.path.splitext(img.filename)[1]}"
        image_url = upload_image_to_gcs(image_bytes, image_filename, img.content_type)
        uploaded_urls.append(image_url)

    # Insert claim into DB
    db_result = insert_claim_to_db(vin=vin, prompt=customer_prompt, image_url_list=uploaded_urls)
    if not db_result["success"]:
        return JSONResponse(content={"error": db_result["message"]}, status_code=db_result["status_code"])

    # Generate session + content
    content = types.Content(role="user", parts=parts)
    session_id = str(uuid.uuid4())
    await session_service.create_session(app_name=APP_NAME, user_id=USER_ID, session_id=session_id)

    # Serialize parts and save to DB
    try:
        parts_dict = [serialize_part(part) for part in parts]
        content_json = json.dumps(parts_dict)

        conn = pymssql.connect(
            server=os.getenv("SQLSERVER_HOST"),
            user=os.getenv("SQLSERVER_USER"),
            password=os.getenv("SQLSERVER_PASSWORD"),
            database=os.getenv("SQLSERVER_DATABASE")
        )
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE Customer SET SessionId = %s, ContentJson = %s WHERE VIN = %s",
            (session_id, content_json, vin)
        )
        conn.commit()
        cursor.close()
        conn.close()
        print("Session ID and ContentJson saved to DB.")
    except Exception as e:
        print("Error saving session to DB:", e)
        return JSONResponse(status_code=500, content={"error": "Failed to save session data"})

    return {"session_id": session_id}


async def event_generator(session_id: str, runner, content):
    try:
        for event in runner.run(user_id=USER_ID, session_id=session_id, new_message=content):
            author = getattr(event, "author", "unknown")

            if event.is_final_response():
                text = event.content.parts[0].text if event.content and event.content.parts else ""
                yield json.dumps({
                    "event": "final",
                    "data": {
                        "author": author,
                        "message": text,
                        "done": True
                    }
                }) + "\n"
            else:
                yield json.dumps({
                    "event": "update",
                    "data": {
                        "author": author,
                        "message": str(event),
                        "done": False
                    }
                }) + "\n"
            await asyncio.sleep(0.01)
    except Exception as e:
        yield json.dumps({"error": str(e)}) + "\n"


@app.get("/stream-claim/{session_id}")
async def stream_claim(session_id: str, request: Request):
    try:
        conn = pymssql.connect(
            server=os.getenv("SQLSERVER_HOST"),
            user=os.getenv("SQLSERVER_USER"),
            password=os.getenv("SQLSERVER_PASSWORD"),
            database=os.getenv("SQLSERVER_DATABASE")
        )
        cursor = conn.cursor(as_dict=True)
        cursor.execute("SELECT ContentJson FROM Customer WHERE SessionId = %s", (session_id,))
        row = cursor.fetchone()
        cursor.close()
        conn.close()

        if not row or not row.get("ContentJson"):
            return JSONResponse(status_code=404, content={"error": "Invalid session ID"})


        parts_data = json.loads(row["ContentJson"])
        parts = [deserialize_part(p) for p in parts_data if deserialize_part(p)]
        content = types.Content(role="user", parts=parts)

        runner = request.app.state.runner
        return StreamingResponse(event_generator(session_id, runner, content), media_type="application/x-ndjson")

    except Exception as e:
        print("Error retrieving session data:", e)
        return JSONResponse(status_code=500, content={"error": "Failed to retrieve session data"})


@app.get("/pingTest")
async def ping_test():
    return {"message": "Ping Test Successful!"}


@app.get("/.well-known/appspecific/com.chrome.devtools.json")
async def chrome_devtools_handler():
    return {"status": "ok"}


@app.get("/")
async def read_index():
    return FileResponse("build/index.html")


@app.get("/{full_path:path}")
async def serve_react_app(full_path: str):
    file_path = pathlib.Path("build") / full_path
    if file_path.exists() and file_path.is_file():
        return FileResponse(file_path)
    return FileResponse("build/index.html")
