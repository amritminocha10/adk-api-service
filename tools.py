import requests
from google.adk import tools
from datetime import datetime

@tools.FunctionTool
def decode_vin(vin: str) -> dict:
    
    
    print(f"Decoding VIN: {vin}")
    return f"Make: Honda, Model: Civic, Year: 2022, Warranty: Yes"

@tools.FunctionTool
def search_knowledge_base(query: str) -> dict:
    
    
    print(f"Searching knowledge base with query: {query}")
    return f"Matched Document: Warranty covers bumper damage under clause 5.2, Confidence: 0.87"


def decode_vin_no(vin: str) -> dict:
    print(f"Decoding VIN: {vin}")
    # 1) Call the free NHTSA VPIC VIN‐decode endpoint
    url = f"https://vpic.nhtsa.dot.gov/api/vehicles/decodevinvalues/{vin}?format=json"
    resp = requests.get(url)
    resp.raise_for_status()
    data = resp.json()

    # 2) Grab the first result (it always returns a list of length 1 for this endpoint)
    result = data.get("Results", [{}])[0]

    # 3) Extract the fields you care about
    make  = result.get("Make", "").title()
    model = result.get("Model", "").title()
    year  = result.get("ModelYear", "")

    # 4) Derving a warranty flag, we can change the no of years of warranty
    warranty = "Unknown"
    try:
        current_year = datetime.now().year
        year_int = int(year)
        warranty = "Yes" if current_year - year_int <= 5 else "No"
    except (ValueError, TypeError):
        pass

    # 5) Return the same shape as before
    return {
        "Make": make,
        "Model": model,
        "Year": year,
        "Warranty": warranty
    }
