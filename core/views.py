from django.contrib.auth.decorators import login_required
from django.contrib.auth import login
from django.contrib.auth.forms import UserCreationForm
from django.shortcuts import render, redirect, get_object_or_404
from django.forms import modelform_factory, inlineformset_factory
from django.http import FileResponse, HttpResponse
from .models import Client, Invoice, InvoiceItem


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


ClientForm = modelform_factory(Client, fields=['name', 'email', 'phone', 'address'])
InvoiceForm = modelform_factory(Invoice, fields=['client', 'invoice_type', 'vehicle', 'lic_no', 'chassis_no', 'date'])
ItemFormSet = inlineformset_factory(Invoice, InvoiceItem, fields=['description', 'labour_cost', 'parts_cost'], extra=1, can_delete=True)


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
    return render(request, 'invoices/form.html', {'form': form, 'formset': formset, 'client': client, 'title': 'New Invoice'})


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
    return render(request, 'invoices/form.html', {'form': form, 'formset': formset, 'client': invoice.client, 'title': 'Edit Invoice'})


@login_required
def invoice_pdf(request, pk: int):
    invoice = get_object_or_404(Invoice, pk=pk, invoice_type=Invoice.Type.GENERAL)
    force = request.GET.get('force') == '1'
    if force or not invoice.pdf_file:
        invoice.generate_general_pdf(overwrite=True)
    if not invoice.pdf_file:
        return HttpResponse("Failed to generate invoice PDF.", status=500)
    return FileResponse(open(invoice.pdf_file.path, 'rb'), as_attachment=True, filename=f"invoice-{invoice.pk}.pdf")
