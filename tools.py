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
# import fitz # PyMuPDF for PDF processing
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
def decode_vin_no(vin: str) -> dict:
    print(f"Decoding VIN: {vin}")
    # 1) Call the free NHTSA VPIC VIN‐decode endpoint
    url = f"https://vpic.nhtsa.dot.gov/api/vehicles/decodevinvalues/{vin}?format=json"
    resp = requests.get(url,verify=False)
    resp.raise_for_status()
    data = resp.json()
    print(f"Response from NHTSA: {data}")
    # 2) Grab the first result (it always returns a list of length 1 for this endpoint)
    result = data.get("Results", [{}])[0]
    print(f"Decoded result: {result}")
    if not result:
        return "error: No results found for the provided VIN."
    # 3) Extract the fields you care about
    make  = result.get("Make", "").title()
    model = result.get("Model", "").title()
    year  = result.get("ModelYear", "")
    print(f"Extracted Make: {make}, Model: {model}, Year: {year}")
    # 4) Derving a warranty flag, we can change the no of years of warranty
    warranty = "Unknown"
    try:
        current_year = datetime.now().year
        year_int = int(year)
        warranty = "Yes" if current_year - year_int <= 5 else "No"
    except (ValueError, TypeError):
        pass

    # 5) Return the same shape as before
    return f"Make: {make}, Model: {model}, Year: {year}, Warranty: {warranty}"
    

