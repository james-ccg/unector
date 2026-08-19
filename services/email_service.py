"""
Thin routing layer for email operations. Right now this just forwards to
gmail_service, but keeping this indirection means bot.py doesn't need to
change if we ever add Outlook support alongside Gmail (e.g. per-company
provider choice stored in the DB).
"""
from services import gmail_service


def find_rc_pdf_by_load_id(company_id: int, load_id: str) -> bytes | None:
    """Searches the company's connected email account for the RC PDF matching this load ID."""
    return gmail_service.find_rc_pdf_by_load_id(company_id, load_id)


def send_email(company_id: int, to_address: str, subject: str, body: str, attachments: list | None = None):
    """Sends an email from the company's connected email account."""
    return gmail_service.send_email(company_id, to_address, subject, body, attachments)
