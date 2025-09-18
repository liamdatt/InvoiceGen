from django.contrib.auth.decorators import login_required
from django.contrib.auth import login
from django.contrib.auth.forms import UserCreationForm
from django.shortcuts import render, redirect, get_object_or_404
from django.http import FileResponse, HttpResponse
from .forms import (
    ClientForm,
    INVOICE_GENERAL_FIELDS,
    INVOICE_PROFORMA_FIELDS,
    InvoiceForm,
    ItemFormSet,
)
from .models import Client, Invoice


@login_required
def dashboard(request):
    clients = Client.objects.all().order_by('name')
    invoices = Invoice.objects.select_related('client').all()[:10]
    return render(request, 'dashboard.html', {'clients': clients, 'invoices': invoices})


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
    return render(request, 'invoices/detail.html', {'invoice': invoice})


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
    suffix = f"-{invoice.invoice_type.lower()}"
    needs_generation = force or not invoice.pdf_file or not invoice.pdf_file.name.endswith(f"{suffix}.pdf")
    if invoice.invoice_type == Invoice.Type.GENERAL:
        if needs_generation:
            invoice.generate_general_pdf(overwrite=True)
    else:
        if needs_generation:
            invoice.generate_proforma_pdf(overwrite=True)
    if not invoice.pdf_file:
        return HttpResponse("Failed to generate invoice PDF.", status=500)
    filename = f"invoice-{invoice.pk}-{invoice.invoice_type.lower()}.pdf"
    return FileResponse(open(invoice.pdf_file.path, 'rb'), as_attachment=True, filename=filename)
