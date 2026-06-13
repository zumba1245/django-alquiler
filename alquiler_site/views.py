from __future__ import annotations

from django.http import HttpRequest, HttpResponse
from django.shortcuts import render


def error_404(request: HttpRequest, exception) -> HttpResponse:
    return render(request, "404.html", status=404)


def error_500(request: HttpRequest) -> HttpResponse:
    return render(request, "500.html", status=500)
