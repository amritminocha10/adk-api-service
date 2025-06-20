from fastapi import UploadFile, File, Form
from fastapi.responses import JSONResponse  
from fastapi import Request
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from contextlib import asynccontextmanager
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from autoclaim_agents import autoclaim_agent
from tools import decode_vin_no
import base64
import uuid
import requests


APP_NAME = "auto_claim_360"
USER_ID = "user_001"
SESSION_ID = str(uuid.uuid4())

session_service = InMemorySessionService()

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("🟢 Lifespan started....")
    await session_service.create_session(app_name=APP_NAME, user_id=USER_ID, session_id=SESSION_ID)
    app.state.runner = Runner(agent=autoclaim_agent, app_name=APP_NAME, session_service=session_service)
    yield
    print("🔴 Lifespan ended")

app = FastAPI(lifespan=lifespan)

class VinRequest(BaseModel):
    vin: str

@app.post("/vin-lookup")
async def vin_lookup(body: VinRequest):
    try:
        return decode_vin_no(body.vin)
    except requests.HTTPError as e:
        raise HTTPException(status_code=502, detail="VIN API error")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/process-claim")
async def process_claim( 
    request: Request,
    vehicle_image: UploadFile = File(...),
    vin: str = Form(...),
    customer_prompt: str = Form(...) 
):
    print(f"Processing claim for VIN::: {vin}")
    image_bytes = await vehicle_image.read()
    encoded_image = base64.b64encode(image_bytes).decode("utf-8")

    parts = [
        types.Part(text=customer_prompt),
        types.Part(text=f"VIN: {vin}"),
        types.Part(inline_data=types.Blob(mime_type=vehicle_image.content_type, data=image_bytes))
    ]

    content = types.Content(role="user", parts=parts)

    runner = request.app.state.runner
    events = runner.run(user_id=USER_ID, session_id=SESSION_ID, new_message=content)
    
    final_response = None
    for event in events:
        print(f"Event received: {event}")
        if event.is_final_response():
            print(f"Final response from agent: {event.content.parts[0].text}")
            
            if event.author == "ReportAgent":
                final_response = event.content.parts[0].text
    if final_response:
        print(f"Final report generated: {final_response}")
        return JSONResponse(content={"final_report": final_response}, status_code=200)
    else:
        print("No final response from agent")
        return JSONResponse(content={"error": "No final response from agent"}, status_code=500)
