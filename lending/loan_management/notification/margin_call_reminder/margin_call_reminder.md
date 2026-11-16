<p>Dear Customer,</p>

<p>The margin call on your {% if doc.loan %}loan <strong>{{ doc.loan }}</strong>{% else %}loans{% endif %} is still open. Repay <strong>{{ doc.get_formatted("shortfall_amount") }}</strong> or pledge more collateral by <strong>{{ frappe.utils.formatdate(doc.cure_by) }}</strong>. If the margin is not restored by then, the lender may sell the collateral.</p>

<p>Thank you.</p>
