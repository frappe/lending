Use these APIs to send an OTP to the applicant on a [Loan Lead](/lending/loan-lead) and verify it. Set up [OTP Verification](/lending/otp-verification) first. The lead must be a draft, the medium must be checked in Loan Origination Settings, and the API user must have write permission on the lead.

# Get Enabled OTP Mediums

Endpoint: GET /api/method/lending.loan_origination.doctype.loan_lead.loan_lead.get_enabled_otp_mediums

Response
```json
{
    "message": ["Email", "SMS"]
}
```

# Send OTP

Endpoint: POST /api/method/lending.loan_origination.doctype.loan_lead.loan_lead.send_otp

Request Body
```json
{
    "loan_lead": "LN-LEAD-01984",
    "medium": "SMS"
}
```

Response
```json
{
    "message": {
        "sent": true,
        "expires_in": 300
    }
}
```

`expires_in` is in seconds. A new OTP replaces the earlier one for the same lead and medium.

# Verify OTP

Endpoint: POST /api/method/lending.loan_origination.doctype.loan_lead.loan_lead.verify_otp

Request Body
```json
{
    "loan_lead": "LN-LEAD-01984",
    "medium": "SMS",
    "otp": "482913"
}
```

Response
```json
{
    "message": {
        "verified": true
    }
}
```

Response for a wrong or expired OTP
```json
{
    "message": {
        "verified": false,
        "reason": "invalid_or_expired"
    }
}
```

# Bulk Send OTP

Endpoint: POST /api/method/lending.loan_origination.doctype.loan_lead.loan_lead.bulk_send_otp

Sends an OTP to up to 50 leads in one request.

Request Body
```json
{
    "loan_leads": ["LN-LEAD-01984", "LN-LEAD-01985", "LN-LEAD-01987"],
    "medium": "Email"
}
```

Response
```json
{
    "message": {
        "sent": ["LN-LEAD-01984", "LN-LEAD-01987"],
        "failed": [
            {
                "loan_lead": "LN-LEAD-01985",
                "error": "Email is already verified for this lead."
            }
        ]
    }
}
```
