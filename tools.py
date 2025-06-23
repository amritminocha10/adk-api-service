import requests
from datetime import datetime
from dotenv import load_dotenv
import os
load_dotenv()
from google.adk import tools 
import vertexai
from vertexai.generative_models import GenerativeModel
import PyPDF2
from google.cloud import storage
import io
import re
from util import sanitize_text

PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT")  
LOCATION = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
GCP_BUCKET = os.getenv("GCP_BUCKET_NAME")
GCP_BUCKET_FOLDER = os.getenv("GCP_BUCKET_FOLDER", "knowledge-documents")

vertexai.init(project=PROJECT_ID, location=LOCATION)

@tools.FunctionTool
def decode_vin(vin: str) -> dict:
    print(f"Decoding VIN: {vin}")
    return f"Make: Honda, Model: Civic, Year: 2022, Warranty: Yes" 

@tools.FunctionTool 
def search_knowledge_base(query: str) -> dict:
    print(f"Searching knowledge base with query: {query}")
    try:
        # Setup GCS
        client = storage.Client()
        bucket_name = GCP_BUCKET
        prefix = GCP_BUCKET_FOLDER.rstrip('/') + '/'
        bucket = client.bucket(bucket_name)

        
        
        # Get list of PDF files
        blobs = list(bucket.list_blobs(prefix=prefix))
        pdf_blobs = [blob for blob in blobs if blob.name.lower().endswith(".pdf")]

        if not pdf_blobs:
            return {"error": f"No PDF documents found in {prefix}"}

        print(f"PDF blobs found: {len(pdf_blobs)}")
        combined_text = ""

        for blob in pdf_blobs:
            try:
                print(f"Reading PDF: {blob.name}")
                pdf_bytes = blob.download_as_bytes()
                pdf_stream = io.BytesIO(pdf_bytes)

                reader = PyPDF2.PdfReader(pdf_stream)
                text = ""
                for page in reader.pages:
                    extracted = page.extract_text()
                    if extracted:
                        # Sanitize extracted page text
                        text += sanitize_text(extracted)

                # Also sanitize blob name just in case
                safe_blob_name = sanitize_text(blob.name)
                combined_text += f"\n\n---\nDocument: {safe_blob_name}\n{text.strip()}\n"

            except Exception as doc_err:
                print(f"Error reading PDF {blob.name}: {doc_err}")

        if not combined_text.strip():
            return {"error": "Extracted text is empty from all PDFs."}

        # Prepare prompt for Gemini
        model = GenerativeModel("gemini-2.5-flash-preview-04-17")
        prompt = (
            f"You are a helpful assistant. Use the following context to answer the question.\n\n"
            f"Context:\n{combined_text}\n\n"
            f"Question: {query}"
        )

        response = model.generate_content(prompt)
        answer = response.text.strip()
        print(f"Final answer: {answer}")
        return {"answer": answer}

    except Exception as e:
        print(f"Error searching knowledge base: {str(e)}")
        return {"error": str(e)}

@tools.FunctionTool
def decode_vin_no(vin: str) -> str:
    print(f"[decode_vin_no] Decoding VIN: {vin}")
    
    url = f"https://vpic.nhtsa.dot.gov/api/vehicles/decodevinvalues/{vin}?format=json"
    
    try:
        resp = requests.get(url, verify=False, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        print(f"[decode_vin_no] Response from NHTSA: {data}")
    except requests.RequestException as e:
        print(f"[decode_vin_no] HTTP request failed: {e}")
        return "error: Failed to fetch VIN info from NHTSA"
    except ValueError as e:
        print(f"[decode_vin_no] JSON decoding failed: {e}")
        return "error: Invalid JSON response from NHTSA"

    try:
        result = data.get("Results", [{}])[0]
        if not result:
            print("[decode_vin_no] Empty result object in response")
            return "error: No results found for the provided VIN."
    except Exception as e:
        print(f"[decode_vin_no] Error extracting result: {e}")
        return "error: Malformed response structure"

    try:
        make  = result.get("Make", "").title()
        model = result.get("Model", "").title()
        year  = result.get("ModelYear", "")
        print(f"[decode_vin_no] Extracted Make: {make}, Model: {model}, Year: {year}")

        # Estimate warranty
        warranty = "Unknown"
        current_year = datetime.now().year
        year_int = int(year)
        warranty = "Yes" if current_year - year_int <= 3 else "No"

        print(f"[decode_vin_no] Returning decoded VIN info: Make: {make}, Model: {model}, Year: {year}, Warranty: {warranty}")
        return f"Make: {make}, Model: {model}, Year: {year}, Warranty: {warranty}"

    except Exception as e:
        print(f"[decode_vin_no] Error processing result fields: {e}")
        return "error: Could not extract vehicle info"