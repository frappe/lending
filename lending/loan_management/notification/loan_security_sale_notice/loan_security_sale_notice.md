<p>Dear Customer,</p>

<p>Collateral pledged against your loan <strong>{{ doc.loan }}</strong> was sold for {{ doc.get_formatted("gross_proceeds") }}.</p>

<ul>
{% for item in doc.items %}{% if item.sold_qty %}
<li>{{ item.loan_security_name or item.loan_security }}: {{ item.sold_qty }} at {{ item.get_formatted("sale_price") }}</li>
{% endif %}{% endfor %}
</ul>

<p>The proceeds will be applied to your loan, and any amount left over will be refunded to you.</p>

<p>Thank you.</p>
