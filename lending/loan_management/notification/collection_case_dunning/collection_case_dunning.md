<p>Dear Customer,</p>

<p>Your loan <strong>{{ doc.loan }}</strong> is {{ doc.days_past_due }} days past due. The amount currently overdue is <strong>{{ doc.get_formatted_overdue_amount() }}</strong>. Please pay this at the earliest to avoid further charges. (Remaining loan balance: {{ doc.get_formatted("outstanding_amount") }})</p>

<p>Thank you.</p>
