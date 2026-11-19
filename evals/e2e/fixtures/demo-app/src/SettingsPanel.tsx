import { Button } from "./components/Button";
import { Card } from "./components/Card";

export default function SettingsPanel() {
  return (
    <Card title="Account settings">
      <form className="settings-form" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <label className="field">
          <span>Display name</span>
          <input type="text" value="Mina Park" />
        </label>
        <label className="field">
          <span>Contact email</span>
          <input type="text" value="mina@example.com" />
        </label>
        <label className="field">
          <span>Notifications</span>
          <select>
            <option>Weekly summary</option>
            <option>Every change</option>
          </select>
        </label>
        <div className="actions">
          <Button variant="primary" type="submit">
            Save changes
          </Button>
          <Button variant="ghost">Cancel</Button>
        </div>
      </form>
    </Card>
  );
}
