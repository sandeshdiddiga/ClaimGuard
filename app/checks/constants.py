"""Rule constants and the CMS pages each check cites."""

from decimal import Decimal

# Federal Good Faith Estimate dispute process (uninsured and self-pay patients only).
GFE_DISPUTE_THRESHOLD = Decimal("400.00")  # billed at least this much over the estimate
GFE_DISPUTE_WINDOW_DAYS = 120  # from the date of the bill
GFE_DISPUTE_URL = (
    "https://www.cms.gov/marketplace/technical-assistance-resources/"
    "understanding-good-faith-estimate-and-dispute-resolution-process.pdf"
)

MUE_URL = (
    "https://www.cms.gov/medicare/coding-billing/national-correct-coding-initiative-ncci-edits/"
    "medicare-ncci-medically-unlikely-edits-mues"
)
ASP_URL = "https://www.cms.gov/medicare/payment/part-b-drugs/asp-pricing-files"
HCPCS_URL = "https://www.cms.gov/medicare/coding/hcpcsreleasecodesets/hcpcs-quarterly-update.html"

MUE_SOURCE = "CMS Medicare NCCI MUE table, facility outpatient hospital services, effective October 1, 2026"
ASP_SOURCE = "CMS Medicare Part B drug payment limits, October 2026"
HCPCS_SOURCE = "CMS HCPCS Level II alpha-numeric file, October 2026"
CPT_POLICY_SOURCE = "ClaimGuard data policy: no AMA CPT content"
GFE_SOURCE = "CMS: Good Faith Estimate and dispute resolution"
EOB_SOURCE = "Your insurer's Explanation of Benefits"
DUPLICATE_SOURCE = "Billing accuracy"
