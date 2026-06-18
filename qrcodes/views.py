from django.contrib.admin.views.decorators import staff_member_required
from django.contrib import messages
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from qrcodes.forms import QrCodeForm
from qrcodes.models import QrCode
from qrcodes.services import QrCodeRenderService


@staff_member_required
def qr_code_list(request):
    qr_codes = QrCode.objects.order_by("title")
    return render(request, "qrcodes/list.html", {"qr_codes": qr_codes})


@staff_member_required
def qr_code_detail(request, pk):
    qr_code = get_object_or_404(QrCode, pk=pk)
    return render(
        request,
        "qrcodes/detail.html",
        {
            "qr_code": qr_code,
            "sizes": QrCodeRenderService.RASTER_SIZES,
            "formats": ("png", "jpg", "svg", "pdf"),
        },
    )


@staff_member_required
@require_http_methods(["GET", "POST"])
def qr_code_create(request):
    if request.method == "POST":
        form = QrCodeForm(request.POST, request.FILES)
        if form.is_valid():
            qr_code = form.save()
            messages.success(request, "QR-Code wurde angelegt.")
            return redirect("qrcodes:detail", pk=qr_code.pk)
    else:
        form = QrCodeForm(initial={"center_mode": QrCode.CenterMode.TEXT, "is_active": True})
    return render(request, "qrcodes/form.html", {"form": form, "title": "QR-Code erstellen"})


@staff_member_required
@require_http_methods(["GET", "POST"])
def qr_code_edit(request, pk):
    qr_code = get_object_or_404(QrCode, pk=pk)
    if request.method == "POST":
        form = QrCodeForm(request.POST, request.FILES, instance=qr_code)
        if form.is_valid():
            qr_code = form.save()
            messages.success(request, "QR-Code wurde gespeichert.")
            return redirect("qrcodes:detail", pk=qr_code.pk)
    else:
        form = QrCodeForm(instance=qr_code)
    return render(request, "qrcodes/form.html", {"form": form, "title": "QR-Code bearbeiten", "qr_code": qr_code})


@staff_member_required
@require_http_methods(["GET", "POST"])
def qr_code_delete(request, pk):
    qr_code = get_object_or_404(QrCode, pk=pk)
    if request.method == "POST":
        qr_code.delete()
        messages.success(request, "QR-Code wurde geloescht.")
        return redirect("qrcodes:list")
    return render(request, "qrcodes/delete.html", {"qr_code": qr_code})


@staff_member_required
def qr_code_preview(request, pk):
    qr_code = get_object_or_404(QrCode, pk=pk)
    content = QrCodeRenderService().render_raster(qr_code, "png", 512)
    return HttpResponse(content, content_type="image/png")


@staff_member_required
def qr_code_download(request, pk, file_format, size_key):
    qr_code = get_object_or_404(QrCode, pk=pk)
    try:
        export = QrCodeRenderService().build_export(qr_code, file_format, size_key)
    except ValueError as exc:
        raise Http404(str(exc)) from exc
    response = HttpResponse(export.content, content_type=export.content_type)
    response["Content-Disposition"] = f'attachment; filename="{export.filename}"'
    return response
