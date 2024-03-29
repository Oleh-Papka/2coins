import json
from collections import defaultdict

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Sum, F, FloatField, Q
from django.db.models.functions import TruncDate, Coalesce, Cast
from django.http import JsonResponse
from django.urls import reverse_lazy
from django.views.generic import ListView, DetailView, TemplateView, CreateView, UpdateView, DeleteView

from . import forms, models
from profiles.models import Profile
from .utils import currency_converter


def get_template_chart_data(query_data):
    res = {'data': [], 'labels': [], 'colors': []}
    for dct in query_data:
        for k in dct.keys():
            res[k].append(dct[k])
    return res


# Currencies

class CurrencyList(LoginRequiredMixin, ListView):
    login_url = 'login'
    model = models.Currency
    context_object_name = 'currency_list'
    template_name = "budget/currency/currency_list.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["instance_name"] = 'Currencies'
        context['currencies'] = models.Currency.objects.all()
        return context


class CurrencyCreateView(LoginRequiredMixin, CreateView):
    login_url = reverse_lazy('login')
    model = models.Currency
    form_class = forms.CurrencyForm
    template_name = 'budget/currency/currency_create.html'
    success_url = reverse_lazy('currency_list')

    def form_valid(self, form):
        messages.success(self.request, f"Currency '{form.cleaned_data.get('name')}' created!")
        return super().form_valid(form)

    def form_invalid(self, form):
        messages.warning(self.request, "Something went wrong!")
        return super().form_invalid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['acct_types'] = models.Currency.MONEY_TYPES_CHOICES
        return context


class CurrencyUpdateView(LoginRequiredMixin, UpdateView):
    login_url = reverse_lazy('login')
    model = models.Currency
    form_class = forms.CurrencyForm
    template_name = 'budget/currency/currency_edit.html'
    success_url = reverse_lazy('currency_list')

    def form_valid(self, form):
        messages.success(self.request, f"Currency '{form.cleaned_data.get('name')}' updated!")
        return super().form_valid(form)

    def form_invalid(self, form):
        messages.warning(self.request, "Something went wrong!")
        return super().form_invalid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['acct_types'] = models.Currency.MONEY_TYPES_CHOICES
        return context


class CurrencyDeleteView(LoginRequiredMixin, DeleteView):
    login_url = reverse_lazy('login')
    model = models.Currency
    template_name = 'budget/currency/currency_delete.html'
    success_url = reverse_lazy('currency_list')

    def form_valid(self, form):
        messages.success(self.request, f"Currency '{self.object.name}' deleted!")
        return super().form_valid(form)


# Accounts

class AccountListView(LoginRequiredMixin, ListView):
    login_url = 'login'
    model = models.Account
    template_name = "budget/account/account_list.html"

    def get_context_data(self, **kwargs):
        data_acct_query = (
            models.Account.objects
            .filter(profile__user=self.request.user)
            .annotate(
                data=Coalesce(Sum('transaction__amount'), 0.0) + Cast(F('balance'), output_field=FloatField())
            )
            .annotate(labels=F('name'))
            .annotate(colors=F('color'))
            .values('data', 'labels', 'colors')
        )

        accounts = self.object_list

        for account in accounts:
            grand_total = 0
            txns = models.Transaction.objects.filter(Q(account=account) | Q(transfer_account=account))

            for txn in txns:
                if txn.amount_default_currency:
                    amount_temp = txn.amount_default_currency
                else:
                    amount_temp = txn.amount

                if txn.txn_type == '>' and txn.transfer_account != account:
                    grand_total -= amount_temp
                else:
                    grand_total += amount_temp

            account.total = account.balance + grand_total

        context = super().get_context_data(**kwargs)
        context['accounts_list'] = accounts
        context['data_acct'] = get_template_chart_data(data_acct_query)

        return context

    def get_queryset(self):
        profile = Profile.objects.get(user=self.request.user)
        return super().get_queryset().filter(profile=profile)


class AccountDetailView(LoginRequiredMixin, DetailView):
    login_url = 'login'
    model = models.Account
    template_name = 'budget/account/account.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        transactions_data = models.Transaction.objects.filter(
            Q(account=self.object) | Q(transfer_account=self.object)).order_by('-date').annotate(
            truncated_date=TruncDate('date'))
        category_ids = models.Category.objects.filter(profile__user=self.request.user).values_list('id', flat=True)
        categories_data = models.Category.objects.filter(profile__user=self.request.user).filter(id__in=category_ids)
        transactions = []

        temp_date = transactions_data[0].truncated_date if transactions_data else None
        temp_total = 0
        temp_txns = []
        grand_total = self.object.balance

        categories = {}
        for cat in categories_data:
            categories[cat] = {
                "label": cat.name,
                "data": [0],
                "backgroundColor": str(cat.color) + '2a',
                "borderColor": str(cat.color),
                "borderWidth": 2,
                "borderRadius": 5,
            }

        for txn in transactions_data:
            if txn.truncated_date != temp_date:
                transactions.append({
                    'date': temp_date,
                    'total': temp_total,
                    'txns': temp_txns
                })

                grand_total += temp_total

                temp_date = txn.truncated_date
                temp_total = 0
                temp_txns = [txn]

                for cat, data in categories.items():
                    if cat == txn.category:
                        data['data'].append(txn.amount_default_currency if txn.amount_default_currency else txn.amount)
                    else:
                        data['data'].append(0)
            else:
                temp_txns.append(txn)

                for cat, data in categories.items():
                    if cat == txn.category:
                        data['data'][-1] += txn.amount_default_currency if txn.amount_default_currency else txn.amount

            if txn.txn_type == '>':
                if txn.transfer_account != self.object:
                    if txn.amount_default_currency:
                        txn.amount_default_currency = -txn.amount_default_currency
                        amount = txn.amount_default_currency
                    else:
                        txn.amount = -txn.amount
                        amount = txn.amount
                else:
                    amount = txn.amount_default_currency if txn.amount_default_currency else txn.amount
            elif txn.amount_default_currency:
                amount = txn.amount_default_currency
            else:
                amount = txn.amount

            temp_total += amount

        else:
            if transactions_data:
                transactions.append({
                    'date': temp_date,
                    'total': temp_total,
                    'txns': temp_txns
                })

                grand_total += temp_total

        data_acct_query = (
            models.Category.objects
            .filter(profile__user=self.request.user)
            .filter(transaction__account=self.object)
            .annotate(data=Coalesce(Sum('transaction__amount'), 0.0))
            .annotate(labels=F('name'))
            .annotate(colors=F('color'))
            .values('data', 'labels', 'colors')
        )

        for i in categories.values():
            i["data"] = i["data"][::-1]

        context["data_txn"] = {
            "labels": [i['date'].strftime("%d/%m") for i in transactions][::-1],
            "datasets": [i for i in categories.values()]
        }

        context['data_acct'] = get_template_chart_data(data_acct_query)
        context["transactions"] = transactions
        context['grad_total'] = grand_total

        return context


class AccountCreateView(LoginRequiredMixin, CreateView):
    login_url = reverse_lazy('login')
    model = models.Account
    form_class = forms.AccountForm
    template_name = 'budget/account/account_create.html'
    success_url = reverse_lazy('account_list')

    def form_valid(self, form):
        self.object = form.save(commit=False)
        self.object.profile = Profile.objects.get(user=self.request.user)
        self.object.save()
        messages.success(self.request, f"Account '{form.cleaned_data.get('name')}' created!")
        return super().form_valid(form)

    def form_invalid(self, form):
        messages.warning(self.request, "Something went wrong!")
        return super().form_invalid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['currencies'] = models.Currency.objects.all()
        context['profile'] = Profile.objects.get(user=self.request.user)
        return context


class AccountUpdateView(LoginRequiredMixin, UpdateView):
    login_url = reverse_lazy('login')
    model = models.Account
    form_class = forms.AccountUpdateForm
    template_name = 'budget/account/account_edit.html'
    success_url = reverse_lazy('account_list')

    def get_initial(self):
        initial = super().get_initial()

        initial['new_balance'] = (
            models.Account.objects
            .filter(profile__user=self.request.user, pk=self.object.id)
            .annotate(real_balance=Coalesce(Sum(F('transaction__amount')), 0.0) + Cast(F('balance'),
                                                                                       output_field=FloatField()))
            .values('real_balance')
        )[0]['real_balance']

        return initial

    def form_valid(self, form):
        messages.success(self.request, f"Account '{form.cleaned_data.get('name')}' updated!")

        new_balance = form.cleaned_data['new_balance']
        real_balance = (
            models.Account.objects
            .filter(profile__user=self.request.user, pk=self.object.id)
            .annotate(real_balance=Coalesce(Sum(F('transaction__amount')), 0.0) + Cast(F('balance'),
                                                                                       output_field=FloatField()))
            .values('real_balance')
        )[0]['real_balance']

        if new_balance != real_balance:
            txn_amount = new_balance - real_balance

            models.Transaction.objects.create(
                category=models.Category.objects.get(cat_type=models.Category.OTHER),
                account=self.object,
                txn_type=models.Transaction.INCOME if txn_amount > 0 else models.Transaction.EXPENSE,
                amount=txn_amount
            )

        return super().form_valid(form)

    def form_invalid(self, form):
        messages.warning(self.request, "Something went wrong!")
        return super().form_invalid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['currencies'] = [(curr.id, curr.abbr, curr.symbol) for curr in models.Currency.objects.all()]
        return context


class AccountDeleteView(LoginRequiredMixin, DeleteView):
    login_url = reverse_lazy('login')
    model = models.Account
    template_name = 'budget/account/account_delete.html'
    success_url = reverse_lazy('account_list')

    def form_valid(self, form):
        messages.success(self.request, f"Account '{self.object.name}' deleted!")
        return super().form_valid(form)


# Categories

class CategoryList(LoginRequiredMixin, ListView):
    login_url = 'login'
    model = models.Category
    context_object_name = 'category_list'
    template_name = "budget/category/category_list.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        income_categories_query = (
            models.Category.objects
            .filter(profile__user=self.request.user, cat_type=models.Category.INCOME)
            .annotate(data=Coalesce(Sum('transaction__amount'), 0.0))
            .annotate(labels=F('name'))
            .annotate(colors=F('color'))
            .values('data', 'labels', 'colors')
        )
        income_other_query = (
            models.Category.objects
            .filter(profile__user=self.request.user,
                    cat_type=models.Category.OTHER,
                    transaction__txn_type=models.Transaction.INCOME)
            .annotate(data=Coalesce(Sum('transaction__amount'), 0.0))
            .annotate(labels=F('name'))
            .annotate(colors=F('color'))
            .values('data', 'labels', 'colors')
        )
        expense_categories_query = (
            models.Category.objects
            .filter(profile__user=self.request.user, cat_type=models.Category.EXPENSE)
            .annotate(data=Coalesce(Sum('transaction__amount'), 0.0))
            .annotate(labels=F('name'))
            .annotate(colors=F('color'))
            .values('data', 'labels', 'colors')
        )
        expense_other_query = (
            models.Category.objects
            .filter(profile__user=self.request.user,
                    cat_type=models.Category.OTHER,
                    transaction__txn_type=models.Transaction.EXPENSE)
            .annotate(data=Coalesce(Sum('transaction__amount'), 0.0))
            .annotate(labels=F('name'))
            .annotate(colors=F('color'))
            .values('data', 'labels', 'colors')
        )
        transfer_query = (
            models.Category.objects
            .filter(profile__user=self.request.user,
                    cat_type=models.Category.TRANSFER,
                    transaction__txn_type=models.Transaction.TRANSFER)
            .annotate(data=Coalesce(Sum('transaction__amount'), 0.0))
            .annotate(labels=F('name'))
            .annotate(colors=F('color'))
            .values('data', 'labels', 'colors')
        )

        data_income = income_categories_query | income_other_query
        data_expense = expense_categories_query | expense_other_query
        data_special = income_other_query | expense_other_query | transfer_query

        context['data_income'] = get_template_chart_data(data_income)
        context['data_expense'] = get_template_chart_data(data_expense)
        context['data_special'] = get_template_chart_data(data_special)

        return context

    def get_queryset(self):
        profile = Profile.objects.get(user=self.request.user)
        return super().get_queryset().filter(profile=profile)


class CategoryDetailView(LoginRequiredMixin, DetailView):
    login_url = 'login'
    model = models.Category
    template_name = "budget/category/category.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        transaction_dict = defaultdict(list)
        transactions = self.get_object().get_transactions_by_category(self.request.user).annotate(
            truncated_date=TruncDate('date'))

        for transaction in transactions:
            transaction_dict[transaction.truncated_date].append(transaction)

        res = dict()
        data_cat = {'data': [], 'labels': []}

        for k, v in dict(transaction_dict).items():
            res[k] = {'total': sum([i.amount_default_currency if i.amount_default_currency else i.amount for i in v]),
                      'txns': v}
            data_cat['data'].append(abs(res[k]['total']))
            data_cat['labels'].append(k.strftime("%d/%m"))

        data_cat['color'] = self.object.color
        data_cat['data'].reverse()
        data_cat['labels'].reverse()

        context['transaction_dict'] = dict(res)
        context['data_cat'] = data_cat

        return context


class CategoryCreateView(LoginRequiredMixin, CreateView):
    login_url = reverse_lazy('login')
    model = models.Category
    form_class = forms.CategoryForm
    template_name = 'budget/category/category_create.html'
    success_url = reverse_lazy('category_list')

    def get_initial(self):
        initial = super().get_initial()

        if cat_type := self.request.GET.get('cat_type'):
            initial['cat_type'] = '-' if cat_type == 'expense' else '+'

        return initial

    def form_valid(self, form):
        self.object = form.save(commit=False)
        self.object.profile = Profile.objects.get(user=self.request.user)
        self.object.save()
        messages.success(self.request, f"Category '{form.cleaned_data.get('name')}' created!")
        return super().form_valid(form)

    def form_invalid(self, form):
        messages.warning(self.request, "Something went wrong!")
        return super().form_invalid(form)


class CategoryUpdateView(LoginRequiredMixin, UpdateView):
    login_url = reverse_lazy('login')
    model = models.Category
    form_class = forms.CategoryForm
    template_name = 'budget/category/category_edit.html'
    success_url = reverse_lazy('category_list')

    def form_valid(self, form):
        messages.success(self.request, f"Category '{form.cleaned_data.get('name')}' updated!")
        return super().form_valid(form)

    def form_invalid(self, form):
        messages.warning(self.request, "Something went wrong!")
        return super().form_invalid(form)


class CategoryDeleteView(LoginRequiredMixin, DeleteView):
    login_url = reverse_lazy('login')
    model = models.Category
    template_name = 'budget/category/category_delete.html'
    success_url = reverse_lazy('category_list')

    def form_valid(self, form):
        messages.success(self.request, f"Category '{self.object.name}' deleted!")
        return super().form_valid(form)


# Transactions

class TransactionList(LoginRequiredMixin, ListView):
    login_url = 'login'
    model = models.Transaction
    template_name = "budget/transaction/transaction_list.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        transactions_data = models.Transaction.objects.filter(account__profile__user=self.request.user).order_by(
            '-date').annotate(truncated_date=TruncDate('date'))
        category_ids = models.Transaction.objects.filter(account__profile__user=self.request.user).values_list(
            'category', flat=True).distinct()
        categories_data = models.Category.objects.filter(profile__user=self.request.user).filter(id__in=category_ids)
        transactions = []

        temp_date = transactions_data[0].truncated_date
        temp_total = 0
        temp_txns = []

        categories = {}
        for cat in categories_data:
            categories[cat] = {
                "label": cat.name,
                "data": [0],
                "backgroundColor": str(cat.color) + '2a',
                "borderColor": str(cat.color),
                "borderWidth": 2,
                "borderRadius": 5,
            }

        for txn in transactions_data:
            if txn.truncated_date != temp_date:
                transactions.append({
                    'date': temp_date,
                    'total': temp_total,
                    'txns': temp_txns
                })

                temp_date = txn.truncated_date
                temp_total = 0
                temp_txns = [txn]

                for cat, data in categories.items():
                    if cat == txn.category:
                        data['data'].append(txn.amount_default_currency if txn.amount_default_currency else txn.amount)
                    else:
                        data['data'].append(0)
            else:
                temp_txns.append(txn)

                for cat, data in categories.items():
                    if cat == txn.category:
                        data['data'][-1] += txn.amount_default_currency if txn.amount_default_currency else txn.amount

            if txn.amount_default_currency:
                amount = txn.amount_default_currency
            elif txn.txn_type == '>':
                amount = 0
            else:
                amount = txn.amount

            temp_total += amount
        else:
            transactions.append({
                'date': temp_date,
                'total': temp_total,
                'txns': temp_txns
            })

        for i in categories.values():
            i["data"] = i["data"][::-1]

        context["data_txn"] = {
            "labels": [i['date'].strftime("%d/%m") for i in transactions][::-1],
            "datasets": [i for i in categories.values()]
        }
        context["transactions"] = transactions

        return context

    def get_queryset(self):
        profile = Profile.objects.get(user=self.request.user)
        return super().get_queryset().filter(account__profile=profile)


class TransactionCreateView(LoginRequiredMixin, CreateView):
    login_url = reverse_lazy('login')
    model = models.Transaction
    form_class = forms.TransactionForm
    template_name = 'budget/transaction/transaction_create.html'
    success_url = reverse_lazy('transaction_list')

    def get_initial(self):
        initial = super().get_initial()

        if cat_id := self.request.GET.get('category'):
            cat = models.Category.objects.get(id=cat_id)
            initial['category'] = cat.name

        if acct_id := self.request.GET.get('account'):
            acct = models.Account.objects.get(id=acct_id)
            initial['account'] = acct.name

        return initial

    def form_valid(self, form):
        messages.success(self.request, f"Transaction '{form.cleaned_data.get('amount')}' created!")
        return super().form_valid(form)

    def form_invalid(self, form):
        messages.warning(self.request, "Something went wrong!")
        return super().form_invalid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        if cat_id := self.request.GET.get('category'):
            cat = models.Category.objects.get(id=cat_id)
            context['category'] = cat

        if acct_id := self.request.GET.get('account'):
            acct = models.Account.objects.get(id=acct_id)
            context['account'] = acct
            current_account_currency = acct.currency
            context['currency'] = current_account_currency

        if self.request.GET.get('transfer'):
            context['transfer'] = True
            context['category'] = models.Category.objects.filter(profile__user=self.request.user).get(
                cat_type=models.Category.TRANSFER)
            context['accounts'] = [acct for acct in
                                   models.Account.objects.filter(
                                       Q(profile__user=self.request.user) & Q(currency=current_account_currency)).all()
                                   if
                                   acct.id != int(acct_id)]
        else:
            context['accounts'] = models.Account.objects.filter(profile__user=self.request.user).all()
            context['categories'] = [(cat.id, cat.name) for cat in
                                     models.Category.objects.filter(profile__user=self.request.user).all() if
                                     cat.cat_type in models.Category.BASIC_CATEGORY_TYPES]

        context['currencies'] = models.Currency.objects.all()
        context['profile'] = Profile.objects.get(user=self.request.user)

        return context


class TransactionUpdateView(LoginRequiredMixin, UpdateView):
    login_url = reverse_lazy('login')
    model = models.Transaction
    form_class = forms.TransactionForm
    template_name = 'budget/transaction/transaction_edit.html'
    success_url = reverse_lazy('transaction_list')

    def form_valid(self, form):
        messages.success(self.request, f"Transaction '{form.cleaned_data.get('amount')}' updated!")
        return super().form_valid(form)

    def form_invalid(self, form):
        messages.warning(self.request, "Something went wrong!")
        return super().form_invalid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        context['categories'] = [(cat.id, cat.name) for cat in
                                 models.Category.objects.filter(profile__user=self.request.user).all()]
        context['accounts'] = [(acct.id, acct.name) for acct in
                               models.Account.objects.filter(profile__user=self.request.user).all()]
        context['currencies'] = models.Currency.objects.all()
        context['profile'] = Profile.objects.get(user=self.request.user)

        return context


class TransactionDeleteView(LoginRequiredMixin, DeleteView):
    login_url = reverse_lazy('login')
    model = models.Transaction
    template_name = 'budget/transaction/transaction_delete.html'
    success_url = reverse_lazy('transaction_list')

    def form_valid(self, form):
        messages.success(self.request, f"Transaction '{self.object.amount}' deleted!")
        return super().form_valid(form)


# Dashboard

class DashboardView(LoginRequiredMixin, TemplateView):
    login_url = 'login'
    template_name = 'budget/dashboard.html'

    def get_context_data(self, **kwargs):
        data_cat_query = (
            models.Category.objects
            .filter(profile__user=self.request.user)
            .annotate(data=Coalesce(Sum('transaction__amount'), 0.0))
            .annotate(labels=F('name'))
            .annotate(colors=F('color'))
            .values('labels', 'colors', 'data')
        )

        data_acct_query = (
            models.Account.objects
            .filter(profile__user=self.request.user)
            .annotate(
                data=Coalesce(Sum('transaction__amount'), 0.0) + Cast(F('balance'), output_field=FloatField())
            )
            .annotate(labels=F('name'))
            .annotate(colors=F('color'))
            .values('data', 'labels', 'colors')
        )

        last_txns = models.Transaction.objects.filter(account__profile__user=self.request.user).order_by('date')[:5]

        context = super().get_context_data(**kwargs)
        context['last_txns'] = last_txns
        context['data_acct'] = get_template_chart_data(data_acct_query)
        context['data_cat'] = get_template_chart_data(data_cat_query)

        return context


# Currency converter
def currency_converter_req(request):
    if request.method == 'POST':
        data = json.loads(request.body)
        res = currency_converter(float(data['amount']), data['from_ccy'], data['to_ccy'])

        response_data = {"result": res}
        return JsonResponse(response_data)
