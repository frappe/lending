<p>Dear Customer,</p>

<p>The value of the collateral pledged against your {% if doc.loan %}loan <strong>{{ doc.loan }}</strong>{% else %}loans{% endif %} has fallen. You owe {{ doc.get_formatted("loan_amount") }} against collateral now worth {{ doc.get_formatted("security_value") }}.</p>

{% if doc.status == "Sale Triggered" %}
<p>The fall is large enough that the lender will now sell part of the collateral to bring the loan back within its limit.</p>
{% else %}
<p>To restore the margin, repay <strong>{{ doc.get_formatted("shortfall_amount") }}</strong> or pledge more collateral by <strong>{{ frappe.utils.formatdate(doc.cure_by) }}</strong>. If the margin is not restored by then, the lender may sell the collateral.</p>
{% endif %}

<p>Thank you.</p>
