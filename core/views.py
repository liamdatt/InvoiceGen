from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.http import FileResponse, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.template.loader import render_to_string
from django.views.decorators.http import require_POST
from .forms import (
    ClientForm,
    INVOICE_GENERAL_FIELDS,
    INVOICE_PROFORMA_FIELDS,
    InvoiceForm,
    ItemFormSet,
)
from .google import (
    GoogleConfigurationError,
    build_flow,
    download_drive_file,
    ensure_account,
    fetch_account_email,
    list_drive_folders,
    send_invoice_email,
    upload_invoice_pdf,
)
from .models import Client, GoogleAccount, Invoice


@login_required
def dashboard(request):
    clients = Client.objects.all().order_by('name')
    invoices = Invoice.objects.select_related('client').all()[:10]
    google_enabled = _google_is_configured()
    google_account = None
    google_email = ""
    drive_folder = ""
    if google_enabled:
        google_account = ensure_account(request.user)
        if google_account.is_connected and not google_account.email:
            try:
                google_email = fetch_account_email(google_account)
            except Exception:
                google_email = google_account.email
        else:
            google_email = google_account.email if google_account else ""
        if google_account:
            drive_folder = google_account.drive_folder_display
    context = {
        'clients': clients,
        'invoices': invoices,
        'google_enabled': google_enabled,
        'google_account': google_account,
        'google_email': google_email,
        'google_drive_folder': drive_folder,
    }
    return render(request, 'dashboard.html', context)


def signup(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
    if request.method == 'POST':
        form = UserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect('dashboard')
    else:
        form = UserCreationForm()
    return render(request, 'auth/signup.html', {'form': form})


GENERAL_FIELDS = list(INVOICE_GENERAL_FIELDS)
PROFORMA_FIELDS = list(INVOICE_PROFORMA_FIELDS)


def _google_is_configured() -> bool:
    return bool(settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET)


def _get_google_account(request) -> GoogleAccount:
    if not _google_is_configured():
        raise GoogleConfigurationError("Google OAuth is not configured for this installation.")
    return ensure_account(request.user)


@login_required
def google_connect(request):
    try:
        _get_google_account(request)
    except GoogleConfigurationError as exc:
        messages.error(request, str(exc))
        return redirect('dashboard')

    try:
        flow = build_flow(request)
        authorization_url, state = flow.authorization_url(
            access_type='offline',
            include_granted_scopes='true',
            prompt='consent',
        )
        request.session['google_auth_state'] = state
        return redirect(authorization_url)
    except Exception as exc:  # pragma: no cover - network errors
        messages.error(request, f"Unable to start Google authentication: {exc}")
        return redirect('dashboard')


@login_required
def google_callback(request):
    state = request.GET.get('state')
    session_state = request.session.pop('google_auth_state', None)
    if not state or not session_state or state != session_state:
        messages.error(request, "Google authentication state did not match. Please try again.")
        return redirect('dashboard')

    try:
        flow = build_flow(request)
        flow.fetch_token(authorization_response=request.build_absolute_uri())
        credentials = flow.credentials
        account = _get_google_account(request)
        account.save_credentials(credentials)
        try:
            fetch_account_email(account)
        except Exception:
            pass
        messages.success(request, "Google account connected successfully.")
        return redirect('google_drive_select')
    except GoogleConfigurationError as exc:
        messages.error(request, str(exc))
    except Exception as exc:  # pragma: no cover - network errors
        messages.error(request, f"Failed to complete Google authentication: {exc}")
    return redirect('dashboard')


@login_required
@require_POST
def google_disconnect(request):
    try:
        account = _get_google_account(request)
    except GoogleConfigurationError as exc:
        messages.error(request, str(exc))
        return redirect('dashboard')

    if account.is_connected:
        account.clear_credentials()
        messages.success(request, "Google account disconnected.")
    else:
        messages.info(request, "No Google account is currently connected.")
    return redirect('dashboard')


@login_required
def google_drive_select(request):
    try:
        account = _get_google_account(request)
    except GoogleConfigurationError as exc:
        messages.error(request, str(exc))
        return redirect('dashboard')

    if not account.is_connected:
        messages.info(request, "Connect your Google account before selecting a Drive folder.")
        return redirect('dashboard')

    folders = []
    try:
        folders = list_drive_folders(account)
    except Exception as exc:  # pragma: no cover - network errors
        messages.warning(request, f"Unable to list Drive folders: {exc}")

    if request.method == 'POST':
        folder_id = request.POST.get('folder_id', '').strip()
        folder_name = request.POST.get('folder_name', '').strip()
        if folder_id:
            account.drive_folder_id = folder_id
            account.drive_folder_name = folder_name or folder_id
            account.save(update_fields=['drive_folder_id', 'drive_folder_name', 'updated_at'])
            messages.success(request, 'Google Drive folder saved for invoices.')
            return redirect('dashboard')
        messages.error(request, 'Select a folder from the list or provide a folder ID.')

    context = {
        'folders': folders,
        'current_folder': account.drive_folder_display,
        'account': account,
    }
    return render(request, 'google/select_folder.html', context)


@login_required
def clients_list(request):
    clients = Client.objects.all().order_by('name')
    return render(request, 'clients/list.html', {'clients': clients})


@login_required
def client_create(request):
    if request.method == 'POST':
        form = ClientForm(request.POST)
        if form.is_valid():
            client = form.save()
            return redirect('clients_detail', pk=client.pk)
    else:
        form = ClientForm()
    return render(request, 'clients/form.html', {'form': form, 'title': 'New Client'})


@login_required
def client_update(request, pk: int):
    client = get_object_or_404(Client, pk=pk)
    if request.method == 'POST':
        form = ClientForm(request.POST, instance=client)
        if form.is_valid():
            form.save()
            return redirect('clients_detail', pk=client.pk)
    else:
        form = ClientForm(instance=client)
    return render(request, 'clients/form.html', {'form': form, 'title': 'Edit Client'})


@login_required
def client_detail(request, pk: int):
    client = get_object_or_404(Client, pk=pk)
    invoices = client.invoices.all()
    return render(request, 'clients/detail.html', {'client': client, 'invoices': invoices})


@login_required
def invoice_create(request, client_pk: int):
    client = get_object_or_404(Client, pk=client_pk)
    if request.method == 'POST':
        form = InvoiceForm(request.POST)
        formset = ItemFormSet(request.POST, prefix='items')
        if form.is_valid() and formset.is_valid():
            invoice = form.save()
            formset.instance = invoice
            formset.save()
            return redirect('invoice_detail', pk=invoice.pk)
    else:
        form = InvoiceForm(initial={'client': client, 'invoice_type': Invoice.Type.GENERAL})
        formset = ItemFormSet(prefix='items')
    context = {
        'form': form,
        'formset': formset,
        'client': client,
        'title': 'New Invoice',
        'general_fields': [form[field_name] for field_name in GENERAL_FIELDS],
        'proforma_fields': [form[field_name] for field_name in PROFORMA_FIELDS],
    }
    return render(request, 'invoices/form.html', context)


@login_required
def invoice_detail(request, pk: int):
    invoice = get_object_or_404(Invoice.objects.select_related('client'), pk=pk)
    google_enabled = _google_is_configured()
    google_account = ensure_account(request.user) if google_enabled else None
    context = {
        'invoice': invoice,
        'google_enabled': google_enabled,
        'google_account': google_account,
        'can_email': bool(
            invoice.client.email
            and google_account
            and google_account.is_connected
        ),
    }
    return render(request, 'invoices/detail.html', context)


@login_required
def invoice_update(request, pk: int):
    invoice = get_object_or_404(Invoice, pk=pk)
    if request.method == 'POST':
        form = InvoiceForm(request.POST, instance=invoice)
        formset = ItemFormSet(request.POST, instance=invoice, prefix='items')
        if form.is_valid() and formset.is_valid():
            form.save()
            formset.save()
            return redirect('invoice_detail', pk=invoice.pk)
    else:
        form = InvoiceForm(instance=invoice)
        formset = ItemFormSet(instance=invoice, prefix='items')
    context = {
        'form': form,
        'formset': formset,
        'client': invoice.client,
        'title': 'Edit Invoice',
        'general_fields': [form[field_name] for field_name in GENERAL_FIELDS],
        'proforma_fields': [form[field_name] for field_name in PROFORMA_FIELDS],
    }
    return render(request, 'invoices/form.html', context)


@login_required
def invoice_delete(request, pk: int):
    invoice = get_object_or_404(Invoice, pk=pk)
    client_pk = invoice.client_id
    if request.method == 'POST':
        if invoice.pdf_file:
            invoice.pdf_file.delete(save=False)
        invoice.delete()
        return redirect('clients_detail', pk=client_pk)
    return redirect('invoice_detail', pk=invoice.pk)


@login_required
def invoice_pdf(request, pk: int):
    invoice = get_object_or_404(Invoice, pk=pk)
    force = request.GET.get('force') == '1'
    google_account = None
    if _google_is_configured():
        try:
            google_account = ensure_account(request.user)
        except Exception:
            google_account = None
        if google_account and not google_account.is_connected:
            google_account = None

    if google_account:
        generated_bytes = None
        try:
            if force or not invoice.has_drive_file:
                filename, pdf_content = invoice.generate_pdf_bytes(overwrite=True, store_local=False)
                drive_file = upload_invoice_pdf(google_account, invoice, filename, pdf_content)
                file_id = drive_file.get('id')
                if file_id:
                    invoice.mark_drive_file(
                        file_id,
                        drive_file.get('webViewLink'),
                        drive_file.get('webContentLink'),
                    )
                generated_bytes = pdf_content
            pdf_bytes = download_drive_file(google_account, invoice.drive_file_id) if invoice.drive_file_id else generated_bytes
        except Exception:
            filename, pdf_bytes = invoice.generate_pdf_bytes(overwrite=True, store_local=False)

        if not pdf_bytes:
            return HttpResponse("Failed to generate invoice PDF.", status=500)
        response = HttpResponse(pdf_bytes, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="{invoice.pdf_filename()}"'
        return response

    suffix = f"-{invoice.invoice_type.lower()}"
    needs_generation = force or not invoice.pdf_file or not invoice.pdf_file.name.endswith(f"{suffix}.pdf")
    if invoice.invoice_type == Invoice.Type.GENERAL:
        if needs_generation:
            invoice.generate_general_pdf(overwrite=True, store_local=True)
    else:
        if needs_generation:
            invoice.generate_proforma_pdf(overwrite=True, store_local=True)
    if not invoice.pdf_file:
        return HttpResponse("Failed to generate invoice PDF.", status=500)
    return FileResponse(invoice.pdf_file.open('rb'), as_attachment=True, filename=invoice.pdf_filename())


@login_required
@require_POST
def invoice_send_email(request, pk: int):
    invoice = get_object_or_404(Invoice.objects.select_related('client'), pk=pk)
    if not invoice.client.email:
        messages.error(request, "The client for this invoice does not have an email address.")
        return redirect('invoice_detail', pk=pk)

    try:
        account = _get_google_account(request)
    except GoogleConfigurationError as exc:
        messages.error(request, str(exc))
        return redirect('invoice_detail', pk=pk)

    if not account.is_connected:
        messages.error(request, "Connect your Google account before sending invoices.")
        return redirect('invoice_detail', pk=pk)

    if not account.email:
        try:
            fetch_account_email(account)
        except Exception:
            pass

    try:
        filename, pdf_bytes = invoice.generate_pdf_bytes(overwrite=True, store_local=False)
        drive_file = upload_invoice_pdf(account, invoice, filename, pdf_bytes)
        file_id = drive_file.get('id')
        if file_id:
            invoice.mark_drive_file(
                file_id,
                drive_file.get('webViewLink'),
                drive_file.get('webContentLink'),
            )
        subject = f"Invoice #{invoice.pk}"
        sender_name = request.user.get_full_name() or request.user.username
        body = render_to_string(
            'emails/invoice_email.txt',
            {
                'invoice': invoice,
                'sender_name': sender_name,
                'drive_link': invoice.drive_web_view_link,
            },
        )
        send_invoice_email(
            account,
            invoice,
            filename,
            pdf_bytes,
            invoice.client.email,
            body,
            subject,
        )
        messages.success(request, f"Invoice emailed to {invoice.client.email}.")
    except Exception as exc:  # pragma: no cover - network errors
        messages.error(request, f"Failed to send invoice email: {exc}")
    return redirect('invoice_detail', pk=pk)
