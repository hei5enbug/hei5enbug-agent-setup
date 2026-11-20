import sys

from patch_tools import append, write

repo = sys.argv[1]
write(repo, "src/Invoices.tsx", '''import { Button } from "./components/Button";

const invoices = [
  { name: "March invoice", amount: "$120.00", status: "Paid" },
  { name: "April invoice", amount: "$120.00", status: "Paid" },
  { name: "May invoice", amount: "$135.00", status: "Due" },
];

export default function Invoices() {
  return (
    <main className="invoices">
      <h1 className="page-title">Invoices</h1>
      <div className="invoice-list" data-testid="invoice-list">
        {invoices.map((invoice) => (
          <div className="invoice-row" data-testid="invoice-row">
            <span>{invoice.name}</span>
            <span>{invoice.amount}</span>
            <span className="muted">{invoice.status}</span>
          </div>
        ))}
      </div>
      <Button variant="secondary">Download all</Button>
    </main>
  );
}
''')
append(repo, "src/styles.css", '''
.invoices {
  max-width: 720px;
}

.invoice-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 16px;
}

.invoice-row {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  padding: 12px 16px;
  background: #ffffff;
  border: 1px solid #d9dce5;
  border-radius: 8px;
}

@media (max-width: 480px) {
  .invoice-row {
    flex-direction: column;
    gap: 4px;
  }
}
''')
