"""Form nhập tờ trình (phần đầu, dòng hàng, phân bổ ngân sách) dùng cho giao diện lập tờ trình."""

from django import forms

from apps.vendors.models import ACTIVE, Vendor

from .models import Requisition, RequisitionFunding, RequisitionLine


class RequisitionForm(forms.ModelForm):
    class Meta:
        model = Requisition
        fields = [
            "title", "requester_unit", "procurement_type", "necessity", "currency", "service_start", "months",
            "vendor", "quote_exception_reason", "consult_units",
        ]
        widgets = {
            "service_start": forms.DateInput(attrs={"type": "date"}),
            "necessity": forms.Textarea(attrs={"rows": 4}),
            "quote_exception_reason": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["vendor"].queryset = Vendor.objects.filter(status=ACTIVE)

    def clean_currency(self):
        return (self.cleaned_data["currency"] or "").strip().upper()


class RequisitionLineForm(forms.ModelForm):
    class Meta:
        model = RequisitionLine
        fields = ["description", "quantity", "unit_price", "vat_rate"]


class RequisitionFundingForm(forms.ModelForm):
    class Meta:
        model = RequisitionFunding
        fields = ["budget_line", "amount_vnd"]


LineFormSet = forms.inlineformset_factory(
    Requisition, RequisitionLine, form=RequisitionLineForm, extra=1, min_num=1, validate_min=True,
    can_delete=True,
)
FundingFormSet = forms.inlineformset_factory(
    Requisition, RequisitionFunding, form=RequisitionFundingForm, extra=1, min_num=1, validate_min=True,
    can_delete=True,
)
