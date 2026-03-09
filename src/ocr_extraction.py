import io
import json
import logging
import os
from pathlib import Path

import pymupdf
from dotenv import load_dotenv
from backends.gcs_backend import make_gcs_client
from landingai_ade import LandingAIADE
from landingai_ade.lib import pydantic_to_json_schema
from landingai_ade.types import ExtractResponse, ParseResponse
from PIL import Image as PILImage
from PIL import ImageDraw

from config import GCS_LOAN_APPLICATION_PREFIX, GCS_OCR_OUTPUT_PREFIX
from schemas.ocr_schemas import AnnualAccountsSchema, BankStatementSchema, DocType
#from vector_store import get_store

load_dotenv(override=True)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("ocr_pipeline.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

# Verify Landing AI ADE API key is loaded
if not os.getenv("VISION_AGENT_API_KEY", "").strip():
    raise ValueError("VISION_AGENT_API_KEY is not set. Add it to .env in the project root.")
logger.info("VISION_AGENT_API_KEY is set.")

client = LandingAIADE(apikey=os.getenv("VISION_AGENT_API_KEY"))
logger.info("Authenticated client initialized")

# Map document types to extraction schemas
schema_per_doc_type = {
    "bank_statement": BankStatementSchema,
    "annual_company_report": AnnualAccountsSchema,
}
doc_type_json_schema = pydantic_to_json_schema(DocType)

# Colours used when drawing bounding boxes (keyed by Landing AI chunk type)
_CHUNK_TYPE_COLORS = {
    "chunkText": (40, 167, 69),
    "chunkTable": (0, 123, 255),
    "chunkMarginalia": (111, 66, 193),
    "chunkFigure": (255, 0, 255),
    "chunkLogo": (144, 238, 144),
    "chunkCard": (255, 165, 0),
    "chunkAttestation": (0, 255, 255),
    "chunkScanCode": (255, 193, 7),
    "chunkForm": (220, 20, 60),
    "tableCell": (173, 216, 230),
    "table": (70, 130, 180),
}


def _draw_extraction_bounding_boxes(
    groundings: dict,
    document_path: Path,
) -> list[tuple[str, bytes]]:
    """Draw bounding boxes on document pages for the supplied grounding chunks.

    Returns a list of ``(filename, png_bytes)`` tuples — one per annotated page.
    Only pages that contain at least one matching chunk are included.

    Args:
        groundings:     dict of chunk_id -> grounding object (page, box, type).
        document_path:  Path to the source PDF or image file.
    """

    def _annotate_page(image: PILImage.Image, groundings: dict, page_num: int):
        annotated = image.copy()
        draw = ImageDraw.Draw(annotated)
        img_w, img_h = image.size
        found = 0
        for gid, grounding in groundings.items():
            if grounding.page != page_num:
                continue
            found += 1
            box = grounding.box
            x1 = int(box.left * img_w)
            y1 = int(box.top * img_h)
            x2 = int(box.right * img_w)
            y2 = int(box.bottom * img_h)
            color = _CHUNK_TYPE_COLORS.get(grounding.type, (128, 128, 128))
            draw.rectangle([x1, y1, x2, y2], outline=color, width=3)
            label = f"{grounding.type}:{gid}"
            label_y = max(0, y1 - 20)
            draw.rectangle([x1, label_y, x1 + len(label) * 8, y1], fill=color)
            draw.text((x1 + 2, label_y + 2), label, fill=(255, 255, 255))
        return annotated if found > 0 else None

    def _to_bytes(img: PILImage.Image) -> bytes:
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    document_path = Path(document_path)
    results: list[tuple[str, bytes]] = []

    if document_path.suffix.lower() == ".pdf":
        pdf = pymupdf.open(document_path)
        for page_num in range(len(pdf)):
            page = pdf[page_num]
            pix = page.get_pixmap(matrix=pymupdf.Matrix(2, 2))
            img = PILImage.frombytes("RGB", [pix.width, pix.height], pix.samples)
            annotated = _annotate_page(img, groundings, page_num)
            if annotated is not None:
                filename = f"{document_path.stem}_page_{page_num + 1}_annotated.png"
                results.append((filename, _to_bytes(annotated)))
        pdf.close()
    else:
        img = PILImage.open(document_path)
        if img.mode != "RGB":
            img = img.convert("RGB")
        annotated = _annotate_page(img, groundings, 0)
        if annotated is not None:
            filename = f"{document_path.stem}_page_annotated.png"
            results.append((filename, _to_bytes(annotated)))

    return results


class DocumentAI:
    """Wrapper around the Landing AI ADE SDK.
    Parses a PDF, classifies its type, and extracts structured fields.
    """

    def __init__(self, source_document_url, case_number: str = None):
        self.source_document_url = Path(source_document_url)
        # Default case_number to parent folder name so that docs stored under
        # data/{case_number}/ pick it up automatically.
        self.case_number = case_number or self.source_document_url.parent.name
        self.parse_result: ParseResponse | None = None
        self.extraction: dict | None = None
        self.extraction_metadata: dict | None = None
        self.document_type: str | None = None

    def parse(self) -> None:
        """Extract Markdown from PDF pages via the Landing AI parse API."""
        self.parse_result = client.parse(
            document=self.source_document_url,
            split="page",
            model="dpt-2-latest",
        )
        logger.info(f"Parsing completed for {self.source_document_url}")

    def classify(self) -> None:
        """Determine document type using the first page markdown."""
        first_page_markdown = self.parse_result.splits[0].markdown
        logger.info("Extracting Document Type...")
        extraction_result: ExtractResponse = client.extract(
            schema=doc_type_json_schema,
            markdown=first_page_markdown,
        )
        self.document_type = extraction_result.extraction["type"]
        logger.info(f"Document Type Extraction: {self.document_type}")

    def extract(self) -> None:
        """Extract structured fields using the schema for this document type."""
        json_schema = pydantic_to_json_schema(schema_per_doc_type[self.document_type])
        extraction_result: ExtractResponse = client.extract(
            schema=json_schema,
            markdown=self.parse_result.markdown,
        )
        logger.info(f"Detailed Extraction: {extraction_result.extraction}")
        self.extraction = extraction_result.extraction
        self.extraction_metadata = extraction_result.extraction_metadata

    def persist(self) -> str:
        """Upload extraction results to GCS and return the virtual OCR output path.

        GCS layout::

            <case_number>/ocr_output/<document_stem>_extraction.json
            <case_number>/ocr_output/<document_stem>_page_N_annotated.png

        Returns:
            The GCS virtual path of the extraction JSON (for use in agent state).
        """
        bucket_name = os.environ["BUCKET_NAME"]
        project = os.environ.get("GOOGLE_CLOUD_PROJECT")
        gcs = make_gcs_client(project=project)
        bucket = gcs.bucket(bucket_name)

        doc_stem = self.source_document_url.stem
        ocr_prefix = f"{self.case_number}/{GCS_OCR_OUTPUT_PREFIX}"
        logger.info("Uploading OCR output to GCS: gs://%s/%s/", bucket_name, ocr_prefix)

        # --- 1. Upload extraction JSON ---
        extraction_data = {
            "document_name": self.source_document_url.name,
            "document_type": self.document_type,
            "extraction": self.extraction,
        }
        json_key = f"{ocr_prefix}/{doc_stem}_extraction.json"
        json_bytes = json.dumps(extraction_data, indent=2, default=str).encode("utf-8")
        bucket.blob(json_key).upload_from_string(
            json_bytes, content_type="application/json"
        )
        logger.info("Uploaded extraction JSON: %s", json_key)

        # --- 2. Upload bounding-box PNGs for extracted fields only ---
        if self.extraction_metadata and self.parse_result:
            document_grounds = {}
            for field, meta in self.extraction_metadata.items():
                refs = meta.get("references") or []
                if not refs:
                    continue
                chunk_id = refs[0]
                if chunk_id in self.parse_result.grounding:
                    document_grounds[chunk_id] = self.parse_result.grounding[chunk_id]

            for filename, png_bytes in _draw_extraction_bounding_boxes(
                document_grounds, self.source_document_url
            ):
                png_key = f"{ocr_prefix}/{filename}"
                bucket.blob(png_key).upload_from_string(
                    png_bytes, content_type="image/png"
                )
                logger.info("Uploaded annotated PNG: %s", png_key)

        return f"/disk-files/{json_key}"

    def embed_and_store(self, store) -> int:
        """Store parse_result chunks in the LangGraph store for semantic search.

        Each chunk is stored under the namespace ``("cases", case_number)`` so
        that documents from different cases remain isolated.  The LangGraph
        Platform will embed the stored values automatically using the embedding
        model configured in ``langgraph.json``.

        Args:
            store: The LangGraph ``BaseStore`` instance injected by the runtime.

        Returns:
            Number of chunks stored.

        Raises:
            ValueError: If parse() has not been called first.
        """
        if self.parse_result is None:
            raise ValueError("parse() must be called before embed_and_store()")

        namespace = ("cases", self.case_number)
        count = 0
        for chunk in self.parse_result.chunks:
            text = chunk.markdown
            if not text or not text.strip():
                continue

            grounding = self.parse_result.grounding.get(chunk.id)
            page_num = int(grounding.page) if grounding else 0
            chunk_type = grounding.type if grounding else "unknown"

            store.put(
                namespace,
                chunk.id,
                {
                    "text": text,
                    "document_name": self.source_document_url.name,
                    "document_type": self.document_type,
                    "page_num": page_num,
                    "chunk_type": chunk_type,
                },
            )
            count += 1

        if count == 0:
            logger.warning(
                "No non-empty chunks to embed for %s", self.source_document_url
            )
        else:
            logger.info(
                "Stored %d chunks in store (namespace=%s)", count, namespace
            )
        return count


if __name__ == "__main__":
    case_number = "SteveGoodman"   # matches the subdirectory under data/
    document_url = Path(f"/Users/stevegoodman/dev/fionaa-be/data/{case_number}/5573DraftAccounts.pdf")

    document = DocumentAI(document_url, case_number=case_number)
    document.parse()
    document.classify()
    document.extract()

    #Persist does NOT call the Landing AI API — safe to run once extraction is complete.
    document.persist()

    # embed_and_store requires a LangGraph store injected by the runtime;
    # skip in standalone __main__ execution.
