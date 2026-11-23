import sys

from patch_tools import append, replace

repo = sys.argv[1]

append(repo, "shop/models.py", '''

@dataclass(frozen=True)
class Customer:
    id: int
    name: str
    tier: str
    email: str | None = None
''')
replace(repo, "shop/customers.py", "from .errors import UnknownCustomer\n", "from .errors import UnknownCustomer\nfrom .models import Customer\n")
replace(repo, "shop/customers.py", "customer_id: int) -> dict:", "customer_id: int) -> Customer:")
replace(repo, "shop/customers.py", '    return {"id": customer_id, "name": raw["name"], "tier": raw["tier"]}\n',
        '    return Customer(id=customer_id, name=raw["name"], tier=raw["tier"], email=raw.get("email"))\n')
replace(repo, "shop/orders.py", 'tier_discount_cents(customer["tier"], subtotal)', "tier_discount_cents(customer.tier, subtotal)")
replace(repo, "shop/mailing.py", "return f\"{customer['name']} (customer {customer['id']})\"", "return f\"{customer.name} (customer {customer.id})\"")
replace(repo, "shop/cli.py", "        print(f\"{customer['name']} ({customer['tier']})\", file=out)\n",
        "        print(f\"{customer.name} ({customer.tier})\", file=out)\n        if customer.email:\n            print(f\"email: {customer.email}\", file=out)\n")
append(repo, "tests/test_customers.py", '''

def test_a_customer_without_an_email_has_none(data_file):
    assert lookup_customer(data_file, 2).email is None
''')
replace(repo, "README.md", "- `lookup CUSTOMER_ID` prints the customer's name and tier.", "- `lookup CUSTOMER_ID` prints the customer's name and tier, and the email on a second line when one is stored.")
replace(repo, "docs/ko/README.ko.md", "- `lookup CUSTOMER_ID`는 고객의 이름과 등급을 출력합니다.", "- `lookup CUSTOMER_ID`는 고객의 이름과 등급을 출력하고, 저장된 이메일이 있으면 둘째 줄에 출력합니다.")
