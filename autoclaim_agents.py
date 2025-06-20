from google.adk.agents import LlmAgent, LoopAgent
from tools import decode_vin, search_knowledge_base,decode_vin_no
from pydantic import BaseModel
from typing import Optional, Dict,List


class InspectionInput(BaseModel):
    vehicle_images: List[str]  

class InspectionOutput(BaseModel):
    image_authenticity: str  

inspection_agent = LlmAgent(
    name="InspectionAgent",
    model="gemini-2.5-flash-preview-04-17",
    instruction="""
You are an expert forensic image inspector. Analyze the submitted vehicle image (base64-encoded in `vehicle_image`) and determine whether it has been altered or doctored.

**Task:**
- Detect signs of image manipulation or anomalies.
- Provide a boolean result and a brief explanation (~1 sentence).

**Input (InspectionInput):**
- vehicle_image (str): Base64-encoded image of the vehicle.

**Output (InspectionOutput):**
- image_authenticity (str): One of ["authentic", "doctored"], followed by brief justification (e.g., "authentic – no signs of tampering found").
""",
    input_schema=InspectionInput,
    output_schema=InspectionOutput,
    # disallow_transfer_to_parent=True,
    # disallow_transfer_to_peers=True
)


class VisionInput(BaseModel):
    vehicle_images: List[str]
    customer_prompt: str

class VisionOutput(BaseModel):
    damage_type: str
    severity: str
    notes: str
    metadata: Dict

vision_agent = LlmAgent(
    name="VisionAgent",
    model="gemini-2.5-flash-preview-04-17",
    instruction="""
You are a vehicle damage analyst with computer vision capabilities. Analyze the uploaded vehicle images and the accompanying customer prompt to determine the damage details.
Analyze each uploaded vehicle image (base64-encoded)...
For each image, assess damage independently and provide combined summary.

**Task:**
- Identify the type and severity of visible vehicle damage.
- Interpret customer notes to add context.
- Provide structured metadata about the damage.

**Input (VisionInput):**
- vehicle_images (List[str]): Base64-encoded vehicle images.
- customer_prompt (str): Customer's description or concern.

**Output (VisionOutput):**
- damage_type (str): Description of the damage (e.g., "bumper dent").
- severity (str): One of ["minor", "moderate", "severe"].
- notes (str): Any additional inferred context or limitations.
- metadata (dict): Structured data such as affected areas, timestamps, etc.
""",
    input_schema=VisionInput,
    output_schema=VisionOutput,
    # disallow_transfer_to_parent=True,
    # disallow_transfer_to_peers=True
)

class VinInput(BaseModel):
    vin: str

class VinOutput(BaseModel):
    vin: str
    make: Optional[str]
    model: Optional[str]
    year: Optional[str]
    warranty: Optional[str]

vin_agent = LlmAgent(
    name="VinAgent",
    model="gemini-2.5-flash-preview-04-17",
    instruction="""
You are a VIN decoder. Use the `decode_vin` tool to fetch detailed information about the vehicle from the given VIN number.

**Task:**
- Call the `decode_vin` tool using the VIN string.
- Structure the returned information cleanly.
- If VIN is invalid or incomplete, return partial data with a note.

**Input (VinInput):**
- vin (str): Vehicle Identification Number.

**Output (VinOutput):**
- vin (str): Echoed VIN.
- make (str, optional)
- model (str, optional)
- year (str, optional)
- warranty (str, optional): "Yes", "No", or relevant status.
""",
    input_schema=VinInput,
    tools=[decode_vin],
    # output_schema=VinOutput,
)


class KBSearchInput(BaseModel):
    damage_report: str
    vin_info: str

class KBSearchOutput(BaseModel):
    matched_doc: str
    confidence: str

kb_agent = LlmAgent(
    name="KBSearchAgent",
    model="gemini-2.5-flash-preview-04-17",
    instruction="""
You are a warranty knowledge base searcher. Use the `search_knowledge_base` tool to find matching warranty policies based on damage type and VIN information.

**Task:**
- Combine the `damage_report` and `vin_info` into a concise query.
- Pass the query to `search_knowledge_base`.
- Return the most relevant document and confidence score.

**Input (KBSearchInput):**
- damage_report (str): Damage type and severity.
- vin_info (str): Vehicle details including warranty status.

**Output (KBSearchOutput):**
- matched_doc (str): Excerpt from matched policy document.
- confidence (str): Confidence score from the retrieval, 0–1.
""",
    input_schema=KBSearchInput,
    tools=[search_knowledge_base],
    # output_schema=KBSearchOutput
)


class ReportInput(BaseModel):
    image_authenticity: str
    damage_report: str
    vin_info: str
    warranty_context: str

class ReportOutput(BaseModel):
    final_report: str

report_agent = LlmAgent(
    name="ReportAgent",
    model="gemini-2.5-flash-preview-04-17",
    instruction="""
You are a claim report generator. Use inputs from previous agents (inspection, vision analysis, VIN decoding, and KB search) to compile a well-structured claim report.

**Task:**
- Concisely summarize findings from each source.
- Indicate claim eligibility or next steps based on warranty.
- Format in a clear, professional, and readable way.

**Input (ReportInput):**
- image_authenticity (str): Output from InspectionAgent.
- damage_report (str): Output from VisionAgent.
- vin_info (str): Output from VinAgent.
- warranty_context (str): Output from KBSearchAgent.

**Output (ReportOutput):**
- final_report (str): Human-readable structured report (Markdown or formatted text). Include sections: Image Check, Damage Details, Vehicle Info, Warranty Evaluation, Final Assessment.
""",
    input_schema=ReportInput,
    output_schema=ReportOutput,
    # disallow_transfer_to_parent=True,
    # disallow_transfer_to_peers=True
)


autoclaim_agent = LoopAgent(
    name="AutoClaimAgent",
    description="Coordinates vehicle claim report generation using image, VIN, and prompt.",
    sub_agents=[
        inspection_agent,
        vision_agent,
        vin_agent,
        kb_agent,
        report_agent
    ],
    max_iterations=1
)


# Root agent for runner
root_agent = autoclaim_agent
