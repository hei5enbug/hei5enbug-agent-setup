import sys

from patch_tools import append, replace

repo = sys.argv[1]
replace(repo, "src/Profile.tsx", '''    <main className="profile">
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
    </main>''', '''    <main className="profile profile-columns">
      <div className="profile-column" data-testid="col-left">
        <Card title="Mina Park">
          <p className="muted">Product designer, Seoul</p>
          <Button variant="secondary">Edit profile</Button>
        </Card>
        <Card title="About">
          <p>Mina designs billing screens and keeps the team's component library tidy. She works on the account area.</p>
        </Card>
      </div>
      <div className="profile-column" data-testid="col-right">
        <Card title="Activity">
          <ul className="activity-list">
            {activity.map((entry) => (
              <li>{entry}</li>
            ))}
          </ul>
        </Card>
      </div>
    </main>''')
append(repo, "src/styles.css", '''
.profile-columns {
  max-width: 1040px;
  display: grid;
  grid-template-columns: 1fr 1fr;
  align-items: start;
  gap: 24px;
}

.profile-column {
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-width: 0;
}

@media (max-width: 640px) {
  .profile-columns {
    grid-template-columns: 1fr;
  }
}
''')
