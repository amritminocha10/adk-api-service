from fastapi import FastAPI, UploadFile, File, Form, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from autoclaim_agents import autoclaim_agent
from util import upload_image_to_gcs, insert_claim_to_db
import base64
import uuid
import os
import asyncio
import json
from typing import List
from fastapi.staticfiles import StaticFiles


APP_NAME = "auto_claim_360"
USER_ID = "user_001"
SESSION_ID = str(uuid.uuid4())
session_service = InMemorySessionService()
stored_claims = {}  # Store session_id -> content for streaming

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("🟢 Lifespan started....")
    await session_service.create_session(app_name=APP_NAME, user_id=USER_ID, session_id=SESSION_ID)
    app.state.runner = Runner(agent=autoclaim_agent, app_name=APP_NAME, session_service=session_service)
    yield
    print("🔴 Lifespan ended")

app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="build/static"), name="static")

@app.post("/upload-claim")
async def process_claim( 
    request: Request,
    vehicle_image: List[UploadFile] = File(...),
    vin: str = Form(...),
    customer_prompt: str = Form(...) 
):
    print(f"Processing claim for VIN::: {vin}")

    encoded_images = []
    uploaded_urls = []
    parts = [
        types.Part(text=customer_prompt),
        types.Part(text=f"VIN: {vin}")
    ]

    for vehicle_image in vehicle_image:
        image_bytes = await vehicle_image.read()
        encoded_image = base64.b64encode(image_bytes).decode("utf-8")
        encoded_images.append(encoded_image)

        parts.append(types.Part(inline_data=types.Blob(
            mime_type=vehicle_image.content_type,
            data=image_bytes
        )))

        image_filename = f"{vin}_{uuid.uuid4().hex}{os.path.splitext(vehicle_image.filename)[1]}"
        image_url = upload_image_to_gcs(image_bytes, image_filename, vehicle_image.content_type)
        uploaded_urls.append(image_url)

    # Insert into DB with all image URLs
    db_result = insert_claim_to_db(vin=vin, prompt=customer_prompt, image_url_list=uploaded_urls)
    if not db_result["success"]:
        return JSONResponse(content={"error": db_result["message"]}, status_code=db_result["status_code"])

    # Construct LLM content
    content = types.Content(role="user", parts=parts)
    session_id = str(uuid.uuid4())
    await session_service.create_session(app_name=APP_NAME, user_id=USER_ID, session_id=session_id)
    stored_claims[session_id] = content

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
    if session_id not in stored_claims:
        return JSONResponse(status_code=404, content={"error": "Invalid session ID"})

    content = stored_claims[session_id]
    runner = request.app.state.runner
    return StreamingResponse(event_generator(session_id, runner, content), media_type="application/x-ndjson")


@app.get("/")
async def read_index():
    return FileResponse("build/index.html")