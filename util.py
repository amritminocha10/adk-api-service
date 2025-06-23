import os
from google.cloud import storage
from dotenv import load_dotenv
import pymssql
import json
from typing import List
load_dotenv()
import re
from google.genai.types import Part, Blob
import base64
import requests
from datetime import datetime



def load_instruction_from_file(
    filename: str, default_instruction: str = "Default instruction."
) -> str:
    """Reads instruction text from a file relative to this script."""
    instruction = default_instruction
    try:
        # Construct path relative to the current script file (__file__)
        filepath = os.path.join(os.path.dirname(__file__), filename)
        with open(filepath, "r", encoding="utf-8") as f:
            instruction = f.read()
        print(f"Successfully loaded instruction from {filename}")
    except FileNotFoundError:
        print(f"WARNING: Instruction file not found: {filepath}. Using default.")
    except Exception as e:
        print(f"ERROR loading instruction file {filepath}: {e}. Using default.")
    return instruction

PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT")  
GCS_BUCKET_NAME = os.getenv("GCP_BUCKET_NAME")
GCS_IMAGE_FOLDER = os.getenv("GCS_IMAGE_FOLDER")

def upload_image_to_gcs(image_bytes: bytes, filename: str, content_type: str) -> str:
    client = storage.Client()
    bucket = client.bucket(GCS_BUCKET_NAME)
    blob_path = f"{GCS_IMAGE_FOLDER.rstrip('/')}/{filename}"
    blob = bucket.blob(blob_path)
    blob.upload_from_string(image_bytes, content_type=content_type)

    print(f"Image uploaded to GCS: {blob_path}") 
    return filename


def insert_claim_to_db(vin: str, prompt: str, image_url_list: List[str]):
    try:
        conn = pymssql.connect(
            server=os.getenv("SQLSERVER_HOST"),
            user=os.getenv("SQLSERVER_USER"),
            password=os.getenv("SQLSERVER_PASSWORD"),
            database=os.getenv("SQLSERVER_DATABASE")
        )
        cursor = conn.cursor()

        image_urls_json = json.dumps(image_url_list)  # Store as JSON string

        cursor.execute(
            "INSERT INTO Customer (VIN, Prompt, vehicleImageUrl) VALUES (%s, %s, %s)",
            (vin, prompt, image_urls_json)
        )

        conn.commit()
        cursor.close()
        conn.close()
        print("Claim data inserted into SQL Server using pymssql")
        return {
            "success": True,
            "message": "Claim data inserted successfully",
            "status_code": 200
        }
    
    except pymssql.DatabaseError as e:
        print("Database error:", e)
        return {
            "success": False,
            "message": f"Database error: {str(e)}",
            "status_code": 500
        }
   
   

def sanitize_text(text):
    """Remove characters that can't be encoded in UTF-8."""
    return text.encode("utf-8", "ignore").decode("utf-8", "ignore")     
        
    
    
    
    
def decode_vin_number(vin: str) -> str:
    print(f"[decode_vin_number] Decoding VIN: {vin}")

    url = f"https://vpic.nhtsa.dot.gov/api/vehicles/decodevinvalues/{vin}?format=json"
    
    try:
        resp = requests.get(url, verify=False, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        print(f"[decode_vin_number] Response from NHTSA: {data}")
    except requests.RequestException as e:
        print(f"[decode_vin_number] HTTP request failed: {e}")
        return "error: Failed to fetch VIN info from NHTSA"
    except ValueError as e:
        print(f"[decode_vin_number] JSON decoding failed: {e}")
        return "error: Invalid JSON response from NHTSA"

    try:
        result = data.get("Results", [{}])[0]
        if not result:
            print("[decode_vin_number] Empty result object in response")
            return "error: No results found for the provided VIN."
    except Exception as e:
        print(f"[decode_vin_number] Error extracting result: {e}")
        return "error: Malformed response structure"

    try:
        make  = result.get("Make", "").title()
        model = result.get("Model", "").title()
        year  = result.get("ModelYear", "")
        print(f"[decode_vin_number] Extracted Make: {make}, Model: {model}, Year: {year}")

        # Estimate warranty
        warranty = "Unknown"
        current_year = datetime.now().year
        year_int = int(year)
        warranty = "Yes" if current_year - year_int <= 3 else "No"

        print(f"[decode_vin_number] Returning decoded VIN info: Make: {make}, Model: {model}, Year: {year}, Warranty: {warranty}")
        return f"Make: {make}, Model: {model}, Year: {year}, Warranty: {warranty}"

    except Exception as e:
        print(f"[decode_vin_number] Error processing result fields: {e}")
        return "error: Could not extract vehicle info"


# from fastapi import Query
# from datetime import timedelta

# @app.get("/get-image-url")
# async def get_signed_image_url(blob_path: str = Query(..., description="Path like 'claims/image.jpg'")):
#     try:
#         bucket = storage.Client().bucket(GCS_BUCKET_NAME)
#         blob = bucket.blob(blob_path)

#         # Signed URL valid for 1 hour
#         url = blob.generate_signed_url(expiration=timedelta(hours=1), method="GET")
#         return {"url": url}

#     except Exception as e:
#         return JSONResponse(status_code=500, content={"error": str(e)})
