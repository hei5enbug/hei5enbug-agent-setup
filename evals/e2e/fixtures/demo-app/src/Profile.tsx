import { Button } from "./components/Button";
import { Card } from "./components/Card";

const activity = [
  "Updated the shipping address",
  "Downloaded the March invoice",
  "Invited a teammate to the workspace",
  "Changed the weekly summary day",
];

export default function Profile() {
  return (
    <main className="profile">
      <Card title="Mina Park">
        <p className="muted">Product designer, Seoul</p>
        <Button variant="secondary">Edit profile</Button>
      </Card>
      <Card title="About">
        <p>Mina designs billing screens and keeps the team's component library tidy. She works on the account area.</p>
      </Card>
      <Card title="Activity">
        <ul className="activity-list">
          {activity.map((entry) => (
            <li>{entry}</li>
          ))}
        </ul>
      </Card>
    </main>
  );
}
