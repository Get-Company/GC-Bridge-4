from celery import shared_task

from documents.models import DocumentImportJob
from documents.word_import_service import DocumentWordImportService


@shared_task(name="documents.run_word_import")
def run_document_word_import(job_id: int) -> None:
    try:
        job = DocumentImportJob.objects.select_related("document", "provider").get(pk=job_id)
    except DocumentImportJob.DoesNotExist:
        return
    DocumentWordImportService().execute(job)
