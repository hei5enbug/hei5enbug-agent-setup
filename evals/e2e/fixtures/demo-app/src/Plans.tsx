import { Button } from "./components/Button";

const plans = [
  { name: "Starter", price: "$0", note: "One workspace, community support" },
  { name: "Team", price: "$12", note: "Ten workspaces, email support" },
  { name: "Business", price: "$40", note: "Unlimited workspaces, priority support" },
];

export default function Plans() {
  return (
    <main className="plans">
      <h1 className="page-title">Choose a plan</h1>
      <div className="plan-list">
        {plans.map((plan) => (
          <section className="plan">
            <h2 className="card-title">{plan.name}</h2>
            <p className="price">{plan.price}</p>
            <p className="muted">{plan.note}</p>
            <Button variant="primary">Select {plan.name}</Button>
          </section>
        ))}
      </div>
    </main>
  );
}
